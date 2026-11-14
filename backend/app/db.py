"""Database layer. Uses Postgres (Supabase) when DATABASE_URL is set, else a local SQLite file."""
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
                        MetaData, String, Table, Text, create_engine, select, insert)

from .metrics import ALL_METRICS, CREW_METRICS, SHIP_METRICS, DEFAULT_BASELINE

url = os.getenv("DATABASE_URL", "sqlite:///./aura.db")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, pool_pre_ping=True, future=True,
                       connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
meta = MetaData()


def now():
    return datetime.now(timezone.utc)


crew = Table("crew", meta,
    Column("id", Integer, primary_key=True),
    Column("name", String(80), nullable=False),
    Column("role", String(80), default=""),
    Column("notes", Text, default=""),
    *[Column(f"base_{m}", Float) for m in CREW_METRICS],
    Column("created_at", DateTime(timezone=True), default=now),
)

sensors = Table("sensors", meta,
    Column("id", Integer, primary_key=True),
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
    Column("metric", String(40), primary_key=True),
    Column("label", String(60)),
    Column("unit", String(20)),
    Column("warn_low", Float), Column("warn_high", Float),
    Column("crit_low", Float), Column("crit_high", Float),
    Column("source", Text),
)

chats = Table("chats", meta,
    Column("id", Integer, primary_key=True),
    Column("crew_id", Integer, ForeignKey("crew.id", ondelete="CASCADE"), nullable=True),
    Column("client_id", String(64), nullable=True),           # private per-browser conversations
    Column("role", String(10), nullable=False),               # user | assistant
    Column("text", Text, nullable=False),
    Column("source", String(10), default=""),                 # gemini | offline
    Column("ts", DateTime(timezone=True), nullable=False, default=now),
)
Index("ix_chats_crew_ts", chats.c.crew_id, chats.c.ts)

users = Table("users", meta,
    Column("id", Integer, primary_key=True),
    Column("username", String(40), nullable=False, unique=True),
    Column("pw_hash", String(200), nullable=False),
    Column("role", String(10), nullable=False, default="admin"),   # admin | viewer
    Column("created_at", DateTime(timezone=True), default=now),
)

audit = Table("audit", meta,
    Column("id", Integer, primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False, default=now),
    Column("username", String(40)),
    Column("ip", String(64)),
    Column("action", String(60), nullable=False),
    Column("detail", Text, default=""),
)

settings = Table("settings", meta,
    Column("key", String(40), primary_key=True),
    Column("value", Text),
)


def new_key():
    return "aura_" + secrets.token_hex(12)


def sensors_for_crew(conn, crew_id, name):
    for m, spec in CREW_METRICS.items():
        conn.execute(insert(sensors).values(
            name=f"{name} · {spec['label']}", metric=m, subject="crew",
            crew_id=crew_id, api_key=new_key(), active=True))


def _migrate():
    """Small in-place upgrades for databases created by older versions."""
    from sqlalchemy import inspect, text
    cols = {c["name"] for c in inspect(engine).get_columns("chats")}
    if "client_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE chats ADD COLUMN client_id VARCHAR(64)"))


def init_db():
    meta.create_all(engine)
    _migrate()
    with engine.begin() as conn:
        if conn.execute(select(users.c.id)).first() is None:
            from .security import hash_password
            conn.execute(insert(users).values(
                username="admin", role="admin",
                pw_hash=hash_password(os.getenv("ADMIN_PASSWORD", "aura-admin"))))
        if conn.execute(select(limits.c.metric)).first() is None:
            for m, spec in ALL_METRICS.items():
                conn.execute(insert(limits).values(metric=m, **spec))
        if conn.execute(select(crew.c.id)).first() is None:
            seed = [
                ("Cmdr. Elena Varga", "Commander", dict(heart_rate=62, bp_sys=116, bp_dia=74)),
                ("Dr. Kenji Mori", "Flight Surgeon", dict(heart_rate=68, bp_sys=122, bp_dia=79)),
                ("Aisha Rahman", "Flight Engineer", dict(heart_rate=71, resp_rate=15)),
                ("Lucas Ferreira", "Mission Specialist", dict(heart_rate=64, body_temp=36.7)),
            ]
            for name, role, over in seed:
                base = {**DEFAULT_BASELINE, **over}
                cid = conn.execute(insert(crew).values(
                    name=name, role=role, notes="Fictional demo crew member",
                    **{f"base_{k}": v for k, v in base.items()})).inserted_primary_key[0]
                sensors_for_crew(conn, cid, name)
            for m, spec in SHIP_METRICS.items():
                conn.execute(insert(sensors).values(
                    name=f"Habitat · {spec['label']}", metric=m, subject="ship",
                    crew_id=None, api_key=new_key(), active=True))
        for k, v in {"simulator": "on", "scenario": "none", "scenario_crew": "",
                     "scenario_started": "", "public_access": "on", "mission_start": (now() - timedelta(days=142, hours=6)).isoformat()}.items():
            if conn.execute(select(settings.c.key).where(settings.c.key == k)).first() is None:
                conn.execute(insert(settings).values(key=k, value=v))


def get_settings(conn):
    return {r.key: r.value for r in conn.execute(select(settings))}


def set_setting(conn, key, value):
    from sqlalchemy import update
    res = conn.execute(update(settings).where(settings.c.key == key).values(value=str(value)))
    if res.rowcount == 0:
        conn.execute(insert(settings).values(key=key, value=str(value)))
