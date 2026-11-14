"""Fictional demo history: past daily check-ins and 7 days of hourly sensor history.
Everything here is simulated and labelled as demo data in the interface."""
import math
import random
from datetime import timedelta

from sqlalchemy import insert, select

from . import db
from .metrics import DECIMALS, SHIP_NOMINAL, SIM_NOISE

SYMPTOM_POOL = ["headache", "congestion", "back pain", "fatigue", "poor sleep"]


def seed_checkins(conn, mission_id, crew_id, days=7):
    rnd = random.Random(crew_id * 7919)
    name = conn.execute(select(db.crew.c.name).where(db.crew.c.id == crew_id)).scalar() or ""
    sleepy = "Rahman" in name          # one demo crew member has a worsening sleep trend
    skip_today = "Ferreira" in name     # one demo crew member hasn't checked in yet today
    t = db.now()
    rows = []
    for d in range(days, -1, -1):
        if d == 0 and skip_today:
            continue
        day = t - timedelta(days=d)
        ts = day.replace(hour=7, minute=rnd.randint(0, 40), second=0, microsecond=0)
        if ts > t:
            ts = t - timedelta(minutes=5)
        sleep = 6.6 - (3 - d) * 0.45 if sleepy and d <= 3 else rnd.gauss(7.3, 0.4)
        sym = rnd.sample(SYMPTOM_POOL, 1) if rnd.random() < 0.25 else []
        if sleepy and d <= 2:
            sym = ["poor sleep"]
        rows.append(dict(mission_id=mission_id, crew_id=crew_id, ts=ts,
                         glucose=round(rnd.gauss(94, 7)), sleep_hours=round(max(3.5, sleep), 1),
                         mood=max(2, min(5, round(rnd.gauss(4.1, 0.6)) - (1 if sleepy and d <= 1 else 0))),
                         exercise_min=round(max(0, rnd.gauss(110, 20))), symptoms=",".join(sym), note=""))
    if rows:
        conn.execute(insert(db.checkins), rows)


def seed_history(conn, mission_id, days=7):
    """Hourly averages for the last `days` days, ending 3 hours ago (live data covers the rest)."""
    crew_rows = {r.id: r for r in conn.execute(select(db.crew).where(db.crew.c.mission_id == mission_id))}
    sensors = list(conn.execute(select(db.sensors).where(db.sensors.c.mission_id == mission_id)))
    end = db.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    rows = []
    for s in sensors:
        rnd = random.Random(s.id * 104729)
        if s.subject == "crew":
            c = crew_rows.get(s.crew_id)
            base = getattr(c, f"base_{s.metric}", None) if c else None
        else:
            base = SHIP_NOMINAL.get(s.metric)
        if base is None:
            continue
        noise = SIM_NOISE.get(s.metric, 0.5)
        for h in range(days * 24, 0, -1):
            hour = end - timedelta(hours=h)
            diurnal = math.sin((hour.hour - 6) / 24 * 2 * math.pi)
            swing = {"heart_rate": 5, "body_temp": 0.25, "bp_sys": 4, "resp_rate": 1,
                     "cabin_co2": 0.15, "cabin_temp": 0.4}.get(s.metric, 0)
            v = base + swing * diurnal + rnd.gauss(0, noise * 0.6)
            if s.metric == "spo2":
                v = min(v, 99.5)
            d = DECIMALS.get(s.metric, 2) + 1
            rows.append(dict(sensor_id=s.id, hour=hour, avg=round(v, d), min=round(v - noise, d),
                             max=round(v + noise, d), n=720))
    for i in range(0, len(rows), 2000):
        conn.execute(insert(db.rollups), rows[i:i + 2000])
