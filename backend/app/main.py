"""AURA AI - FastAPI application.

Missions work like game servers: anyone can host one (with a password) and share its join code.
Everything inside a mission - crew, sensors, limits, simulator, chats, activity - is isolated.

  /api/missions                    host a mission, look one up, log in as its host
  /api/m/{code}/...                one mission: overview, assistant, and its admin (CMS) API
  /api/ingest                      real sensors (the sensor key identifies the mission)
  /api/team/...                    platform team: all missions, team accounts, platform log
"""
import asyncio
import csv
import hmac
import io
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update

from . import analysis, chat, db, simulator
from .metrics import ALL_METRICS, CREW_METRICS
from .security import check_password, client_ip, hash_password, limiter, make_token, read_token

CHAT_PER_MIN = 10          # per visitor
CHAT_PER_HOUR_ALL = 400    # whole site, protects the free AI quota
LOGIN_FAILS = 5            # failed logins (per IP) before a 5-minute lockout
LOCK_SECONDS = 300
INGEST_PER_MIN = 240       # per sensor
HOSTS_PER_HOUR = 3         # new missions per IP
MAX_MISSIONS = 300
CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{16,64}$")


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    task = asyncio.create_task(simulator.run_forever())
    asyncio.create_task(chat.warm_up())
    yield
    task.cancel()


app = FastAPI(title="AURA AI", version="2.0", lifespan=lifespan,
              description="Astronaut health monitoring: hosted missions, sensor ingest, "
                          "analysis/prediction, assistant, admin.")

_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Client-Id"])

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
_ADMIN_PATH = re.compile(r"^/api/m/([A-Za-z0-9]+)/admin/(.+)$")
VERBS = {"POST": "create/update", "PUT": "edit", "DELETE": "delete"}


@app.middleware("http")
async def security_and_audit(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Strict-Transport-Security"] = "max-age=31536000"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    path = request.url.path
    if not path.startswith(("/docs", "/redoc", "/openapi.json")):
        h["Content-Security-Policy"] = CSP
    if path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    # audit trail: every successful change
    if request.method != "GET" and response.status_code < 400:
        who = read_token((request.headers.get("authorization") or "")[7:]) or {}
        m = _ADMIN_PATH.match(path)
        if m:
            await asyncio.to_thread(_log_by_code, m.group(1), who.get("username"), client_ip(request),
                                    f"{VERBS.get(request.method, request.method)} {m.group(2)}")
        elif path.startswith("/api/team/") and path != "/api/team/login":
            await asyncio.to_thread(log_action, None, who.get("username"), client_ip(request),
                                    f"{VERBS.get(request.method, request.method)} {path[len('/api/team/'):]}")
    return response


def log_action(mission_id, username, ip, action, detail=""):
    try:
        with db.engine.begin() as conn:
            conn.execute(insert(db.audit).values(mission_id=mission_id, ts=db.now(), username=username,
                                                 ip=ip, action=action[:60], detail=detail[:500]))
    except Exception:
        pass


def _log_by_code(code, username, ip, action):
    with db.engine.connect() as conn:
        m = db.get_mission(conn, code)
    if m:
        log_action(m.id, username, ip, action)


# ---------------- auth ----------------
def current_user(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        return read_token(authorization[7:])
    return None


def mission(code: str):
    with db.engine.connect() as conn:
        m = db.get_mission(conn, code)
    if not m:
        raise HTTPException(404, "No mission with that code")
    return m


def require_team(user=Depends(current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(401, "Team login required")
    return user


def require_host(m=Depends(mission), user=Depends(current_user)):
    """Mission admin: the mission's host (password holder) or a platform team member."""
    if not user:
        raise HTTPException(401, "Mission password required")
    if user["role"] == "admin" or (user["role"] == "host" and user.get("mission_id") == m.id):
        return m
    raise HTTPException(403, "You are not an admin of this mission")


def _touch(mid):
    """Mark a mission as in use (drives the simulator and idle clean-up); at most once a minute."""
    if limiter.hit(f"touch:{mid}", 1, 60):
        with db.engine.begin() as conn:
            conn.execute(update(db.missions).where(db.missions.c.id == mid).values(last_active=db.now()))


def _lockout(keys):
    if any(limiter.count(k, LOCK_SECONDS) >= LOGIN_FAILS for k in keys):
        raise HTTPException(429, "Too many failed attempts. Try again in 5 minutes.")


def _fail(keys):
    for k in keys:
        limiter.hit(k, 10_000, LOCK_SECONDS)
    time.sleep(0.4)


# ---------------- missions (hosting / joining) ----------------
@app.get("/api/health")
def health():
    return {"ok": True, "time": db.now().isoformat()}


class HostIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=8, max_length=200)
    demo_crew: bool = True


@app.post("/api/missions")
def host_mission(body: HostIn, request: Request):
    ip = client_ip(request)
    if not limiter.hit(f"host:{ip}", HOSTS_PER_HOUR, 3600):
        raise HTTPException(429, "You've hosted several missions recently. Try again later.")
    with db.engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(db.missions)).scalar() >= MAX_MISSIONS:
            raise HTTPException(503, "Mission capacity reached. Try again later.")
        for _ in range(10):
            code = db.new_code()
            if not db.get_mission(conn, code):
                break
        mid = db.create_mission(conn, body.name.strip(), hash_password(body.password), code=code,
                                demo_crew=body.demo_crew)
    log_action(mid, "host", ip, "mission created", body.name.strip())
    return {"code": code, "name": body.name.strip(), "token": make_token("host", "host", mid)}


@app.get("/api/missions/{code}")
def find_mission(m=Depends(mission)):
    return {"code": m.code, "name": m.name, "is_demo": bool(m.is_demo)}


class PasswordOnly(BaseModel):
    password: str = Field(max_length=200)


@app.post("/api/missions/{code}/login")
def host_login(body: PasswordOnly, request: Request, m=Depends(mission)):
    ip = client_ip(request)
    keys = (f"fail:ip:{ip}", f"fail:mission:{m.id}:{ip}")
    _lockout(keys)
    if not check_password(body.password, m.pw_hash):
        _fail(keys)
        log_action(m.id, "host", ip, "login failed")
        raise HTTPException(401, "Wrong mission password")
    log_action(m.id, "host", ip, "login")
    return {"token": make_token("host", "host", m.id), "username": "host", "role": "host", "mission": m.code}


# ---------------- one mission: public ----------------
@app.get("/api/m/{code}/overview")
def overview(m=Depends(mission)):
    _touch(m.id)
    return analysis.compute(m.id)


@app.get("/api/m/{code}/meta")
def meta(m=Depends(mission)):
    return {"metrics": ALL_METRICS, "scenarios": simulator.SCENARIOS,
            "crew_scenarios": sorted(simulator.CREW_SCENARIOS),
            "ai": "gemini" if os.getenv("GEMINI_API_KEY") else "offline",
            "mission": {"code": m.code, "name": m.name, "is_demo": bool(m.is_demo)}}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    crew_id: Optional[int] = None


def _client(x_client_id: Optional[str] = Header(None)):
    if not x_client_id or not CLIENT_ID.match(x_client_id):
        raise HTTPException(400, "Missing or invalid X-Client-Id")
    return x_client_id


def _chat_scope(q, mid, crew_id, client):
    q = q.where(db.chats.c.mission_id == mid, db.chats.c.client_id == client)
    return q.where(db.chats.c.crew_id == crew_id) if crew_id else q.where(db.chats.c.crew_id.is_(None))


def _history(mid, crew_id, client, limit=50):
    q = _chat_scope(select(db.chats), mid, crew_id, client)
    q = q.order_by(db.chats.c.ts.desc(), db.chats.c.id.desc()).limit(limit)
    with db.engine.connect() as conn:
        rows = list(conn.execute(q))
    return [dict(id=r.id, role=r.role, text=r.text, source=r.source, ts=r.ts.isoformat()) for r in reversed(rows)]


@app.get("/api/m/{code}/chat/history")
def chat_history(crew_id: Optional[int] = None, client: str = Depends(_client), m=Depends(mission)):
    """Only the conversation started from this browser, in this mission."""
    return _history(m.id, crew_id, client)


@app.delete("/api/m/{code}/chat/history")
def clear_history(crew_id: Optional[int] = None, client: str = Depends(_client), m=Depends(mission)):
    with db.engine.begin() as conn:
        conn.execute(_chat_scope(delete(db.chats), m.id, crew_id, client))
    return {"ok": True}


@app.post("/api/m/{code}/chat")
async def chat_endpoint(body: ChatIn, request: Request, client: str = Depends(_client), m=Depends(mission)):
    ip = client_ip(request)
    if not limiter.hit(f"chat:{ip}", CHAT_PER_MIN, 60):
        raise HTTPException(429, "Too many questions. Please wait a minute.")
    if not limiter.hit("chat:all", CHAT_PER_HOUR_ALL, 3600):
        raise HTTPException(429, "The assistant is busy. Please try again later.")
    if body.crew_id:
        with db.engine.connect() as conn:
            if not conn.execute(select(db.crew.c.id).where(db.crew.c.id == body.crew_id,
                                                           db.crew.c.mission_id == m.id)).first():
                raise HTTPException(404, "Crew member not found in this mission")
    history = [{"role": h["role"], "text": h["text"]} for h in _history(m.id, body.crew_id, client, 8)]
    text, source = await chat.reply(m.id, body.message, history, body.crew_id)
    with db.engine.begin() as conn:
        conn.execute(insert(db.chats), [
            dict(mission_id=m.id, crew_id=body.crew_id, client_id=client, role="user", text=body.message,
                 source="", ts=db.now()),
            dict(mission_id=m.id, crew_id=body.crew_id, client_id=client, role="assistant", text=text,
                 source=source, ts=db.now()),
        ])
    return {"reply": text, "source": source}


# ---------------- sensor ingest ----------------
class Reading(BaseModel):
    sensor_id: int
    value: float
    type: Optional[str] = None
    unit: Optional[str] = None
    timestamp: Optional[datetime] = None


class Batch(BaseModel):
    readings: list[Reading] = Field(max_length=500)


def _ingest(conn, r: Reading, key: str):
    if not limiter.hit(f"ingest:{r.sensor_id}", INGEST_PER_MIN, 60):
        raise HTTPException(429, f"Sensor {r.sensor_id} is sending too fast")
    s = conn.execute(select(db.sensors).where(db.sensors.c.id == r.sensor_id)).first()
    if not s or not hmac.compare_digest(s.api_key, key or ""):
        raise HTTPException(403, f"Invalid sensor id or API key for sensor {r.sensor_id}")
    if not s.active:
        raise HTTPException(409, f"Sensor {r.sensor_id} is disabled")
    if r.type and r.type != s.metric:
        raise HTTPException(422, f"Sensor {r.sensor_id} measures '{s.metric}', not '{r.type}'")
    ts = r.timestamp or db.now()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    conn.execute(insert(db.readings).values(sensor_id=s.id, value=r.value, ts=ts, source="device"))
    conn.execute(update(db.sensors).where(db.sensors.c.id == s.id).values(last_device_at=db.now()))
    return s.mission_id


@app.post("/api/ingest")
def ingest(body: Reading, x_api_key: str = Header(...)):
    """A real sensor sends one reading with header `X-API-Key: <sensor key>`."""
    with db.engine.begin() as conn:
        mid = _ingest(conn, body, x_api_key)
    analysis.invalidate(mid)
    return {"ok": True}


@app.post("/api/ingest/batch")
def ingest_batch(body: Batch, x_api_key: str = Header(...)):
    """Several readings from one gateway. X-API-Key may hold one key, or 'id:key,id:key'."""
    keys = dict(p.split(":", 1) for p in x_api_key.split(",")) if ":" in x_api_key else None
    mids = set()
    with db.engine.begin() as conn:
        for r in body.readings:
            mids.add(_ingest(conn, r, keys.get(str(r.sensor_id), "") if keys else x_api_key))
    for mid in mids:
        analysis.invalidate(mid)
    return {"ok": True, "count": len(body.readings)}


# ---------------- one mission: admin (CMS) ----------------
def _owned(conn, table, row_id, mid):
    r = conn.execute(select(table).where(table.c.id == row_id, table.c.mission_id == mid)).first()
    if not r:
        raise HTTPException(404, "Not found in this mission")
    return r


class CrewIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field("", max_length=80)
    notes: str = Field("", max_length=500)
    baseline: dict[str, float] = {}


def _crew_dict(r):
    return dict(id=r.id, name=r.name, role=r.role, notes=r.notes,
                baseline={k: getattr(r, f"base_{k}") for k in CREW_METRICS})


@app.get("/api/m/{code}/admin/crew")
def list_crew(m=Depends(require_host)):
    with db.engine.connect() as conn:
        return [_crew_dict(r) for r in conn.execute(
            select(db.crew).where(db.crew.c.mission_id == m.id).order_by(db.crew.c.id))]


@app.post("/api/m/{code}/admin/crew")
def add_crew(body: CrewIn, m=Depends(require_host)):
    with db.engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(db.crew).where(db.crew.c.mission_id == m.id)).scalar() >= 12:
            raise HTTPException(409, "A mission can have at most 12 crew members")
        cid = db.add_crew_member(conn, m.id, body.name, body.role, body.notes,
                                 {k: v for k, v in body.baseline.items() if k in CREW_METRICS})
    analysis.invalidate(m.id)
    return {"id": cid}


@app.put("/api/m/{code}/admin/crew/{cid}")
def edit_crew(cid: int, body: CrewIn, m=Depends(require_host)):
    vals = dict(name=body.name, role=body.role, notes=body.notes)
    vals.update({f"base_{k}": v for k, v in body.baseline.items() if k in CREW_METRICS})
    with db.engine.begin() as conn:
        _owned(conn, db.crew, cid, m.id)
        conn.execute(update(db.crew).where(db.crew.c.id == cid).values(**vals))
    analysis.invalidate(m.id)
    return {"ok": True}


@app.delete("/api/m/{code}/admin/crew/{cid}")
def delete_crew(cid: int, m=Depends(require_host)):
    with db.engine.begin() as conn:
        _owned(conn, db.crew, cid, m.id)
        sids = select(db.sensors.c.id).where(db.sensors.c.crew_id == cid)
        conn.execute(delete(db.readings).where(db.readings.c.sensor_id.in_(sids)))
        conn.execute(delete(db.sensors).where(db.sensors.c.crew_id == cid))
        conn.execute(delete(db.chats).where(db.chats.c.crew_id == cid))
        conn.execute(delete(db.crew).where(db.crew.c.id == cid))
    analysis.invalidate(m.id)
    return {"ok": True}


class SensorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    metric: str
    crew_id: Optional[int] = None
    active: bool = True


@app.get("/api/m/{code}/admin/sensors")
def list_sensors(m=Depends(require_host)):
    with db.engine.connect() as conn:
        out = []
        for r in conn.execute(select(db.sensors).where(db.sensors.c.mission_id == m.id)
                              .order_by(db.sensors.c.subject, db.sensors.c.crew_id, db.sensors.c.id)):
            d = dict(r._mapping)
            d["last_device_at"] = d["last_device_at"].isoformat() if d["last_device_at"] else None
            out.append(d)
        return out


@app.post("/api/m/{code}/admin/sensors")
def add_sensor(body: SensorIn, m=Depends(require_host)):
    if body.metric not in ALL_METRICS:
        raise HTTPException(422, "Unknown metric")
    subject = "crew" if body.metric in CREW_METRICS else "ship"
    with db.engine.begin() as conn:
        if subject == "crew":
            if not body.crew_id:
                raise HTTPException(422, "Crew sensors need a crew member")
            _owned(conn, db.crew, body.crew_id, m.id)
        if conn.execute(select(func.count()).select_from(db.sensors).where(db.sensors.c.mission_id == m.id)).scalar() >= 120:
            raise HTTPException(409, "Sensor limit reached for this mission")
        sid = conn.execute(insert(db.sensors).values(
            mission_id=m.id, name=body.name, metric=body.metric, subject=subject,
            crew_id=body.crew_id if subject == "crew" else None,
            api_key=db.new_key(), active=body.active)).inserted_primary_key[0]
    analysis.invalidate(m.id)
    return {"id": sid}


@app.put("/api/m/{code}/admin/sensors/{sid}")
def edit_sensor(sid: int, body: SensorIn, m=Depends(require_host)):
    with db.engine.begin() as conn:
        _owned(conn, db.sensors, sid, m.id)
        conn.execute(update(db.sensors).where(db.sensors.c.id == sid).values(name=body.name, active=body.active))
    analysis.invalidate(m.id)
    return {"ok": True}


@app.post("/api/m/{code}/admin/sensors/{sid}/rotate-key")
def rotate_key(sid: int, m=Depends(require_host)):
    k = db.new_key()
    with db.engine.begin() as conn:
        _owned(conn, db.sensors, sid, m.id)
        conn.execute(update(db.sensors).where(db.sensors.c.id == sid).values(api_key=k))
    return {"api_key": k}


@app.delete("/api/m/{code}/admin/sensors/{sid}")
def delete_sensor(sid: int, m=Depends(require_host)):
    with db.engine.begin() as conn:
        _owned(conn, db.sensors, sid, m.id)
        conn.execute(delete(db.readings).where(db.readings.c.sensor_id == sid))
        conn.execute(delete(db.sensors).where(db.sensors.c.id == sid))
    analysis.invalidate(m.id)
    return {"ok": True}


class LimitIn(BaseModel):
    warn_low: Optional[float] = None
    warn_high: Optional[float] = None
    crit_low: Optional[float] = None
    crit_high: Optional[float] = None


@app.get("/api/m/{code}/admin/limits")
def get_limits(m=Depends(require_host)):
    with db.engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(
            select(db.limits).where(db.limits.c.mission_id == m.id).order_by(db.limits.c.id))]


@app.put("/api/m/{code}/admin/limits/{metric}")
def set_limit(metric: str, body: LimitIn, m=Depends(require_host)):
    with db.engine.begin() as conn:
        conn.execute(update(db.limits).where(db.limits.c.mission_id == m.id, db.limits.c.metric == metric)
                     .values(**body.model_dump()))
    analysis.invalidate(m.id)
    return {"ok": True}


@app.get("/api/m/{code}/admin/readings")
def list_readings(sensor_id: Optional[int] = None, limit: int = 100, m=Depends(require_host)):
    q = (select(db.readings, db.sensors.c.name).join(db.sensors)
         .where(db.sensors.c.mission_id == m.id).order_by(db.readings.c.ts.desc()).limit(min(limit, 500)))
    if sensor_id:
        q = q.where(db.readings.c.sensor_id == sensor_id)
    with db.engine.connect() as conn:
        return [dict(id=r.id, sensor_id=r.sensor_id, sensor=r.name, value=r.value,
                     ts=r.ts.isoformat(), source=r.source) for r in conn.execute(q)]


class ManualReading(BaseModel):
    sensor_id: int
    value: float
    timestamp: Optional[datetime] = None


@app.post("/api/m/{code}/admin/readings")
def add_reading(body: ManualReading, m=Depends(require_host)):
    ts = body.timestamp or db.now()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    with db.engine.begin() as conn:
        _owned(conn, db.sensors, body.sensor_id, m.id)
        conn.execute(insert(db.readings).values(sensor_id=body.sensor_id, value=body.value, ts=ts, source="manual"))
    analysis.invalidate(m.id)
    return {"ok": True}


@app.delete("/api/m/{code}/admin/readings/{rid}")
def delete_reading(rid: int, m=Depends(require_host)):
    with db.engine.begin() as conn:
        owned = select(db.sensors.c.id).where(db.sensors.c.mission_id == m.id)
        res = conn.execute(delete(db.readings).where(db.readings.c.id == rid, db.readings.c.sensor_id.in_(owned)))
        if res.rowcount == 0:
            raise HTTPException(404, "Not found in this mission")
    analysis.invalidate(m.id)
    return {"ok": True}


@app.post("/api/m/{code}/admin/readings/csv")
async def import_csv(file: UploadFile = File(...), m=Depends(require_host)):
    """CSV columns: sensor_id,value[,timestamp]  (timestamp ISO-8601, optional)."""
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise HTTPException(413, "CSV too large (max 2 MB)")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    rows, errors = [], []
    with db.engine.connect() as conn:
        valid = {r.id for r in conn.execute(select(db.sensors.c.id).where(db.sensors.c.mission_id == m.id))}
    for i, row in enumerate(reader, start=2):
        try:
            sid = int(row["sensor_id"])
            if sid not in valid:
                raise ValueError("sensor_id is not in this mission")
            ts = (row.get("timestamp") or "").strip()
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else db.now()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            rows.append(dict(sensor_id=sid, value=float(row["value"]), ts=ts, source="import"))
        except Exception as e:
            errors.append(f"line {i}: {e}")
    if rows:
        with db.engine.begin() as conn:
            conn.execute(insert(db.readings), rows)
    analysis.invalidate(m.id)
    return {"imported": len(rows), "errors": errors[:20]}


class SimIn(BaseModel):
    enabled: bool
    scenario: str = "none"
    scenario_crew: Optional[int] = None


@app.post("/api/m/{code}/admin/simulator")
def set_sim(body: SimIn, m=Depends(require_host)):
    if body.scenario not in simulator.SCENARIOS:
        raise HTTPException(422, "Unknown scenario")
    with db.engine.begin() as conn:
        if body.scenario_crew:
            _owned(conn, db.crew, body.scenario_crew, m.id)
        conn.execute(update(db.missions).where(db.missions.c.id == m.id).values(
            simulator=body.enabled, scenario=body.scenario, scenario_crew=body.scenario_crew,
            scenario_started=db.now()))
    analysis.invalidate(m.id)
    return {"ok": True}


@app.get("/api/m/{code}/admin/audit")
def mission_audit(limit: int = 200, m=Depends(require_host)):
    with db.engine.connect() as conn:
        rows = conn.execute(select(db.audit).where(db.audit.c.mission_id == m.id)
                            .order_by(db.audit.c.ts.desc()).limit(min(limit, 500)))
        return [dict(ts=r.ts.isoformat(), username=r.username, ip=r.ip, action=r.action, detail=r.detail)
                for r in rows]


class MissionEdit(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=60)
    password: Optional[str] = Field(None, min_length=8, max_length=200)


@app.put("/api/m/{code}/admin/mission")
def edit_mission(body: MissionEdit, m=Depends(require_host)):
    vals = {}
    if body.name:
        vals["name"] = body.name.strip()
    if body.password:
        vals["pw_hash"] = hash_password(body.password)
    if vals:
        with db.engine.begin() as conn:
            conn.execute(update(db.missions).where(db.missions.c.id == m.id).values(**vals))
        analysis.invalidate(m.id)
    return {"ok": True}


@app.delete("/api/m/{code}/admin/mission")
def end_mission(m=Depends(require_host)):
    if m.is_demo:
        raise HTTPException(409, "The demo mission can't be deleted")
    with db.engine.begin() as conn:
        db.delete_mission(conn, m.id)
    analysis.invalidate(m.id)
    return {"ok": True}


# ---------------- platform team ----------------
class TeamLogin(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)


@app.post("/api/team/login")
def team_login(body: TeamLogin, request: Request):
    ip = client_ip(request)
    keys = (f"fail:ip:{ip}",)
    _lockout(keys)
    with db.engine.connect() as conn:
        u = conn.execute(select(db.users).where(db.users.c.username == body.username.strip().lower())).first()
    if not u or not check_password(body.password, u.pw_hash):
        _fail(keys)
        log_action(None, body.username[:40], ip, "team login failed")
        raise HTTPException(401, "Wrong username or password")
    log_action(None, u.username, ip, "team login")
    return {"token": make_token(u.username, "admin"), "username": u.username, "role": "admin"}


@app.get("/api/team/missions", dependencies=[Depends(require_team)])
def all_missions():
    with db.engine.connect() as conn:
        counts = dict(conn.execute(select(db.crew.c.mission_id, func.count()).group_by(db.crew.c.mission_id)).all())
        return [dict(code=r.code, name=r.name, is_demo=bool(r.is_demo), crew=counts.get(r.id, 0),
                     scenario=r.scenario, created_at=r.created_at.isoformat() if r.created_at else None,
                     last_active=r.last_active.isoformat() if r.last_active else None)
                for r in conn.execute(select(db.missions).order_by(db.missions.c.last_active.desc()))]


@app.delete("/api/team/missions/{code}", dependencies=[Depends(require_team)])
def team_delete_mission(m=Depends(mission)):
    if m.is_demo:
        raise HTTPException(409, "The demo mission can't be deleted")
    with db.engine.begin() as conn:
        db.delete_mission(conn, m.id)
    analysis.invalidate(m.id)
    return {"ok": True}


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=200)


class NewPassword(BaseModel):
    password: str = Field(min_length=10, max_length=200)


@app.get("/api/team/users", dependencies=[Depends(require_team)])
def list_users():
    with db.engine.connect() as conn:
        return [dict(id=r.id, username=r.username, created_at=r.created_at.isoformat() if r.created_at else None)
                for r in conn.execute(select(db.users).order_by(db.users.c.id))]


@app.post("/api/team/users", dependencies=[Depends(require_team)])
def add_user(body: UserIn):
    name = body.username.lower()
    with db.engine.begin() as conn:
        if conn.execute(select(db.users.c.id).where(db.users.c.username == name)).first():
            raise HTTPException(409, "That username is taken")
        uid = conn.execute(insert(db.users).values(username=name, role="admin",
                                                   pw_hash=hash_password(body.password))).inserted_primary_key[0]
    return {"id": uid}


@app.put("/api/team/users/{uid}/password", dependencies=[Depends(require_team)])
def set_password(uid: int, body: NewPassword):
    with db.engine.begin() as conn:
        conn.execute(update(db.users).where(db.users.c.id == uid).values(pw_hash=hash_password(body.password)))
    return {"ok": True}


@app.delete("/api/team/users/{uid}")
def delete_user(uid: int, me=Depends(require_team)):
    with db.engine.begin() as conn:
        u = conn.execute(select(db.users).where(db.users.c.id == uid)).first()
        if not u:
            raise HTTPException(404, "Not found")
        if u.username == me["username"]:
            raise HTTPException(409, "You can't delete your own account")
        conn.execute(delete(db.users).where(db.users.c.id == uid))
    return {"ok": True}


@app.get("/api/team/audit", dependencies=[Depends(require_team)])
def team_audit(limit: int = 200):
    with db.engine.connect() as conn:
        codes = dict(conn.execute(select(db.missions.c.id, db.missions.c.code)).all())
        rows = conn.execute(select(db.audit).order_by(db.audit.c.ts.desc()).limit(min(limit, 500)))
        return [dict(ts=r.ts.isoformat(), mission=codes.get(r.mission_id), username=r.username, ip=r.ip,
                     action=r.action, detail=r.detail) for r in rows]


# ---------------- web app ----------------
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
