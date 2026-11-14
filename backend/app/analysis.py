"""Analysis + prediction engine.

Three checks per sensor, all explainable:
  1. Limits      - value vs. safe ranges (NASA-STD-3001 for the cabin, clinical bands for vitals)
  2. Baseline    - value vs. this astronaut's own pre-flight normal
  3. Trend       - linear fit over the last few minutes, projected forward to estimate
                   WHEN a limit will be crossed (the prediction)
"""
import threading
import time
from datetime import timedelta, timezone

from sqlalchemy import insert, select, update

from . import db
from . import knowledge
from .metrics import (ALL_METRICS, BASELINE_TOLERANCE, CHECKIN_METRICS, CREW_METRICS, DECIMALS, SHIP_METRICS,
                      SHIP_NOMINAL)

WINDOW_MIN = 10       # history pulled per sensor
TREND_MIN = 5         # minutes used for the trend line
HORIZON_MIN = 60      # how far ahead we predict
SEVERITY_ORDER = {"critical": 0, "warning": 1, "watch": 2}

_cache: dict[int, tuple[float, dict]] = {}


def _status(v, lim):
    if lim is None:
        return "ok"
    if (lim.crit_low is not None and v <= lim.crit_low) or (lim.crit_high is not None and v >= lim.crit_high):
        return "critical"
    if (lim.warn_low is not None and v < lim.warn_low) or (lim.warn_high is not None and v > lim.warn_high):
        return "warning"
    return "ok"


MIN_TREND_POINTS = 30   # ~2.5 min of 5-s readings before any forecast is made


def _fit(points):
    """Least-squares line. points: [(minutes, value)]. Returns slope/min, r^2 and residual std."""
    n = len(points)
    if n < MIN_TREND_POINTS:
        return 0.0, 0.0, 0.0
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx == 0:
        return 0.0, 0.0, 0.0
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
    slope = sxy / sxx
    syy = sum((p[1] - my) ** 2 for p in points)
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    resid = max(0.0, syy - slope * sxy) / max(1, n - 2)
    return slope, r2, resid ** 0.5


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


_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()
FRESH_S = 2.5     # results younger than this are served as-is
STALE_S = 15      # while one request recomputes, others may get a result up to this old


def compute(mission_id):
    """Cached per mission. Only one request computes at a time; the rest reuse the latest result."""
    hit = _cache.get(mission_id)
    if hit and time.time() - hit[0] < FRESH_S:
        return hit[1]
    with _locks_guard:
        lock = _locks.setdefault(mission_id, threading.Lock())
    if not lock.acquire(blocking=hit is None or time.time() - hit[0] > STALE_S):
        return hit[1]                     # someone else is refreshing: serve the slightly older result
    try:
        hit = _cache.get(mission_id)
        if hit and time.time() - hit[0] < FRESH_S:
            return hit[1]
        return _compute(mission_id)
    finally:
        lock.release()


def _compute(mission_id):
    t_now = db.now()
    since = t_now - timedelta(minutes=WINDOW_MIN)
    with db.engine.connect() as conn:
        m = conn.execute(select(db.missions).where(db.missions.c.id == mission_id)).first()
        lims = {r.metric: r for r in conn.execute(select(db.limits).where(db.limits.c.mission_id == mission_id))}
        crew_rows = list(conn.execute(select(db.crew).where(db.crew.c.mission_id == mission_id).order_by(db.crew.c.id)))
        sens = list(conn.execute(select(db.sensors).where(db.sensors.c.mission_id == mission_id,
                                                          db.sensors.c.active.is_(True))))
        series = {s.id: [] for s in sens}
        q = (select(db.readings.c.sensor_id, db.readings.c.value, db.readings.c.ts)
             .where(db.readings.c.ts >= since, db.readings.c.sensor_id.in_(list(series) or [-1]))
             .order_by(db.readings.c.ts))
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
        crew_ids = [c.id for c in crew_rows]
        wb_events = list(conn.execute(select(db.wellbeing).where(
            db.wellbeing.c.crew_id.in_(crew_ids or [-1]), db.wellbeing.c.ts >= t_now - timedelta(days=30))
            .order_by(db.wellbeing.c.ts)))
        checks = list(conn.execute(select(db.checkins).where(
            db.checkins.c.crew_id.in_(crew_ids or [-1]), db.checkins.c.ts >= t_now - timedelta(days=120))
            .order_by(db.checkins.c.ts)))

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
                               message=f"{item['label']} {_fmt(s.metric, v)} {item['unit']} " +
                                       ("has reached the critical limit" if item['status'] == 'critical' else "is outside the safe range"),
                               value=v, eta_min=None))

        # --- trend + prediction ---
        cutoff = t_now - timedelta(minutes=TREND_MIN)
        tp = [((p.ts.replace(tzinfo=timezone.utc) if p.ts.tzinfo is None else p.ts) - t_now)
              .total_seconds() / 60 for p in pts]
        recent = [(m, p.value) for m, p in zip(tp, pts) if m >= -TREND_MIN]
        slope, r2, noise = _fit(recent)
        item["slope"] = round(slope, 4)
        span = (lim.warn_high or lim.crit_high or v * 1.2) - (lim.warn_low or lim.crit_low or v * 0.8) if lim else v
        window = (recent[-1][0] - recent[0][0]) if recent else 0
        # a real trend: strong fit, a change well above the measurement noise, and a sizeable share of the safe range
        meaningful = (r2 >= 0.6 and abs(slope) * window > 3 * noise
                      and abs(slope) * TREND_MIN > 0.04 * abs(span or 1))
        if meaningful:
            item["trend"] = "rising" if slope > 0 else "falling"
        normal = None
        if s.subject == "crew":
            c0 = next((c for c in crew_rows if c.id == s.crew_id), None)
            normal = getattr(c0, f"base_{s.metric}", None) if c0 else None
        else:
            normal = SHIP_NOMINAL.get(s.metric)
        fitted_now = sum(x[1] for x in recent[-6:]) / min(6, len(recent)) if recent else v
        recovering = normal is not None and (fitted_now - normal) * slope < 0   # heading back towards normal
        if meaningful and lim and not stale and item["status"] != "critical" and not recovering:
            direction = 1 if slope > 0 else -1
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
                                   value=v, eta_min=round(eta_c), dir="high" if direction > 0 else "low"))
            elif eta_w is not None and eta_w <= HORIZON_MIN / 2:
                item["prediction"] = dict(level="warning", eta_min=round(eta_w), bound=warn)
                alerts.append(dict(severity="watch", kind="prediction", subject=s.subject,
                                   crew_id=s.crew_id, metric=s.metric, who=where,
                                   message=f"{item['label']} {item['trend']} — likely to leave the safe range "
                                           f"in ~{max(1, round(eta_w))} min",
                                   value=v, eta_min=round(eta_w), dir="high" if direction > 0 else "low"))

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

    # --- daily self check-ins, routine and streaks ---
    by_crew = {}
    for ck in checks:
        by_crew.setdefault(ck.crew_id, []).append(ck)
    wellness = {}
    for c in crew_rows:
        mine_ck = by_crew.get(c.id, [])
        last = mine_ck[-1] if mine_ck else None
        last_ts = (last.ts.replace(tzinfo=timezone.utc) if last and last.ts.tzinfo is None else last.ts) if last else None
        fresh = last is not None and (t_now - last_ts) < timedelta(hours=36)
        items = []
        recent_ck = [k for k in mine_ck if (t_now - (k.ts.replace(tzinfo=timezone.utc) if k.ts.tzinfo is None else k.ts))
                     < timedelta(hours=36)]
        for metric in CHECKIN_METRICS:
            lim = lims.get(metric)
            v = next((getattr(k, metric) for k in reversed(recent_ck) if getattr(k, metric) is not None), None)
            hist = [getattr(k, metric) for k in mine_ck[-7:] if getattr(k, metric) is not None]
            st = _status(v, lim) if v is not None else "nodata"
            items.append(dict(metric=metric, label=lim.label if lim else CHECKIN_METRICS[metric]["label"],
                              unit=lim.unit if lim else CHECKIN_METRICS[metric]["unit"], value=v, status=st,
                              history=hist, **knowledge.tag(metric)))
            if st in ("warning", "critical"):
                alerts.append(dict(severity=st, kind="checkin", subject="crew", crew_id=c.id, metric=metric,
                                   who=c.name, value=v, eta_min=None,
                                   message=f"Check-in: {items[-1]['label'].lower()} {_fmt(metric, v)} {items[-1]['unit']} "
                                           + ("needs attention" if st == "critical" else "is outside the healthy range")))
        sleeps = [k.sleep_hours for k in mine_ck[-3:] if k.sleep_hours is not None]
        if len(sleeps) == 3 and sum(sleeps) / 3 < 6.5 and all(i["status"] == "ok" for i in items if i["metric"] == "sleep_hours"):
            alerts.append(dict(severity="watch", kind="checkin", subject="crew", crew_id=c.id, metric="sleep_hours",
                               who=c.name, value=sleeps[-1], eta_min=None, dir="low",
                               message=f"Sleep averaging {sum(sleeps)/3:.1f} h over the last 3 nights"))
        # --- wellbeing: mood / connection / stress patterns, contact with home, support requests ---
        ev = [e for e in wb_events if e.crew_id == c.id]
        def _ts(x):
            return x.ts.replace(tzinfo=timezone.utc) if x.ts.tzinfo is None else x.ts
        calls = [e for e in ev if e.kind == "call_home"]
        last_call = _ts(calls[-1]) if calls else None
        days_since_call = (t_now - last_call).days if last_call else None
        support = [e for e in ev if e.kind == "support_request" and t_now - _ts(e) < timedelta(hours=24)]
        last3 = mine_ck[-3:]
        low_mood = sum(1 for k in last3 if k.mood is not None and k.mood <= 2)
        isolated = sum(1 for k in last3 if k.connection is not None and k.connection <= 2)
        stressed = sum(1 for k in last3 if k.stress is not None and k.stress >= 4)
        signals = []
        if low_mood >= 2:
            signals.append("low mood on 2 of the last 3 days")
        if isolated >= 2:
            signals.append("feeling isolated on 2 of the last 3 days")
        if stressed >= 2:
            signals.append("high stress on 2 of the last 3 days")
        if signals:
            alerts.append(dict(severity="warning" if len(signals) > 1 else "watch", kind="wellbeing", subject="crew",
                               crew_id=c.id, metric="wellbeing", who=c.name, value=None, eta_min=None,
                               message="Wellbeing: " + "; ".join(signals)))
        if days_since_call is None or days_since_call >= 7:
            alerts.append(dict(severity="watch", kind="routine", subject="crew", crew_id=c.id, metric=None,
                               who=c.name, value=None, eta_min=None,
                               message="No call home logged for 7+ days \u2014 consider scheduling one"))
        if support:
            alerts.append(dict(severity="warning", kind="wellbeing", subject="crew", crew_id=c.id, metric="wellbeing",
                               who=c.name, value=None, eta_min=None,
                               message="Requested a private talk with the flight psychologist"))
        wb_state = "attention" if support or len(signals) > 1 else "watch" if signals else "good"
        week = [k for k in mine_ck if t_now - _ts(k) < timedelta(days=14)]
        wb = dict(state=wb_state, signals=signals,
                  last_call_home=last_call.isoformat() if last_call else None, days_since_call=days_since_call,
                  calls_7d=sum(1 for e in calls if t_now - _ts(e) < timedelta(days=7)),
                  crew_time_7d=sum(1 for e in ev if e.kind == "crew_time" and t_now - _ts(e) < timedelta(days=7)),
                  support_requested=bool(support),
                  trend={m: [dict(t=_ts(k).isoformat(), v=getattr(k, m)) for k in week if getattr(k, m) is not None]
                         for m in ("mood", "connection", "stress")})

        due = last is None or (t_now - last_ts) > timedelta(hours=24)
        if due:
            alerts.append(dict(severity="watch", kind="routine", subject="crew", crew_id=c.id, metric=None,
                               who=c.name, value=None, eta_min=None,
                               message="Daily health check-in is due"))
        days_done = {(k.ts.replace(tzinfo=timezone.utc) if k.ts.tzinfo is None else k.ts).date() for k in mine_ck}
        today = t_now.date()
        d = today if today in days_done else today - timedelta(days=1)
        streak = 0
        while d in days_done:
            streak += 1
            d -= timedelta(days=1)
        today_ck = last if last is not None and last_ts.date() == today else None
        tasks = [
            dict(key="checkin", label="Morning health check-in", done=today_ck is not None),
            dict(key="sleep", label="Sleep 7 h or more", done=bool(today_ck and (today_ck.sleep_hours or 0) >= 7)),
            dict(key="exercise", label="Exercise 60 min or more", done=bool(today_ck and (today_ck.exercise_min or 0) >= 60)),
            dict(key="connect", label="Connect: call home or crew time",
                 done=any(e.kind in ("call_home", "crew_time") and _ts(e).date() == today for e in ev)),
        ]
        wellness[c.id] = dict(checkin=items, last_checkin=last_ts.isoformat() if last else None, due=due, wellbeing=wb,
                              streak=streak, tasks=tasks,
                              symptoms=[x for x in (last.symptoms or "").split(",") if x] if fresh else [])

    # --- tag every alert with its NASA hazard / HRP risk and an action card ---
    for a in alerts:
        a.update(knowledge.tag(a["metric"]) if a["metric"] else dict(hazard=None, hazard_label=None, risk=None))
        a["action"] = (knowledge.guidance(a["metric"], a["value"], lims.get(a["metric"]), a.get("dir"))
                       if a["metric"] and a["value"] is not None else None)
        if a["kind"] == "routine" and "call home" in a["message"]:
            a["action"] = dict(now=["Schedule a private call or video message home", "Log it in the Wellbeing panel"],
                               escalate="Regular contact with family and friends is one of the best protections "
                                        "against isolation on long missions.")
        elif a["kind"] == "routine":
            a["action"] = dict(now=["Open Check-in and log blood sugar, sleep, mood, exercise and any symptoms"],
                               escalate="Takes about one minute. Daily check-ins let AURA spot slow changes early.")
        if a["metric"] == "wellbeing":
            a.update(hazard="isolation", hazard_label=knowledge.HAZARDS["isolation"],
                     risk="Risk of Behavioral Changes and Psychiatric Disorders")
            a["action"] = knowledge.guidance("wellbeing", 0, True, "low")
    for lst in by_subject.values():
        for item in lst:
            item.update(knowledge.tag(item["metric"]))

    order = {m: i for i, m in enumerate(list(CREW_METRICS) + list(SHIP_METRICS))}
    crew_out = []
    for c in crew_rows:
        items = sorted(by_subject.get(("crew", c.id), []), key=lambda i: order.get(i["metric"], 99))
        mine = [a for a in alerts if a["subject"] == "crew" and a["crew_id"] == c.id and a["kind"] != "routine"]
        score = sum({"critical": 4, "warning": 2, "watch": 1}[a["severity"]] for a in mine)
        risk = "high" if score >= 4 or any(a["severity"] == "critical" for a in mine) else \
               "watch" if score >= 1 else "low"
        health = max(0, 100 - sum({"critical": 25, "warning": 12, "watch": 5}[a["severity"]] for a in mine))
        crew_out.append(dict(id=c.id, name=c.name, role=c.role, risk=risk, score=score, health=health,
                             metrics=items, **wellness.get(c.id, {})))
    ship_items = sorted(by_subject.get(("ship", None), []), key=lambda i: order.get(i["metric"], 99))
    ship_status = "critical" if any(i["status"] == "critical" for i in ship_items) else \
                  "warning" if any(i["status"] == "warning" for i in ship_items) else "ok"
    alerts.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], a["kind"] == "routine",
                               a["eta_min"] if a["eta_min"] is not None else 999))

    sev_rank = {"critical": 3, "warning": 2, "watch": 1}
    env = knowledge.ENVIRONMENTS.get(m.environment or knowledge.DEFAULT_ENV, knowledge.ENVIRONMENTS[knowledge.DEFAULT_ENV])
    hazards = []
    for key, label in knowledge.HAZARDS.items():
        hz = [a for a in alerts if a.get("hazard") == key]
        worst = max((a["severity"] for a in hz), key=lambda x: sev_rank[x], default=None)
        risks = sorted({a["risk"] for a in hz if a.get("risk")})
        metrics = [k for k, (h, _) in knowledge.METRIC_HAZARD.items() if h == key]
        hazards.append(dict(key=key, label=label, status=worst or "ok", count=len(hz), risks=risks, metrics=metrics))
    ms = m.mission_start
    if ms is not None and ms.tzinfo is None:
        ms = ms.replace(tzinfo=timezone.utc)
    earth = knowledge.earth_info(m.environment or knowledge.DEFAULT_ENV, ms, t_now)
    for h in hazards:
        if h["key"] == "distance":
            h["earth"] = earth
    data = dict(updated=t_now.isoformat(), crew=crew_out, hazards=hazards, earth=earth,
                environment=dict(key=m.environment or knowledge.DEFAULT_ENV, **env),
                crew_health=round(sum(c["health"] for c in crew_out) / len(crew_out)) if crew_out else None,
                ship=dict(status=ship_status, metrics=ship_items), alerts=alerts,
                simulator=dict(enabled=bool(m.simulator), scenario=m.scenario or "none",
                               scenario_crew=m.scenario_crew),
                mission=dict(code=m.code, name=m.name, is_demo=bool(m.is_demo)),
                mission_start=(ms.replace(tzinfo=timezone.utc) if ms and ms.tzinfo is None else ms).isoformat() if ms else None)
    _cache[mission_id] = (time.time(), data)
    _record_alerts(mission_id, alerts, t_now)
    return data


_last_log: dict[int, float] = {}
LOGGED_KINDS = ("limit", "checkin", "prediction")


def _record_alerts(mission_id, alerts, t_now):
    """Keep a history of alerts: open a row when an alert appears, close it when it clears."""
    if time.time() - _last_log.get(mission_id, 0) < 10:
        return
    _last_log[mission_id] = time.time()
    current = {}
    for a in alerts:
        if a["kind"] in LOGGED_KINDS and a["severity"] in ("warning", "critical"):
            current[f"{a['kind']}|{a['crew_id']}|{a['metric']}"] = a
    try:
        with db.engine.begin() as conn:
            open_rows = {r.key: r for r in conn.execute(select(db.alert_log).where(
                db.alert_log.c.mission_id == mission_id, db.alert_log.c.ended.is_(None)))}
            for key, r in open_rows.items():
                if key not in current:
                    conn.execute(update(db.alert_log).where(db.alert_log.c.id == r.id).values(ended=t_now))
                elif current[key]["severity"] == "critical" and r.severity != "critical":
                    conn.execute(update(db.alert_log).where(db.alert_log.c.id == r.id).values(
                        severity="critical", message=current[key]["message"]))
            new = [dict(mission_id=mission_id, crew_id=a["crew_id"], key=k, kind=a["kind"], severity=a["severity"],
                        metric=a["metric"], message=a["message"], hazard=a.get("hazard"), risk=a.get("risk"),
                        started=t_now) for k, a in current.items() if k not in open_rows]
            if new:
                conn.execute(insert(db.alert_log), new)
    except Exception:
        pass


def invalidate(mission_id=None):
    if mission_id is None:
        _cache.clear()
    else:
        _cache.pop(mission_id, None)
