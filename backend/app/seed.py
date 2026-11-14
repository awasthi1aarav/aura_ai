"""Fictional demo history: past daily check-ins and 7 days of hourly sensor history.
Everything here is simulated and labelled as demo data in the interface."""
import math
import random
from datetime import timedelta, timezone

from sqlalchemy import insert, select

from . import db
from .metrics import DECIMALS, SHIP_NOMINAL, SIM_NOISE

SYMPTOM_POOL = ["headache", "congestion", "back pain", "fatigue", "poor sleep"]


def seed_checkins(conn, mission_id, crew_id, days=7, older_than_days=-1):
    rnd = random.Random(crew_id * 7919)
    name = conn.execute(select(db.crew.c.name).where(db.crew.c.id == crew_id)).scalar() or ""
    sleepy = "Rahman" in name          # one demo crew member has a worsening sleep trend
    skip_today = "Ferreira" in name     # one demo crew member hasn't checked in yet today
    t = db.now()
    rows = []
    for d in range(days, older_than_days, -1):
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
                         connection=max(2, min(5, round(rnd.gauss(4.0, 0.6)) - (1 if sleepy and d <= 2 else 0))),
                         stress=max(1, min(5, round(rnd.gauss(2.2, 0.6)) + (1 if sleepy and d <= 2 else 0))),
                         exercise_min=round(max(0, rnd.gauss(110, 20))), symptoms=",".join(sym), note=""))
    if rows:
        conn.execute(insert(db.checkins), rows)
    ev = []
    for d in range(days, older_than_days, -1):        # calls home about twice a week, crew time most days
        day = t - timedelta(days=d)
        if d > 0 and rnd.random() < (0.12 if sleepy else 0.3):
            ev.append(dict(mission_id=mission_id, crew_id=crew_id, kind="call_home", note="",
                           ts=day.replace(hour=19, minute=rnd.randint(0, 50), second=0, microsecond=0)))
        if d > 0 and rnd.random() < 0.6:
            ev.append(dict(mission_id=mission_id, crew_id=crew_id, kind="crew_time", note="",
                           ts=day.replace(hour=20, minute=rnd.randint(0, 50), second=0, microsecond=0)))
    if ev:
        conn.execute(insert(db.wellbeing), ev)


def seed_history(conn, mission_id, days=7, end=None):
    """Hourly averages for `days` days, ending at `end` (default: 3 hours ago; live data covers the rest)."""
    crew_rows = {r.id: r for r in conn.execute(select(db.crew).where(db.crew.c.mission_id == mission_id))}
    sensors = list(conn.execute(select(db.sensors).where(db.sensors.c.mission_id == mission_id)))
    end = end or db.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
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


def backfill_wellbeing(conn, mission_id):
    """Demo missions made before the wellbeing feature: add connection/stress values and contact events."""
    from sqlalchemy import update
    crew = conn.execute(select(db.crew.c.id, db.crew.c.name).where(db.crew.c.mission_id == mission_id)).all()
    t = db.now()
    for cid, name in crew:
        rnd = random.Random(cid * 31337)
        sleepy = "Rahman" in name
        for ck in conn.execute(select(db.checkins.c.id, db.checkins.c.ts).where(
                db.checkins.c.crew_id == cid, db.checkins.c.connection.is_(None))).all():
            ts = ck.ts if ck.ts.tzinfo else ck.ts.replace(tzinfo=timezone.utc)
            recent = (t - ts).days <= 2
            conn.execute(update(db.checkins).where(db.checkins.c.id == ck.id).values(
                connection=max(2, min(5, round(rnd.gauss(4.0, 0.6)) - (1 if sleepy and recent else 0))),
                stress=max(1, min(5, round(rnd.gauss(2.2, 0.6)) + (1 if sleepy and recent else 0)))))
        ev = []
        for d in range(60, 0, -1):
            day = t - timedelta(days=d)
            if rnd.random() < (0.12 if sleepy else 0.3):
                ev.append(dict(mission_id=mission_id, crew_id=cid, kind="call_home", note="",
                               ts=day.replace(hour=19, minute=rnd.randint(0, 50), second=0, microsecond=0)))
            if rnd.random() < 0.6:
                ev.append(dict(mission_id=mission_id, crew_id=cid, kind="crew_time", note="",
                               ts=day.replace(hour=20, minute=rnd.randint(0, 50), second=0, microsecond=0)))
        if ev:
            conn.execute(insert(db.wellbeing), ev)
