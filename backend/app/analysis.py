"""Analysis + prediction engine.

Three checks per sensor, all explainable:
  1. Limits      - value vs. safe ranges (NASA-STD-3001 for the cabin, clinical bands for vitals)
  2. Baseline    - value vs. this astronaut's own pre-flight normal
  3. Trend       - linear fit over the last few minutes, projected forward to estimate
                   WHEN a limit will be crossed (the prediction)
"""
import time
from datetime import timedelta, timezone

from sqlalchemy import select

from . import db
from .metrics import ALL_METRICS, BASELINE_TOLERANCE, CREW_METRICS, SHIP_METRICS, DECIMALS

WINDOW_MIN = 10       # history pulled per sensor
TREND_MIN = 5         # minutes used for the trend line
HORIZON_MIN = 60      # how far ahead we predict
SEVERITY_ORDER = {"critical": 0, "warning": 1, "watch": 2}

_cache = {"t": 0.0, "data": None}


def _status(v, lim):
    if lim is None:
        return "ok"
    if (lim.crit_low is not None and v <= lim.crit_low) or (lim.crit_high is not None and v >= lim.crit_high):
        return "critical"
    if (lim.warn_low is not None and v < lim.warn_low) or (lim.warn_high is not None and v > lim.warn_high):
        return "warning"
    return "ok"


def _fit(points):
    """Least-squares line. points: [(minutes, value)]. Returns slope/min and r^2."""
    n = len(points)
    if n < 10:
        return 0.0, 0.0
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx == 0:
        return 0.0, 0.0
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
    slope = sxy / sxx
    syy = sum((p[1] - my) ** 2 for p in points)
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    return slope, r2


def _eta(v, slope, bound, direction):
    """Minutes until v reaches bound when moving in direction (+1 up, -1 down)."""
    if bound is None or slope == 0:
        return None
    if direction > 0 and slope > 0 and bound > v:
        return (bound - v) / slope
    if direction < 0 and slope < 0 and bound < v:
        return (bound - v) / slope
    return None


def _fmt(metric, v):
    d = DECIMALS.get(metric, 1)
    return f"{v:.{d}f}"


def compute():
    if _cache["data"] is not None and time.time() - _cache["t"] < 2:
        return _cache["data"]
    t_now = db.now()
    since = t_now - timedelta(minutes=WINDOW_MIN)
    with db.engine.connect() as conn:
        lims = {r.metric: r for r in conn.execute(select(db.limits))}
        crew_rows = list(conn.execute(select(db.crew).order_by(db.crew.c.id)))
        sens = list(conn.execute(select(db.sensors).where(db.sensors.c.active.is_(True))))
        series = {s.id: [] for s in sens}
        q = (select(db.readings.c.sensor_id, db.readings.c.value, db.readings.c.ts)
             .where(db.readings.c.ts >= since).order_by(db.readings.c.ts))
        for r in conn.execute(q):
            if r.sensor_id in series:
                series[r.sensor_id].append(r)
        latest_any = {}
        missing = [s.id for s in sens if not series[s.id]]
        if missing:  # sensors with older data (e.g. manual entries) still show their last value
            for sid in missing:
                r = conn.execute(select(db.readings.c.value, db.readings.c.ts)
                                 .where(db.readings.c.sensor_id == sid)
                                 .order_by(db.readings.c.ts.desc()).limit(1)).first()
                if r:
                    latest_any[sid] = r
        cfg = db.get_settings(conn)

    alerts = []
    by_subject = {}
    for s in sens:
        spec = ALL_METRICS.get(s.metric)
        if not spec:
            continue
        lim = lims.get(s.metric)
        pts = series[s.id]
        if pts:
            v, ts = pts[-1].value, pts[-1].ts
        elif s.id in latest_any:
            v, ts = latest_any[s.id].value, latest_any[s.id].ts
        else:
            v, ts = None, None
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        item = dict(sensor_id=s.id, metric=s.metric, label=lim.label if lim else spec["label"],
                    unit=lim.unit if lim else spec["unit"], value=v, status="nodata",
                    trend="steady", slope=0.0, spark=[p.value for p in pts[-40:]],
                    updated=ts.isoformat() if ts else None, prediction=None, baseline=None)
        subj_key = ("crew", s.crew_id) if s.subject == "crew" else ("ship", None)
        by_subject.setdefault(subj_key, []).append(item)
        if v is None:
            continue
        stale = (t_now - ts).total_seconds() > 120
        item["status"] = "stale" if stale else _status(v, lim)
        who = None
        if s.subject == "crew":
            c = next((c for c in crew_rows if c.id == s.crew_id), None)
            who = c.name if c else "Crew"
        where = who or "Habitat"

        if item["status"] in ("critical", "warning"):
            alerts.append(dict(severity=item["status"], kind="limit", subject=s.subject,
                               crew_id=s.crew_id, metric=s.metric, who=where,
                               message=f"{item['label']} {_fmt(s.metric, v)} {item['unit']} "
                                       ("has reached the critical limit" if item['status'] == 'critical' else "is outside the safe range"),
                               value=v, eta_min=None))

        # --- trend + prediction ---
        cutoff = t_now - timedelta(minutes=TREND_MIN)
        tp = [((p.ts.replace(tzinfo=timezone.utc) if p.ts.tzinfo is None else p.ts) - t_now)
              .total_seconds() / 60 for p in pts]
        recent = [(m, p.value) for m, p in zip(tp, pts) if m >= -TREND_MIN]
        slope, r2 = _fit(recent)
        item["slope"] = round(slope, 4)
        span = (lim.warn_high or lim.crit_high or v * 1.2) - (lim.warn_low or lim.crit_low or v * 0.8) if lim else v
        meaningful = r2 >= 0.5 and abs(slope) * TREND_MIN > 0.04 * abs(span or 1)
        if meaningful:
            item["trend"] = "rising" if slope > 0 else "falling"
        if meaningful and lim and not stale and item["status"] != "critical":
            direction = 1 if slope > 0 else -1
            fitted_now = sum(x[1] for x in recent[-6:]) / min(6, len(recent))
            crit = lim.crit_high if direction > 0 else lim.crit_low
            warn = lim.warn_high if direction > 0 else lim.warn_low
            eta_c = _eta(fitted_now, slope, crit, direction)
            eta_w = _eta(fitted_now, slope, warn, direction) if item["status"] == "ok" else None
            if eta_c is not None and eta_c <= HORIZON_MIN:
                item["prediction"] = dict(level="critical", eta_min=round(eta_c), bound=crit)
                alerts.append(dict(severity="warning", kind="prediction", subject=s.subject,
                                   crew_id=s.crew_id, metric=s.metric, who=where,
                                   message=f"{item['label']} {item['trend']} — projected to reach critical "
                                           f"({_fmt(s.metric, crit)} {item['unit']}) in ~{max(1, round(eta_c))} min",
                                   value=v, eta_min=round(eta_c)))
            elif eta_w is not None and eta_w <= HORIZON_MIN / 2:
                item["prediction"] = dict(level="warning", eta_min=round(eta_w), bound=warn)
                alerts.append(dict(severity="watch", kind="prediction", subject=s.subject,
                                   crew_id=s.crew_id, metric=s.metric, who=where,
                                   message=f"{item['label']} {item['trend']} — likely to leave the safe range "
                                           f"in ~{max(1, round(eta_w))} min",
                                   value=v, eta_min=round(eta_w)))

        # --- personal baseline ---
        if s.subject == "crew" and s.metric in CREW_METRICS and not stale:
            c = next((c for c in crew_rows if c.id == s.crew_id), None)
            base = getattr(c, f"base_{s.metric}", None) if c else None
            if base:
                dev = (v - base) / base
                item["baseline"] = base
                if abs(dev) > BASELINE_TOLERANCE.get(s.metric, 0.2) and item["status"] == "ok":
                    alerts.append(dict(severity="watch", kind="baseline", subject="crew",
                                       crew_id=s.crew_id, metric=s.metric, who=where,
                                       message=f"{item['label']} {_fmt(s.metric, v)} {item['unit']} is "
                                               f"{abs(dev)*100:.0f}% {'above' if dev > 0 else 'below'} "
                                               f"their pre-flight baseline ({_fmt(s.metric, base)})",
                                       value=v, eta_min=None))

    order = {m: i for i, m in enumerate(list(CREW_METRICS) + list(SHIP_METRICS))}
    crew_out = []
    for c in crew_rows:
        items = sorted(by_subject.get(("crew", c.id), []), key=lambda i: order.get(i["metric"], 99))
        mine = [a for a in alerts if a["subject"] == "crew" and a["crew_id"] == c.id]
        score = sum({"critical": 4, "warning": 2, "watch": 1}[a["severity"]] for a in mine)
        risk = "high" if score >= 4 or any(a["severity"] == "critical" for a in mine) else \
               "watch" if score >= 1 else "low"
        crew_out.append(dict(id=c.id, name=c.name, role=c.role, risk=risk, score=score, metrics=items))
    ship_items = sorted(by_subject.get(("ship", None), []), key=lambda i: order.get(i["metric"], 99))
    ship_status = "critical" if any(i["status"] == "critical" for i in ship_items) else \
                  "warning" if any(i["status"] == "warning" for i in ship_items) else "ok"
    alerts.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], a["eta_min"] if a["eta_min"] is not None else 999))

    data = dict(updated=t_now.isoformat(), crew=crew_out,
                ship=dict(status=ship_status, metrics=ship_items), alerts=alerts,
                simulator=dict(enabled=cfg.get("simulator") == "on", scenario=cfg.get("scenario", "none"),
                               scenario_crew=cfg.get("scenario_crew") or None),
                mission_start=cfg.get("mission_start"))
    _cache.update(t=time.time(), data=data)
    return data


def invalidate():
    _cache["data"] = None
