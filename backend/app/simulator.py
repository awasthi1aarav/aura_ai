"""Built-in sensor simulator.

Produces realistic readings for every active sensor that has NOT received real device
data in the last 60 s. Real sensors (POST /api/ingest) automatically take over.
Scenarios let you inject a medical or ship event for demos.
"""
import asyncio
import logging
import random
from datetime import timedelta, timezone

from sqlalchemy import delete, insert, select

from . import db
from .metrics import DECIMALS, SHIP_NOMINAL, SIM_NOISE

log = logging.getLogger("aura.sim")
TICK_SECONDS = 5
KEEP_HOURS = 3

SCENARIOS = {
    "none": "Normal operations",
    "hypoxia": "Hypoxia — falling SpO₂ in one crew member",
    "fever": "Fever / infection onset in one crew member",
    "hypertension": "Rising blood pressure in one crew member",
    "co2_fault": "CO₂ scrubber fault — cabin CO₂ climbing",
    "cabin_leak": "Slow cabin leak — pressure and O₂ dropping",
    "solar_event": "Solar particle event — radiation spike",
}
CREW_SCENARIOS = {"hypoxia", "fever", "hypertension"}

_state: dict[int, float] = {}


def _offset(scenario, minutes, metric, is_target, subject):
    m = minutes
    if scenario == "hypoxia" and is_target:
        return {"spo2": -min(m * 0.9, 13), "heart_rate": min(m * 2.4, 34),
                "resp_rate": min(m * 0.8, 11)}.get(metric, 0)
    if scenario == "fever" and is_target:
        return {"body_temp": min(m * 0.12, 2.7), "heart_rate": min(m * 1.6, 26),
                "resp_rate": min(m * 0.4, 6)}.get(metric, 0)
    if scenario == "hypertension" and is_target:
        return {"bp_sys": min(m * 5.0, 70), "bp_dia": min(m * 2.6, 34),
                "heart_rate": min(m * 0.8, 12)}.get(metric, 0)
    if scenario == "co2_fault":
        if metric == "cabin_co2":
            return min(m * 0.12, 2.8)
        if subject == "crew" and metric == "resp_rate":
            return min(m * 0.3, 4)
    if scenario == "cabin_leak":
        return {"cabin_pressure": -min(m * 0.6, 14), "cabin_o2": -min(m * 1.2, 32)}.get(metric, 0)
    if scenario == "solar_event" and metric == "radiation":
        return min(m * 25, 170)
    return 0


ACTIVE_MINUTES = 30   # missions nobody has opened for this long stop simulating (saves the free DB)


def _tick_mission(conn, m, t):
    scenario = m.scenario or "none"
    target = str(m.scenario_crew or "")
    started = m.scenario_started
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    minutes = max(0.0, (t - started).total_seconds() / 60) if started else 0.0
    crew_rows = {r.id: r for r in conn.execute(select(db.crew).where(db.crew.c.mission_id == m.id))}
    rows = []
    fresh = t - timedelta(seconds=60)
    for s in conn.execute(select(db.sensors).where(db.sensors.c.mission_id == m.id,
                                                   db.sensors.c.active.is_(True))):
        last_dev = s.last_device_at
        if last_dev is not None and last_dev.tzinfo is None:
            last_dev = last_dev.replace(tzinfo=timezone.utc)
        if last_dev and last_dev > fresh:
            continue  # a real device is feeding this sensor
        if s.subject == "crew":
            c = crew_rows.get(s.crew_id)
            base = getattr(c, f"base_{s.metric}", None) if c else None
        else:
            base = SHIP_NOMINAL.get(s.metric)
        if base is None:
            continue
        is_target = s.subject == "crew" and str(s.crew_id) == target
        goal = base + _offset(scenario, minutes, s.metric, is_target, s.subject)
        prev = _state.get(s.id, base)
        val = prev + 0.35 * (goal - prev) + random.gauss(0, SIM_NOISE.get(s.metric, 0.5))
        if s.metric == "spo2":
            val = min(val, 100)
        val = max(val, 0)
        _state[s.id] = val
        rows.append(dict(sensor_id=s.id, value=round(val, DECIMALS.get(s.metric, 2)), ts=t, source="simulator"))
    return rows


def tick():
    t = db.now()
    active_since = t - timedelta(minutes=ACTIVE_MINUTES)
    with db.engine.begin() as conn:
        ms = list(conn.execute(select(db.missions).where(
            db.missions.c.simulator.is_(True),
            (db.missions.c.is_demo.is_(True)) | (db.missions.c.last_active >= active_since))))
        rows = []
        for m in ms:
            rows += _tick_mission(conn, m, t)
        if rows:
            conn.execute(insert(db.readings), rows)


IDLE_DAYS = 7         # hosted missions untouched this long are deleted


def prune():
    with db.engine.begin() as conn:
        conn.execute(delete(db.readings).where(
            db.readings.c.ts < db.now() - timedelta(hours=KEEP_HOURS),
            db.readings.c.source == "simulator"))
        idle = conn.execute(select(db.missions.c.id).where(
            db.missions.c.is_demo.is_(False),
            db.missions.c.last_active < db.now() - timedelta(days=IDLE_DAYS))).all()
        for (mid,) in idle:
            db.delete_mission(conn, mid)


async def run_forever():
    n = 0
    while True:
        try:
            await asyncio.to_thread(tick)
            n += 1
            if n % 60 == 0:
                await asyncio.to_thread(prune)
        except Exception:  # keep the loop alive no matter what
            log.exception("simulator tick failed")
        await asyncio.sleep(TICK_SECONDS)
