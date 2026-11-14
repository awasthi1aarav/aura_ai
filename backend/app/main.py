"""AURA AI - FastAPI application: public API, sensor ingest, admin (CMS) API, and the web app."""
import asyncio
import csv
import hashlib
import hmac
import io
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from . import analysis, chat, db, simulator
from .metrics import ALL_METRICS, CREW_METRICS, DEFAULT_BASELINE

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "aura-admin")
SECRET = os.getenv("SECRET_KEY", "dev-secret-change-me")
TOKEN_HOURS = 12


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    task = asyncio.create_task(simulator.run_forever())
    yield
    task.cancel()


app = FastAPI(title="AURA AI", version="1.0", lifespan=lifespan,
              description="Astronaut health monitoring: ingest, analysis/prediction, assistant, admin.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------- auth ----------------
def make_token():
    exp = str(int(time.time()) + TOKEN_HOURS * 3600)
    sig = hmac.new(SECRET.encode(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def require_admin(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Login required")
    try:
        exp, sig = authorization[7:].split(".", 1)
    except ValueError:
        raise HTTPException(401, "Bad token")
    good = hmac.new(SECRET.encode(), exp.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig) or int(exp) < time.time():
        raise HTTPException(401, "Session expired")
    return True


# ---------------- public ----------------
@app.get("/api/health")
def health():
    return {"ok": True, "time": db.now().isoformat()}


@app.get("/api/overview")
def overview():
    return analysis.compute()


@app.get("/api/meta")
def meta():
    with db.engine.connect() as conn:
        lims = [dict(r._mapping) for r in conn.execute(select(db.limits))]
    return {"metrics": ALL_METRICS, "limits": lims, "scenarios": simulator.SCENARIOS,
            "crew_scenarios": sorted(simulator.CREW_SCENARIOS),
            "ai": "gemini" if os.getenv("GEMINI_API_KEY") else "offline"}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    crew_id: Optional[int] = None
    history: list[dict] = []


@app.post("/api/chat")
async def chat_endpoint(body: ChatIn):
    text, source = await chat.reply(body.message, body.history, body.crew_id)
    return {"reply": text, "source": source}


# ---------------- sensor ingest ----------------
class Reading(BaseModel):
    sensor_id: int
    value: float
    type: Optional[str] = None
    unit: Optional[str] = None
    timestamp: Optional[datetime] = None


class Batch(BaseModel):
    readings: list[Reading]


def _ingest(conn, r: Reading, key: str):
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
    password: str


@app.post("/api/admin/login")
def login(body: Login):
    if not hmac.compare_digest(body.password, ADMIN_PASSWORD):
        time.sleep(0.5)
        raise HTTPException(401, "Wrong password")
    return {"token": make_token()}


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
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
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
