"""AURA AI - FastAPI application: public API, sensor ingest, admin (CMS) API, and the web app."""
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
from sqlalchemy import delete, insert, select, update

from . import analysis, chat, db, simulator
from .metrics import ALL_METRICS, CREW_METRICS, DEFAULT_BASELINE
from .security import check_password, client_ip, hash_password, limiter, make_token, read_token

CHAT_PER_MIN = 10          # per visitor
CHAT_PER_HOUR_ALL = 400    # whole site, protects the free AI quota
LOGIN_FAILS = 5            # failed logins before lockout
LOCK_SECONDS = 300
INGEST_PER_MIN = 240       # per sensor
CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{16,64}$")


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    task = asyncio.create_task(simulator.run_forever())
    asyncio.create_task(chat.warm_up())
    yield
    task.cancel()


app = FastAPI(title="AURA AI", version="1.0", lifespan=lifespan,
              description="Astronaut health monitoring: ingest, analysis/prediction, assistant, admin.")
# Cross-origin access is OFF unless explicitly allowed (the web app is served from the same origin).
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Client-Id"])

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


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
    # audit trail: every successful change made through the admin API
    if path.startswith("/api/admin/") and request.method != "GET" and path != "/api/admin/login" \
            and response.status_code < 400:
        who = read_token((request.headers.get("authorization") or "")[7:]) or {}
        verb = {"POST": "create/update", "PUT": "edit", "DELETE": "delete"}.get(request.method, request.method)
        log_action(who.get("username"), client_ip(request), f"{verb} {path[len('/api/admin/'):]}")
    return response


def log_action(username, ip, action, detail=""):
    try:
        with db.engine.begin() as conn:
            conn.execute(insert(db.audit).values(ts=db.now(), username=username, ip=ip,
                                                 action=action[:60], detail=detail[:500]))
    except Exception:
        pass


# ---------------- auth ----------------
def current_user(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        return read_token(authorization[7:])
    return None


def require_admin(user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "Login required")
    if user["role"] != "admin":
        raise HTTPException(403, "Admins only")
    return user


def require_view(user=Depends(current_user)):
    """Dashboard + assistant: open to all in public mode, login needed in private mode."""
    with db.engine.connect() as conn:
        public = db.get_settings(conn).get("public_access", "on") == "on"
    if not public and not user:
        raise HTTPException(401, "Login required")
    return user


# ---------------- public ----------------
@app.get("/api/_iphdrs")
def _iphdrs(request: Request):  # TEMP: inspect proxy headers, removed next commit
    return {k: v for k, v in request.headers.items() if k.lower() in
            ("x-forwarded-for", "true-client-ip", "cf-connecting-ip", "x-real-ip", "forwarded")} | \
           {"client": request.client.host if request.client else None}


@app.get("/api/health")
def health():
    return {"ok": True, "time": db.now().isoformat()}


@app.get("/api/overview", dependencies=[Depends(require_view)])
def overview():
    return analysis.compute()


@app.get("/api/meta", dependencies=[Depends(require_view)])
def meta():
    with db.engine.connect() as conn:
        lims = [dict(r._mapping) for r in conn.execute(select(db.limits))]
    return {"metrics": ALL_METRICS, "limits": lims, "scenarios": simulator.SCENARIOS,
            "crew_scenarios": sorted(simulator.CREW_SCENARIOS),
            "ai": "gemini" if os.getenv("GEMINI_API_KEY") else "offline"}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    crew_id: Optional[int] = None


def _client(x_client_id: Optional[str] = Header(None)):
    if not x_client_id or not CLIENT_ID.match(x_client_id):
        raise HTTPException(400, "Missing or invalid X-Client-Id")
    return x_client_id


def _chat_scope(q, table, crew_id, client):
    q = q.where(table.c.client_id == client)
    return q.where(table.c.crew_id == crew_id) if crew_id else q.where(table.c.crew_id.is_(None))


def _history(crew_id, client, limit=50):
    q = _chat_scope(select(db.chats), db.chats, crew_id, client)
    q = q.order_by(db.chats.c.ts.desc(), db.chats.c.id.desc()).limit(limit)
    with db.engine.connect() as conn:
        rows = list(conn.execute(q))
    return [dict(id=r.id, role=r.role, text=r.text, source=r.source, ts=r.ts.isoformat()) for r in reversed(rows)]


@app.get("/api/chat/history", dependencies=[Depends(require_view)])
def chat_history(crew_id: Optional[int] = None, client: str = Depends(_client)):
    """Only the conversation started from this browser is returned."""
    return _history(crew_id, client)


@app.delete("/api/chat/history", dependencies=[Depends(require_view)])
def clear_history(crew_id: Optional[int] = None, client: str = Depends(_client)):
    with db.engine.begin() as conn:
        conn.execute(_chat_scope(delete(db.chats), db.chats, crew_id, client))
    return {"ok": True}


@app.post("/api/chat", dependencies=[Depends(require_view)])
async def chat_endpoint(body: ChatIn, request: Request, client: str = Depends(_client)):
    ip = client_ip(request)
    if not limiter.hit(f"chat:{ip}", CHAT_PER_MIN, 60):
        raise HTTPException(429, "Too many questions. Please wait a minute.")
    if not limiter.hit("chat:all", CHAT_PER_HOUR_ALL, 3600):
        raise HTTPException(429, "The assistant is busy. Please try again later.")
    history = [{"role": h["role"], "text": h["text"]} for h in _history(body.crew_id, client, 8)]
    text, source = await chat.reply(body.message, history, body.crew_id)
    with db.engine.begin() as conn:
        conn.execute(insert(db.chats), [
            dict(crew_id=body.crew_id, client_id=client, role="user", text=body.message, source="", ts=db.now()),
            dict(crew_id=body.crew_id, client_id=client, role="assistant", text=text, source=source, ts=db.now()),
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


@app.post("/api/ingest")
def ingest(body: Reading, x_api_key: str = Header(...)):
    """Real sensors send one reading: header `X-API-Key: <sensor key>`."""
    with db.engine.begin() as conn:
        _ingest(conn, body, x_api_key)
    analysis.invalidate()
    return {"ok": True}


@app.post("/api/ingest/batch")
def ingest_batch(body: Batch, x_api_key: str = Header(...)):
    """Several readings from one gateway. X-API-Key may hold one key, or 'id:key,id:key'."""
    keys = dict(p.split(":", 1) for p in x_api_key.split(",")) if ":" in x_api_key else None
    with db.engine.begin() as conn:
        for r in body.readings:
            _ingest(conn, r, keys.get(str(r.sensor_id), "") if keys else x_api_key)
    analysis.invalidate()
    return {"ok": True, "count": len(body.readings)}


# ---------------- admin (CMS) ----------------
class Login(BaseModel):
    username: str = Field("admin", max_length=40)
    password: str = Field(max_length=200)


@app.post("/api/admin/login")
def login(body: Login, request: Request):
    ip = client_ip(request)
    keys = (f"fail:ip:{ip}", f"fail:user:{body.username.lower()}")
    if limiter.count(keys[0], LOCK_SECONDS) >= LOGIN_FAILS or limiter.count(keys[1], LOCK_SECONDS) >= LOGIN_FAILS * 4:
        raise HTTPException(429, "Too many failed attempts. Try again in 5 minutes.")
    with db.engine.connect() as conn:
        u = conn.execute(select(db.users).where(db.users.c.username == body.username.strip().lower())).first()
    if not u or not check_password(body.password, u.pw_hash):
        for k in keys:
            limiter.hit(k, 10_000, LOCK_SECONDS)
        log_action(body.username[:40], ip, "login failed")
        time.sleep(0.4)
        raise HTTPException(401, "Wrong username or password")
    for k in keys:
        limiter.reset(k)
    log_action(u.username, ip, "login")
    return {"token": make_token(u.username, u.role), "username": u.username, "role": u.role}


# ---- team accounts ----
class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=200)
    role: str = Field("admin", pattern=r"^(admin|viewer)$")


class PasswordIn(BaseModel):
    password: str = Field(min_length=10, max_length=200)


@app.get("/api/admin/users", dependencies=[Depends(require_admin)])
def list_users():
    with db.engine.connect() as conn:
        return [dict(id=r.id, username=r.username, role=r.role,
                     created_at=r.created_at.isoformat() if r.created_at else None)
                for r in conn.execute(select(db.users).order_by(db.users.c.id))]


@app.post("/api/admin/users", dependencies=[Depends(require_admin)])
def add_user(body: UserIn):
    name = body.username.lower()
    with db.engine.begin() as conn:
        if conn.execute(select(db.users.c.id).where(db.users.c.username == name)).first():
            raise HTTPException(409, "That username is taken")
        uid = conn.execute(insert(db.users).values(username=name, role=body.role,
                                                   pw_hash=hash_password(body.password))).inserted_primary_key[0]
    return {"id": uid}


@app.put("/api/admin/users/{uid}/password")
def set_password(uid: int, body: PasswordIn, me=Depends(require_admin)):
    with db.engine.begin() as conn:
        conn.execute(update(db.users).where(db.users.c.id == uid).values(pw_hash=hash_password(body.password)))
    return {"ok": True}


@app.delete("/api/admin/users/{uid}")
def delete_user(uid: int, me=Depends(require_admin)):
    with db.engine.begin() as conn:
        u = conn.execute(select(db.users).where(db.users.c.id == uid)).first()
        if not u:
            raise HTTPException(404, "Not found")
        if u.username == me["username"]:
            raise HTTPException(409, "You can't delete your own account")
        admins = conn.execute(select(db.users.c.id).where(db.users.c.role == "admin")).all()
        if u.role == "admin" and len(admins) <= 1:
            raise HTTPException(409, "At least one admin must remain")
        conn.execute(delete(db.users).where(db.users.c.id == uid))
    return {"ok": True}


@app.get("/api/admin/audit", dependencies=[Depends(require_admin)])
def audit_log(limit: int = 200):
    with db.engine.connect() as conn:
        rows = conn.execute(select(db.audit).order_by(db.audit.c.ts.desc()).limit(min(limit, 500)))
        return [dict(ts=r.ts.isoformat(), username=r.username, ip=r.ip, action=r.action, detail=r.detail)
                for r in rows]


class AccessIn(BaseModel):
    public: bool


@app.get("/api/admin/access", dependencies=[Depends(require_admin)])
def get_access():
    with db.engine.connect() as conn:
        return {"public": db.get_settings(conn).get("public_access", "on") == "on"}


@app.post("/api/admin/access", dependencies=[Depends(require_admin)])
def set_access(body: AccessIn):
    with db.engine.begin() as conn:
        db.set_setting(conn, "public_access", "on" if body.public else "off")
    return {"ok": True}


class CrewIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = ""
    notes: str = ""
    baseline: dict[str, float] = {}


def _crew_dict(r):
    return dict(id=r.id, name=r.name, role=r.role, notes=r.notes,
                baseline={m: getattr(r, f"base_{m}") for m in CREW_METRICS})


@app.get("/api/admin/crew", dependencies=[Depends(require_admin)])
def list_crew():
    with db.engine.connect() as conn:
        return [_crew_dict(r) for r in conn.execute(select(db.crew).order_by(db.crew.c.id))]


@app.post("/api/admin/crew", dependencies=[Depends(require_admin)])
def add_crew(body: CrewIn):
    base = {**DEFAULT_BASELINE, **{k: v for k, v in body.baseline.items() if k in CREW_METRICS}}
    with db.engine.begin() as conn:
        cid = conn.execute(insert(db.crew).values(
            name=body.name, role=body.role, notes=body.notes,
            **{f"base_{k}": v for k, v in base.items()})).inserted_primary_key[0]
        db.sensors_for_crew(conn, cid, body.name)
    analysis.invalidate()
    return {"id": cid}


@app.put("/api/admin/crew/{cid}", dependencies=[Depends(require_admin)])
def edit_crew(cid: int, body: CrewIn):
    vals = dict(name=body.name, role=body.role, notes=body.notes)
    vals.update({f"base_{k}": v for k, v in body.baseline.items() if k in CREW_METRICS})
    with db.engine.begin() as conn:
        conn.execute(update(db.crew).where(db.crew.c.id == cid).values(**vals))
    analysis.invalidate()
    return {"ok": True}


@app.delete("/api/admin/crew/{cid}", dependencies=[Depends(require_admin)])
def delete_crew(cid: int):
    with db.engine.begin() as conn:
        ids = [r.id for r in conn.execute(select(db.sensors.c.id).where(db.sensors.c.crew_id == cid))]
        if ids:
            conn.execute(delete(db.readings).where(db.readings.c.sensor_id.in_(ids)))
            conn.execute(delete(db.sensors).where(db.sensors.c.id.in_(ids)))
        conn.execute(delete(db.crew).where(db.crew.c.id == cid))
    analysis.invalidate()
    return {"ok": True}


class SensorIn(BaseModel):
    name: str
    metric: str
    crew_id: Optional[int] = None
    active: bool = True


@app.get("/api/admin/sensors", dependencies=[Depends(require_admin)])
def list_sensors():
    with db.engine.connect() as conn:
        out = []
        for r in conn.execute(select(db.sensors).order_by(db.sensors.c.subject, db.sensors.c.crew_id, db.sensors.c.id)):
            d = dict(r._mapping)
            d["last_device_at"] = d["last_device_at"].isoformat() if d["last_device_at"] else None
            out.append(d)
        return out


@app.post("/api/admin/sensors", dependencies=[Depends(require_admin)])
def add_sensor(body: SensorIn):
    if body.metric not in ALL_METRICS:
        raise HTTPException(422, "Unknown metric")
    subject = "crew" if body.metric in CREW_METRICS else "ship"
    if subject == "crew" and not body.crew_id:
        raise HTTPException(422, "Crew sensors need a crew member")
    with db.engine.begin() as conn:
        sid = conn.execute(insert(db.sensors).values(
            name=body.name, metric=body.metric, subject=subject,
            crew_id=body.crew_id if subject == "crew" else None,
            api_key=db.new_key(), active=body.active)).inserted_primary_key[0]
    analysis.invalidate()
    return {"id": sid}


@app.put("/api/admin/sensors/{sid}", dependencies=[Depends(require_admin)])
def edit_sensor(sid: int, body: SensorIn):
    with db.engine.begin() as conn:
        conn.execute(update(db.sensors).where(db.sensors.c.id == sid)
                     .values(name=body.name, active=body.active))
    analysis.invalidate()
    return {"ok": True}


@app.post("/api/admin/sensors/{sid}/rotate-key", dependencies=[Depends(require_admin)])
def rotate_key(sid: int):
    k = db.new_key()
    with db.engine.begin() as conn:
        conn.execute(update(db.sensors).where(db.sensors.c.id == sid).values(api_key=k))
    return {"api_key": k}


@app.delete("/api/admin/sensors/{sid}", dependencies=[Depends(require_admin)])
def delete_sensor(sid: int):
    with db.engine.begin() as conn:
        conn.execute(delete(db.readings).where(db.readings.c.sensor_id == sid))
        conn.execute(delete(db.sensors).where(db.sensors.c.id == sid))
    analysis.invalidate()
    return {"ok": True}


class LimitIn(BaseModel):
    warn_low: Optional[float] = None
    warn_high: Optional[float] = None
    crit_low: Optional[float] = None
    crit_high: Optional[float] = None
    source: Optional[str] = None


@app.get("/api/admin/limits", dependencies=[Depends(require_admin)])
def get_limits():
    with db.engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(db.limits))]


@app.put("/api/admin/limits/{metric}", dependencies=[Depends(require_admin)])
def set_limit(metric: str, body: LimitIn):
    vals = body.model_dump()
    if vals["source"] is None:
        vals.pop("source")
    with db.engine.begin() as conn:
        conn.execute(update(db.limits).where(db.limits.c.metric == metric).values(**vals))
    analysis.invalidate()
    return {"ok": True}


@app.get("/api/admin/readings", dependencies=[Depends(require_admin)])
def list_readings(sensor_id: Optional[int] = None, source: Optional[str] = None, limit: int = 100):
    q = select(db.readings, db.sensors.c.name).join(db.sensors).order_by(db.readings.c.ts.desc()).limit(min(limit, 500))
    if sensor_id:
        q = q.where(db.readings.c.sensor_id == sensor_id)
    if source:
        q = q.where(db.readings.c.source == source)
    with db.engine.connect() as conn:
        return [dict(id=r.id, sensor_id=r.sensor_id, sensor=r.name, value=r.value,
                     ts=r.ts.isoformat(), source=r.source) for r in conn.execute(q)]


class ManualReading(BaseModel):
    sensor_id: int
    value: float
    timestamp: Optional[datetime] = None


@app.post("/api/admin/readings", dependencies=[Depends(require_admin)])
def add_reading(body: ManualReading):
    ts = body.timestamp or db.now()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    with db.engine.begin() as conn:
        if not conn.execute(select(db.sensors.c.id).where(db.sensors.c.id == body.sensor_id)).first():
            raise HTTPException(404, "Sensor not found")
        conn.execute(insert(db.readings).values(sensor_id=body.sensor_id, value=body.value, ts=ts, source="manual"))
    analysis.invalidate()
    return {"ok": True}


@app.delete("/api/admin/readings/{rid}", dependencies=[Depends(require_admin)])
def delete_reading(rid: int):
    with db.engine.begin() as conn:
        conn.execute(delete(db.readings).where(db.readings.c.id == rid))
    analysis.invalidate()
    return {"ok": True}


@app.post("/api/admin/readings/csv", dependencies=[Depends(require_admin)])
async def import_csv(file: UploadFile = File(...)):
    """CSV columns: sensor_id,value[,timestamp]  (timestamp ISO-8601, optional)."""
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise HTTPException(413, "CSV too large (max 2 MB)")
    raw = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    rows, errors = [], []
    with db.engine.connect() as conn:
        valid = {r.id for r in conn.execute(select(db.sensors.c.id))}
    for i, row in enumerate(reader, start=2):
        try:
            sid = int(row["sensor_id"])
            if sid not in valid:
                raise ValueError("unknown sensor_id")
            ts = row.get("timestamp") or ""
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts.strip() else db.now()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            rows.append(dict(sensor_id=sid, value=float(row["value"]), ts=ts, source="import"))
        except Exception as e:
            errors.append(f"line {i}: {e}")
    if rows:
        with db.engine.begin() as conn:
            conn.execute(insert(db.readings), rows)
    analysis.invalidate()
    return {"imported": len(rows), "errors": errors[:20]}


class SimIn(BaseModel):
    enabled: bool
    scenario: str = "none"
    scenario_crew: Optional[int] = None


@app.post("/api/admin/simulator", dependencies=[Depends(require_admin)])
def set_sim(body: SimIn):
    if body.scenario not in simulator.SCENARIOS:
        raise HTTPException(422, "Unknown scenario")
    with db.engine.begin() as conn:
        db.set_setting(conn, "simulator", "on" if body.enabled else "off")
        db.set_setting(conn, "scenario", body.scenario)
        db.set_setting(conn, "scenario_crew", body.scenario_crew or "")
        db.set_setting(conn, "scenario_started", db.now().isoformat())
    analysis.invalidate()
    return {"ok": True}


# ---------------- web app ----------------
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
