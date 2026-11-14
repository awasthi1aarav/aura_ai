"""Database layer. Uses Postgres (Supabase) when DATABASE_URL is set, else a local SQLite file.

Everything belongs to a *mission* (like a game server): crew, sensors, limits, simulator state,
chats and the activity log are all scoped by mission_id, so changes in one mission never affect another.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, MetaData,
                        String, Table, Text, UniqueConstraint, create_engine, insert, inspect, select)

from .metrics import ALL_METRICS, CREW_METRICS, DEFAULT_BASELINE, SHIP_METRICS

url = os.getenv("DATABASE_URL", "sqlite:///./aura.db")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, pool_pre_ping=True, future=True, pool_size=5, max_overflow=5,
                       **({"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}))
meta = MetaData()
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DEMO_CODE = "DEMO"


def now():
    return datetime.now(timezone.utc)


missions = Table("missions", meta,
    Column("id", Integer, primary_key=True),
    Column("code", String(12), nullable=False, unique=True),
    Column("name", String(60), nullable=False),
    Column("pw_hash", String(200), nullable=False),            # mission (host) password
    Column("is_demo", Boolean, default=False),
    Column("environment", String(20), default="spacecraft"),
    Column("simulator", Boolean, default=True),
    Column("scenario", String(30), default="none"),
    Column("scenario_crew", Integer, nullable=True),
    Column("scenario_started", DateTime(timezone=True), nullable=True),
    Column("mission_start", DateTime(timezone=True), default=now),
    Column("created_at", DateTime(timezone=True), default=now),
    Column("last_active", DateTime(timezone=True), default=now),
)

crew = Table("crew", meta,
    Column("id", Integer, primary_key=True),
    Column("mission_id", Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(80), nullable=False),
    Column("role", String(80), default=""),
    Column("notes", Text, default=""),
    *[Column(f"base_{m}", Float) for m in CREW_METRICS],
    Column("created_at", DateTime(timezone=True), default=now),
)

sensors = Table("sensors", meta,
    Column("id", Integer, primary_key=True),
    Column("mission_id", Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("metric", String(40), nullable=False),
    Column("subject", String(10), nullable=False),          # 'crew' or 'ship'
    Column("crew_id", Integer, ForeignKey("crew.id", ondelete="CASCADE"), nullable=True),
    Column("api_key", String(64), nullable=False),
    Column("active", Boolean, default=True),
    Column("last_device_at", DateTime(timezone=True), nullable=True),
)

readings = Table("readings", meta,
    Column("id", Integer, primary_key=True),
    Column("sensor_id", Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False),
    Column("value", Float, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False, default=now),
    Column("source", String(12), default="simulator"),       # simulator | device | manual | import
)
Index("ix_readings_sensor_ts", readings.c.sensor_id, readings.c.ts)

limits = Table("limits", meta,
    Column("id", Integer, primary_key=True),
    Column("mission_id", Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
    Column("metric", String(40), nullable=False),
    Column("label", String(60)),
    Column("unit", String(20)),
    Column("warn_low", Float), Column("warn_high", Float),
    Column("crit_low", Float), Column("crit_high", Float),
    Column("source", Text),
    UniqueConstraint("mission_id", "metric"),
)

chats = Table("chats", meta,
    Column("id", Integer, primary_key=True),
    Column("mission_id", Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
    Column("crew_id", Integer, ForeignKey("crew.id", ondelete="CASCADE"), nullable=True),
    Column("client_id", String(64), nullable=False),          # private per-browser conversations
    Column("role", String(10), nullable=False),               # user | assistant
    Column("text", Text, nullable=False),
    Column("source", String(10), default=""),                 # gemini | offline
    Column("ts", DateTime(timezone=True), nullable=False, default=now),
)
Index("ix_chats_scope", chats.c.mission_id, chats.c.client_id, chats.c.crew_id, chats.c.ts)

checkins = Table("checkins", meta,                            # astronaut daily self check-in
    Column("id", Integer, primary_key=True),
    Column("mission_id", Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
    Column("crew_id", Integer, ForeignKey("crew.id", ondelete="CASCADE"), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False, default=now),
    Column("glucose", Float), Column("sleep_hours", Float), Column("mood", Float),
    Column("exercise_min", Float),
    Column("symptoms", Text, default=""),                     # comma-separated tags
    Column("note", Text, default=""),
)
Index("ix_checkins_crew_ts", checkins.c.crew_id, checkins.c.ts)

rollups = Table("rollups", meta,                              # hourly history kept for 7 days
    Column("id", Integer, primary_key=True),
    Column("sensor_id", Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False),
    Column("hour", DateTime(timezone=True), nullable=False),
    Column("avg", Float), Column("min", Float), Column("max", Float), Column("n", Integer),
)
Index("ix_rollups_sensor_hour", rollups.c.sensor_id, rollups.c.hour)

users = Table("users", meta,                                  # platform team (can manage every mission)
    Column("id", Integer, primary_key=True),
    Column("username", String(40), nullable=False, unique=True),
    Column("pw_hash", String(200), nullable=False),
    Column("role", String(10), nullable=False, default="admin"),
    Column("created_at", DateTime(timezone=True), default=now),
)

audit = Table("audit", meta,
    Column("id", Integer, primary_key=True),
    Column("mission_id", Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=True, index=True),
    Column("ts", DateTime(timezone=True), nullable=False, default=now),
    Column("username", String(40)),
    Column("ip", String(64)),
    Column("action", String(60), nullable=False),
    Column("detail", Text, default=""),
)

DEMO_CREW = [
    ("Cmdr. Elena Varga", "Commander", dict(heart_rate=62, bp_sys=116, bp_dia=74)),
    ("Dr. Kenji Mori", "Flight Surgeon", dict(heart_rate=68, bp_sys=122, bp_dia=79)),
    ("Aisha Rahman", "Flight Engineer", dict(heart_rate=71, resp_rate=15)),
    ("Lucas Ferreira", "Mission Specialist", dict(heart_rate=64, body_temp=36.7)),
]


def new_key():
    return "aura_" + secrets.token_hex(12)


def new_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def sensors_for_crew(conn, mission_id, crew_id, name):
    for m, spec in CREW_METRICS.items():
        conn.execute(insert(sensors).values(
            mission_id=mission_id, name=f"{name} · {spec['label']}", metric=m, subject="crew",
            crew_id=crew_id, api_key=new_key(), active=True))


def add_crew_member(conn, mission_id, name, role="", notes="", baseline=None):
    base = {**DEFAULT_BASELINE, **(baseline or {})}
    cid = conn.execute(insert(crew).values(
        mission_id=mission_id, name=name, role=role, notes=notes,
        **{f"base_{k}": v for k, v in base.items() if k in CREW_METRICS})).inserted_primary_key[0]
    sensors_for_crew(conn, mission_id, cid, name)
    return cid


def create_mission(conn, name, pw_hash, code=None, is_demo=False, demo_crew=True, environment="spacecraft"):
    """A new mission starts with default limits, ship sensors and (optionally) the demo crew."""
    t = now()
    mid = conn.execute(insert(missions).values(
        code=code or new_code(), name=name, pw_hash=pw_hash, is_demo=is_demo, simulator=True,
        environment=environment,
        scenario="none", mission_start=t - timedelta(days=142, hours=6) if is_demo else t,
        created_at=t, last_active=t)).inserted_primary_key[0]
    for m, spec in ALL_METRICS.items():
        conn.execute(insert(limits).values(mission_id=mid, metric=m, **spec))
    for m, spec in SHIP_METRICS.items():
        conn.execute(insert(sensors).values(
            mission_id=mid, name=f"Habitat · {spec['label']}", metric=m, subject="ship",
            crew_id=None, api_key=new_key(), active=True))
    if demo_crew:
        from .seed import seed_checkins, seed_history
        for cname, role, over in DEMO_CREW:
            cid = add_crew_member(conn, mid, cname, role, "Fictional demo crew member", over)
            seed_checkins(conn, mid, cid, days=7)
        if is_demo:
            seed_history(conn, mid, days=7)
    return mid


def init_db():
    from .security import hash_password
    # Older single-mission versions had no 'missions' table: their demo data is replaced.
    existing = set(inspect(engine).get_table_names())
    if existing and "missions" not in existing:
        old = MetaData()
        old.reflect(engine)
        old.drop_all(engine)
    meta.create_all(engine)
    _upgrade()
    with engine.begin() as conn:
        if conn.execute(select(users.c.id)).first() is None:
            conn.execute(insert(users).values(
                username="admin", role="admin",
                pw_hash=hash_password(os.getenv("ADMIN_PASSWORD", "aura-admin"))))
        demo = conn.execute(select(missions.c.id).where(missions.c.code == DEMO_CODE)).first()
        if demo is None:
            create_mission(conn, "AURA Demo Mission",
                           hash_password(os.getenv("ADMIN_PASSWORD", "aura-admin")),
                           code=DEMO_CODE, is_demo=True)
        elif conn.execute(select(checkins.c.id).where(checkins.c.mission_id == demo.id)).first() is None:
            from .seed import seed_checkins, seed_history   # demo created by an earlier version
            for (cid,) in conn.execute(select(crew.c.id).where(crew.c.mission_id == demo.id)).all():
                seed_checkins(conn, demo.id, cid, days=7)
            seed_history(conn, demo.id, days=7)


def delete_mission(conn, mid):
    """Explicit cascade (SQLite doesn't enforce foreign-key cascades by default)."""
    from sqlalchemy import delete
    sids = select(sensors.c.id).where(sensors.c.mission_id == mid)
    conn.execute(delete(readings).where(readings.c.sensor_id.in_(sids)))
    conn.execute(delete(rollups).where(rollups.c.sensor_id.in_(sids)))
    for t in (chats, audit, checkins, sensors, limits, crew):
        conn.execute(delete(t).where(t.c.mission_id == mid))
    conn.execute(delete(missions).where(missions.c.id == mid))


def _upgrade():
    """In-place upgrades for databases created by earlier versions."""
    from sqlalchemy import text
    cols = {c["name"] for c in inspect(engine).get_columns("missions")}
    if "environment" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE missions ADD COLUMN environment VARCHAR(20) DEFAULT 'spacecraft'"))
    with engine.begin() as conn:  # limits for metrics added later
        for (mid,) in conn.execute(select(missions.c.id)).all():
            have = {r.metric for r in conn.execute(select(limits.c.metric).where(limits.c.mission_id == mid))}
            for m, spec in ALL_METRICS.items():
                if m not in have:
                    conn.execute(insert(limits).values(mission_id=mid, metric=m, **spec))


def get_mission(conn, code):
    return conn.execute(select(missions).where(missions.c.code == (code or "").upper())).first()
