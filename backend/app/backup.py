"""Mission backup (export) and restore. Backups never contain passwords, sensor API keys or chats."""
import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import insert, select

from . import db
from .metrics import ALL_METRICS, CHECKIN_METRICS, CREW_METRICS

FORMAT = 1


def _iso(t):
    if t is None:
        return None
    return (t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t).isoformat()


def export_mission(m):
    with db.engine.connect() as conn:
        crew = list(conn.execute(select(db.crew).where(db.crew.c.mission_id == m.id).order_by(db.crew.c.id)))
        sens = list(conn.execute(select(db.sensors).where(db.sensors.c.mission_id == m.id).order_by(db.sensors.c.id)))
        sids = [s.id for s in sens] or [-1]
        return {
            "aura_backup": FORMAT, "exported": _iso(db.now()),
            "mission": {"name": m.name, "environment": m.environment, "mission_start": _iso(m.mission_start)},
            "limits": [dict(metric=r.metric, warn_low=r.warn_low, warn_high=r.warn_high, crit_low=r.crit_low,
                            crit_high=r.crit_high) for r in conn.execute(select(db.limits).where(db.limits.c.mission_id == m.id))],
            "crew": [dict(ref=c.id, name=c.name, role=c.role, notes=c.notes,
                          baseline={k: getattr(c, f"base_{k}") for k in CREW_METRICS}) for c in crew],
            "sensors": [dict(ref=s.id, name=s.name, metric=s.metric, subject=s.subject, crew_ref=s.crew_id,
                             active=bool(s.active)) for s in sens],
            "checkins": [dict(crew_ref=r.crew_id, ts=_iso(r.ts), glucose=r.glucose, sleep_hours=r.sleep_hours,
                              mood=r.mood, connection=r.connection, stress=r.stress,
                              exercise_min=r.exercise_min, symptoms=r.symptoms or "", note=r.note or "")
                         for r in conn.execute(select(db.checkins).where(db.checkins.c.mission_id == m.id)
                                               .order_by(db.checkins.c.ts))],
            "history": [dict(sensor_ref=r.sensor_id, hour=_iso(r.hour), avg=r.avg, min=r.min, max=r.max, n=r.n)
                        for r in conn.execute(select(db.rollups).where(db.rollups.c.sensor_id.in_(sids))
                                              .order_by(db.rollups.c.hour))],
            "readings": [dict(sensor_ref=r.sensor_id, ts=_iso(r.ts), value=r.value, source=r.source)
                         for r in conn.execute(select(db.readings).where(db.readings.c.sensor_id.in_(sids),
                                                                         db.readings.c.source != "simulator")
                                               .order_by(db.readings.c.ts))],
            "wellbeing": [dict(crew_ref=r.crew_id, ts=_iso(r.ts), kind=r.kind, note=r.note or "")
                          for r in conn.execute(select(db.wellbeing).where(db.wellbeing.c.mission_id == m.id)
                                                .order_by(db.wellbeing.c.ts))],
            "alerts": [dict(crew_ref=r.crew_id, kind=r.kind, severity=r.severity, metric=r.metric,
                            message=r.message, hazard=r.hazard, risk=r.risk, started=_iso(r.started),
                            ended=_iso(r.ended))
                       for r in conn.execute(select(db.alert_log).where(db.alert_log.c.mission_id == m.id)
                                             .order_by(db.alert_log.c.started))],
        }


def export_csv(m, what):
    buf = io.StringIO()
    w = csv.writer(buf)
    with db.engine.connect() as conn:
        names = dict(conn.execute(select(db.crew.c.id, db.crew.c.name).where(db.crew.c.mission_id == m.id)).all())
        if what == "checkins":
            w.writerow(["time_utc", "crew_member", "blood_sugar_mg_dl", "sleep_hours", "mood_1_5",
                        "connection_1_5", "stress_1_5", "exercise_min", "symptoms", "note"])
            for r in conn.execute(select(db.checkins).where(db.checkins.c.mission_id == m.id).order_by(db.checkins.c.ts)):
                w.writerow([_iso(r.ts), names.get(r.crew_id, ""), r.glucose, r.sleep_hours, r.mood, r.connection,
                            r.stress, r.exercise_min,
                            (r.symptoms or "").replace(",", "; "), r.note or ""])
        else:
            sens = {s.id: s for s in conn.execute(select(db.sensors).where(db.sensors.c.mission_id == m.id))}
            w.writerow(["hour_utc", "subject", "metric", "unit", "average", "min", "max", "samples"])
            for r in conn.execute(select(db.rollups).where(db.rollups.c.sensor_id.in_(list(sens) or [-1]))
                                  .order_by(db.rollups.c.hour, db.rollups.c.sensor_id)):
                s = sens[r.sensor_id]
                spec = ALL_METRICS.get(s.metric, {})
                w.writerow([_iso(r.hour), names.get(s.crew_id, "Habitat") if s.subject == "crew" else "Habitat",
                            s.metric, spec.get("unit", ""), round(r.avg, 3), round(r.min, 3), round(r.max, 3), r.n])
    return buf.getvalue()


# ---------- restore ----------
def _f(x):
    return None if x is None else float(x)


class BCrew(BaseModel):
    ref: int
    name: str = Field(min_length=1, max_length=80)
    role: str = Field("", max_length=80)
    notes: str = Field("", max_length=500)
    baseline: dict[str, Optional[float]] = {}


class BSensor(BaseModel):
    ref: int
    name: str = Field(min_length=1, max_length=120)
    metric: str
    subject: str = Field(pattern="^(crew|ship)$")
    crew_ref: Optional[int] = None
    active: bool = True


class BLimit(BaseModel):
    metric: str
    warn_low: Optional[float] = None
    warn_high: Optional[float] = None
    crit_low: Optional[float] = None
    crit_high: Optional[float] = None


class BCheckin(BaseModel):
    crew_ref: int
    ts: datetime
    glucose: Optional[float] = Field(None, ge=0, le=1000)
    sleep_hours: Optional[float] = Field(None, ge=0, le=24)
    mood: Optional[float] = Field(None, ge=1, le=5)
    connection: Optional[float] = Field(None, ge=1, le=5)
    stress: Optional[float] = Field(None, ge=1, le=5)
    exercise_min: Optional[float] = Field(None, ge=0, le=1440)
    symptoms: str = Field("", max_length=500)
    note: str = Field("", max_length=500)


class BHour(BaseModel):
    sensor_ref: int
    hour: datetime
    avg: float
    min: float
    max: float
    n: int = 1


class BReading(BaseModel):
    sensor_ref: int
    ts: datetime
    value: float
    source: str = Field("import", pattern="^(device|manual|import)$")


class BAlert(BaseModel):
    crew_ref: Optional[int] = None
    kind: str = Field(max_length=12)
    severity: str = Field(pattern="^(watch|warning|critical)$")
    metric: Optional[str] = Field(None, max_length=40)
    message: str = Field("", max_length=300)
    hazard: Optional[str] = Field(None, max_length=20)
    risk: Optional[str] = Field(None, max_length=120)
    started: datetime
    ended: Optional[datetime] = None


class BWellbeing(BaseModel):
    crew_ref: int
    ts: datetime
    kind: str = Field(pattern="^(call_home|crew_time|support_request)$")
    note: str = Field("", max_length=300)


class BMission(BaseModel):
    name: str = ""
    environment: Optional[str] = None
    mission_start: Optional[datetime] = None


class Backup(BaseModel):
    aura_backup: int
    mission: BMission
    limits: list[BLimit] = Field([], max_length=50)
    crew: list[BCrew] = Field([], max_length=12)
    sensors: list[BSensor] = Field([], max_length=120)
    checkins: list[BCheckin] = Field([], max_length=20_000)
    history: list[BHour] = Field([], max_length=150_000)
    readings: list[BReading] = Field([], max_length=50_000)
    alerts: list[BAlert] = Field([], max_length=20_000)
    wellbeing: list[BWellbeing] = Field([], max_length=20_000)


def _utc(t):
    return t.replace(tzinfo=timezone.utc) if t and t.tzinfo is None else t


def restore(raw: bytes, name: str, pw_hash: str, code: str, environment_ok):
    try:
        b = Backup.model_validate(json.loads(raw.decode("utf-8-sig")))
    except Exception as e:
        raise ValueError(f"Not a valid AURA backup ({str(e).splitlines()[0][:120]})")
    if b.aura_backup != FORMAT:
        raise ValueError("Unsupported backup version")
    env = b.mission.environment if environment_ok(b.mission.environment) else "spacecraft"
    with db.engine.begin() as conn:
        mid = db.create_mission(conn, name, pw_hash, code=code, demo_crew=False, environment=env)
        from sqlalchemy import delete, update
        if b.mission.mission_start:
            conn.execute(update(db.missions).where(db.missions.c.id == mid).values(mission_start=_utc(b.mission.mission_start)))
        for l in b.limits:
            if l.metric in ALL_METRICS:
                conn.execute(update(db.limits).where(db.limits.c.mission_id == mid, db.limits.c.metric == l.metric)
                             .values(warn_low=l.warn_low, warn_high=l.warn_high, crit_low=l.crit_low, crit_high=l.crit_high))
        crew_map = {}
        for c in b.crew:
            base = {k: v for k, v in c.baseline.items() if k in CREW_METRICS and v is not None}
            crew_map[c.ref] = conn.execute(insert(db.crew).values(
                mission_id=mid, name=c.name, role=c.role, notes=c.notes,
                **{f"base_{k}": v for k, v in base.items()})).inserted_primary_key[0]
        # replace the default ship sensors with the backed-up ones
        conn.execute(delete(db.sensors).where(db.sensors.c.mission_id == mid))
        sensor_map = {}
        for s in b.sensors:
            if s.metric not in ALL_METRICS or s.metric in CHECKIN_METRICS:
                continue
            if s.subject == "crew" and s.crew_ref not in crew_map:
                continue
            sensor_map[s.ref] = conn.execute(insert(db.sensors).values(
                mission_id=mid, name=s.name, metric=s.metric, subject=s.subject,
                crew_id=crew_map.get(s.crew_ref) if s.subject == "crew" else None,
                api_key=db.new_key(), active=s.active)).inserted_primary_key[0]

        def chunks(rows):
            for i in range(0, len(rows), 2000):
                yield rows[i:i + 2000]
        rows = [dict(mission_id=mid, crew_id=crew_map[c.crew_ref], ts=_utc(c.ts), glucose=c.glucose,
                     sleep_hours=c.sleep_hours, mood=c.mood, connection=c.connection, stress=c.stress,
                     exercise_min=c.exercise_min,
                     symptoms=c.symptoms, note=c.note) for c in b.checkins if c.crew_ref in crew_map]
        for ch in chunks(rows):
            conn.execute(insert(db.checkins), ch)
        rows = [dict(sensor_id=sensor_map[h.sensor_ref], hour=_utc(h.hour), avg=h.avg, min=h.min, max=h.max, n=h.n)
                for h in b.history if h.sensor_ref in sensor_map]
        for ch in chunks(rows):
            conn.execute(insert(db.rollups), ch)
        rows = [dict(sensor_id=sensor_map[r.sensor_ref], ts=_utc(r.ts), value=r.value, source=r.source)
                for r in b.readings if r.sensor_ref in sensor_map]
        for ch in chunks(rows):
            conn.execute(insert(db.readings), ch)
        rows = [dict(mission_id=mid, crew_id=crew_map[w.crew_ref], ts=_utc(w.ts), kind=w.kind, note=w.note)
                for w in b.wellbeing if w.crew_ref in crew_map]
        for ch in chunks(rows):
            conn.execute(insert(db.wellbeing), ch)
        rows = [dict(mission_id=mid, crew_id=crew_map.get(a.crew_ref), key=f"restored|{i}", kind=a.kind,
                     severity=a.severity, metric=a.metric, message=a.message, hazard=a.hazard, risk=a.risk,
                     started=_utc(a.started), ended=_utc(a.ended) or _utc(a.started))
                for i, a in enumerate(b.alerts) if a.crew_ref is None or a.crew_ref in crew_map]
        for ch in chunks(rows):
            conn.execute(insert(db.alert_log), ch)
    hours = [h.hour for h in b.history]
    span = (max(hours) - min(hours)).days + 1 if hours else 0
    return mid, dict(crew=len(crew_map), sensors=len(sensor_map), checkins=len(b.checkins),
                     history_days=span, alerts=len(b.alerts))
