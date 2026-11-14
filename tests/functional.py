"""Functional + security test suite for AURA (run against any base URL)."""
import json
import sys
import time
import uuid

import httpx

import os

# Usage: AURA_ADMIN_PASSWORD=... python functional.py <base-url>
B = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
DEMO_PW = os.environ.get("AURA_ADMIN_PASSWORD", "aura-admin")   # never hard-code real passwords
TEAM_PW = DEMO_PW
c = httpx.Client(base_url=B, timeout=60)
results = []


def check(name, cond, info=""):
    results.append((name, bool(cond), info))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info and not cond else ""))


def H(tok=None, client=None, **kw):
    h = {"X-Client-Id": client or "suite-" + "0" * 20}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    h.update(kw)
    return h


# ---------- public ----------
r = c.get("/api/health"); check("health 200", r.status_code == 200)
r = c.get("/"); check("web app served", r.status_code == 200 and "<div id=\"root\">" in r.text)
for h in ["content-security-policy", "x-frame-options", "strict-transport-security", "x-content-type-options"]:
    check(f"header {h}", h in r.headers)
check("unknown api path 404", c.get("/api/does-not-exist").status_code == 404)
r = c.get("/api/m/DEMO/overview"); d = r.json()
check("demo overview", r.status_code == 200 and len(d["crew"]) >= 1 and len(d["hazards"]) == 5)
check("overview has environment", "environment" in d and d["environment"].get("label"))
crew = d["crew"]; cid = crew[0]["id"]
check("crew has checkin/tasks/health", all(k in crew[0] for k in ("checkin", "tasks", "health", "streak")))
check("missing mission 404", c.get("/api/m/ZZZZZZ/overview").status_code == 404)
check("meta", c.get("/api/m/DEMO/meta").status_code == 200)
for rng in ["24h", "7d", "30d", "90d"]:
    r = c.get(f"/api/m/DEMO/history?metric=heart_rate&crew_id={cid}&range={rng}")
    check(f"history {rng}", r.status_code == 200 and len(r.json()["points"]) > 0, r.text[:80])
r = c.get("/api/m/DEMO/history?metric=cabin_co2&range=7d"); check("ship history", r.status_code == 200 and r.json()["points"])
r = c.get(f"/api/m/DEMO/history?metric=sleep_hours&crew_id={cid}&range=30d"); check("checkin history", r.status_code == 200)
r = c.get(f"/api/m/DEMO/records?crew_id={cid}&days=90"); check("records", r.status_code == 200 and len(r.json()) > 0)
check("records bad crew 404", c.get("/api/m/DEMO/records?crew_id=999999").status_code == 404)

# ---------- host a mission ----------
r = c.post("/api/missions", json={"name": "Suite Mission", "password": "suitepass1", "environment": "mars_base"})
check("host mission", r.status_code == 200, r.text[:100])
M = r.json()["code"]; HT = r.json()["token"]
mo = c.get(f"/api/m/{M}/overview").json()
check("hosted env = mars", mo["environment"]["key"] == "mars_base")
check("weak host password rejected", c.post("/api/missions", json={"name": "X", "password": "short"}).status_code == 422)
check("bad environment rejected", c.post("/api/missions", json={"name": "Xyz", "password": "longenough1", "environment": "venus"}).status_code == 422)

# ---------- admin CRUD in own mission ----------
check("admin needs auth", c.get(f"/api/m/{M}/admin/crew").status_code == 401)
r = c.post(f"/api/m/{M}/admin/crew", headers=H(HT), json={"name": "Test Astro", "role": "Pilot", "baseline": {"heart_rate": 70}})
check("add crew", r.status_code == 200); NC = r.json()["id"]
check("edit crew", c.put(f"/api/m/{M}/admin/crew/{NC}", headers=H(HT), json={"name": "Test Astro 2", "role": "Pilot"}).status_code == 200)
sens = c.get(f"/api/m/{M}/admin/sensors", headers=H(HT)).json()
check("sensors auto-created", sum(1 for s in sens if s["crew_id"] == NC) == 6)
spo2 = next(s for s in sens if s["crew_id"] == NC and s["metric"] == "spo2")
r = c.post(f"/api/m/{M}/admin/sensors", headers=H(HT), json={"name": "Extra CO2", "metric": "cabin_co2"})
check("add sensor", r.status_code == 200); XS = r.json()["id"]
check("checkin metric not a sensor", c.post(f"/api/m/{M}/admin/sensors", headers=H(HT), json={"name": "G", "metric": "glucose"}).status_code == 422)
r = c.post(f"/api/m/{M}/admin/sensors/{XS}/rotate-key", headers=H(HT)); check("rotate key", r.status_code == 200)
check("disable sensor", c.put(f"/api/m/{M}/admin/sensors/{XS}", headers=H(HT), json={"name": "Extra CO2", "metric": "cabin_co2", "active": False}).status_code == 200)
check("delete sensor", c.delete(f"/api/m/{M}/admin/sensors/{XS}", headers=H(HT)).status_code == 200)
check("edit limit", c.put(f"/api/m/{M}/admin/limits/spo2", headers=H(HT), json={"warn_low": 95, "crit_low": 90}).status_code == 200)
lim = {l["metric"]: l for l in c.get(f"/api/m/{M}/admin/limits", headers=H(HT)).json()}
check("limit saved", lim["spo2"]["warn_low"] == 95 and "glucose" in lim)

# ---------- sensor ingest ----------
r = c.post("/api/ingest", headers={"X-API-Key": spo2["api_key"]}, json={"sensor_id": spo2["id"], "type": "spo2", "value": 88})
check("ingest ok", r.status_code == 200, r.text)
check("ingest bad key", c.post("/api/ingest", headers={"X-API-Key": "nope"}, json={"sensor_id": spo2["id"], "value": 90}).status_code == 403)
check("ingest wrong type", c.post("/api/ingest", headers={"X-API-Key": spo2["api_key"]}, json={"sensor_id": spo2["id"], "type": "heart_rate", "value": 90}).status_code == 422)
check("ingest non-number", c.post("/api/ingest", headers={"X-API-Key": spo2["api_key"]}, json={"sensor_id": spo2["id"], "value": "abc"}).status_code == 422)
r = c.post("/api/ingest/batch", headers={"X-API-Key": f"{spo2['id']}:{spo2['api_key']}"},
           json={"readings": [{"sensor_id": spo2["id"], "value": 87}, {"sensor_id": spo2["id"], "value": 86}]})
check("ingest batch", r.status_code == 200)
time.sleep(2.5)
mo = c.get(f"/api/m/{M}/overview").json()
astro = next(x for x in mo["crew"] if x["id"] == NC)
sp = next(m for m in astro["metrics"] if m["metric"] == "spo2")
check("device value shown + critical", sp["value"] == 86 and sp["status"] == "critical", f"{sp['value']} {sp['status']}")
al = [a for a in mo["alerts"] if a["crew_id"] == NC and a["metric"] == "spo2"]
check("critical alert with action card + hazard", al and al[0]["action"] and al[0]["risk"] == "Risk of Hypoxia")

# ---------- manual reading, csv ----------
check("manual reading", c.post(f"/api/m/{M}/admin/readings", headers=H(HT), json={"sensor_id": spo2["id"], "value": 97}).status_code == 200)
csvdata = f"sensor_id,value,timestamp\n{spo2['id']},96,2026-11-14T05:00:00Z\n{spo2['id']},oops,\n999999,5,\n"
r = c.post(f"/api/m/{M}/admin/readings/csv", headers=H(HT), files={"file": ("x.csv", csvdata, "text/csv")})
check("csv import partial", r.status_code == 200 and r.json()["imported"] == 1 and len(r.json()["errors"]) == 2, r.text[:100])
rd = c.get(f"/api/m/{M}/admin/readings?limit=5", headers=H(HT)).json()
check("delete reading", c.delete(f"/api/m/{M}/admin/readings/{rd[0]['id']}", headers=H(HT)).status_code == 200)

# ---------- check-ins ----------
r = c.post(f"/api/m/{M}/checkin", json={"crew_id": NC, "glucose": 50, "sleep_hours": 4.5, "mood": 1, "exercise_min": 0,
                                        "symptoms": ["headache", "eye or vision change"], "note": "<script>alert(1)</script>"})
check("checkin", r.status_code == 200, r.text[:100])
check("checkin bad symptom", c.post(f"/api/m/{M}/checkin", json={"crew_id": NC, "symptoms": ["zombie"]}).status_code == 422)
check("checkin out of range", c.post(f"/api/m/{M}/checkin", json={"crew_id": NC, "glucose": 5000}).status_code == 422)
check("checkin mood 6 rejected", c.post(f"/api/m/{M}/checkin", json={"crew_id": NC, "mood": 6}).status_code == 422)
mo = c.get(f"/api/m/{M}/overview").json()
astro = next(x for x in mo["crew"] if x["id"] == NC)
ck = {i["metric"]: i["status"] for i in astro["checkin"]}
check("checkin statuses", {k: ck.get(k) for k in ("glucose", "sleep_hours", "mood")} ==
      {"glucose": "critical", "sleep_hours": "warning", "mood": "critical"}, str(ck))
r = c.post(f"/api/m/{M}/checkin", json={"crew_id": NC, "connection": 1, "stress": 5})
check("checkin connection/stress", r.status_code == 200)
r = c.post(f"/api/m/{M}/wellbeing", json={"crew_id": NC, "kind": "support_request"})
check("support request", r.status_code == 200)
check("bad wellbeing kind", c.post(f"/api/m/{M}/wellbeing", json={"crew_id": NC, "kind": "x"}).status_code == 422)
mo = c.get(f"/api/m/{M}/overview").json()
astro = next(x for x in mo["crew"] if x["id"] == NC)
check("wellbeing needs support", astro["wellbeing"]["state"] == "attention" and astro["wellbeing"]["support_requested"])
check("earth info", mo["earth"]["distance_km"] > 1e7 and mo["earth"]["return_time"])
check("streak >= 1 and tasks", astro["streak"] >= 1 and astro["tasks"][0]["done"])
check("isolation hazard raised", next(h for h in mo["hazards"] if h["key"] == "isolation")["status"] in ("warning", "critical"))
recs = c.get(f"/api/m/{M}/records?crew_id={NC}&days=7").json()
check("record has script as plain text", any("<script>" in (x.get("note") or "") for x in recs))
check("records search", len(c.get(f"/api/m/{M}/records?crew_id={NC}&days=7&q=vision").json()) >= 1)

# ---------- simulator + environment + mission edit ----------
check("start scenario", c.post(f"/api/m/{M}/admin/simulator", headers=H(HT), json={"enabled": True, "scenario": "fever", "scenario_crew": NC}).status_code == 200)
check("scenario crew from other mission rejected",
      c.post(f"/api/m/{M}/admin/simulator", headers=H(HT), json={"enabled": True, "scenario": "fever", "scenario_crew": cid}).status_code == 404)
check("edit env", c.put(f"/api/m/{M}/admin/mission", headers=H(HT), json={"environment": "lunar_base"}).status_code == 200)
check("env updated", c.get(f"/api/m/{M}/overview").json()["environment"]["key"] == "lunar_base")
check("demo untouched by scenario", c.get("/api/m/DEMO/overview").json()["simulator"]["scenario"] != "fever")

# ---------- isolation / authorization ----------
check("host token cannot admin DEMO", c.get("/api/m/DEMO/admin/crew", headers=H(HT)).status_code == 403)
check("IDOR: delete DEMO crew via own mission", c.delete(f"/api/m/{M}/admin/crew/{cid}", headers=H(HT)).status_code == 404)
check("IDOR: manual reading to DEMO sensor", c.post(f"/api/m/{M}/admin/readings", headers=H(HT), json={"sensor_id": 1, "value": 1}).status_code == 404)
check("IDOR: checkin DEMO crew via own mission", c.post(f"/api/m/{M}/checkin", json={"crew_id": cid, "mood": 3}).status_code == 404)
check("forged token rejected", c.get(f"/api/m/{M}/admin/crew", headers=H("eyJ1IjoiYWRtaW4iLCJyIjoiYWRtaW4ifQ.deadbeef")).status_code == 401)
check("wrong mission password", c.post(f"/api/missions/{M}/login", json={"password": "wrongwrong"}).status_code == 401)
r = c.post(f"/api/missions/{M}/login", json={"password": "suitepass1"}); check("right mission password", r.status_code == 200)

# ---------- chat privacy + history ----------
A, Bc = "suite-a-" + uuid.uuid4().hex[:16], "suite-b-" + uuid.uuid4().hex[:16]
r = c.post(f"/api/m/{M}/chat", headers=H(client=A), json={"message": "How is Test Astro doing?", "crew_id": NC})
check("chat reply", r.status_code == 200 and r.json()["reply"], r.text[:120])
check("chat source", r.json().get("source") in ("gemini", "offline"), r.json().get("source"))
check("history visible to owner", len(c.get(f"/api/m/{M}/chat/history?crew_id={NC}", headers=H(client=A)).json()) == 2)
check("history hidden from others", len(c.get(f"/api/m/{M}/chat/history?crew_id={NC}", headers=H(client=Bc)).json()) == 0)
check("chat needs client id", c.post(f"/api/m/{M}/chat", json={"message": "x"}).status_code == 400)
check("chat crew from other mission", c.post(f"/api/m/{M}/chat", headers=H(client=A), json={"message": "x", "crew_id": cid}).status_code == 404)
check("chat too long", c.post(f"/api/m/{M}/chat", headers=H(client=A), json={"message": "x" * 2001}).status_code == 422)

# ---------- export / restore ----------
r = c.get(f"/api/m/{M}/admin/export", headers=H(HT)); check("export json", r.status_code == 200 and r.json()["aura_backup"] == 1)
bk = r.text
check("export has no api keys", "api_key" not in bk and "pw_hash" not in bk)
check("export csv checkins", c.get(f"/api/m/{M}/admin/export?format=csv&what=checkins", headers=H(HT)).text.startswith("time_utc"))
check("export csv vitals", c.get(f"/api/m/{M}/admin/export?format=csv&what=vitals", headers=H(HT)).text.startswith("hour_utc"))
check("export needs auth", c.get(f"/api/m/{M}/admin/export").status_code == 401)
check("restore garbage rejected", c.post("/api/missions/restore", files={"file": ("x.json", "not json", "application/json")},
                                         data={"name": "Bad", "password": "longenough1"}).status_code == 422)
evil = json.loads(bk); evil["sensors"].append({"ref": 1, "name": "x", "metric": "evil", "subject": "ship"})
evil["crew"] = evil["crew"] * 3  # 15 crew > 12 limit
check("restore over limits rejected", c.post("/api/missions/restore", files={"file": ("x.json", json.dumps(evil), "application/json")},
                                             data={"name": "Bad", "password": "longenough1"}).status_code == 422)

# ---------- team ----------
r = c.post("/api/team/login", json={"username": "admin", "password": TEAM_PW}); check("team login", r.status_code == 200)
TT = r.json()["token"]
check("team sees missions", any(m["code"] == M for m in c.get("/api/team/missions", headers=H(TT)).json()))
check("team can admin any mission", c.get(f"/api/m/{M}/admin/crew", headers=H(TT)).status_code == 200)
au = c.get(f"/api/m/{M}/admin/audit", headers=H(HT)).json()
check("audit logged changes", len(au) >= 10 and any(a["action"].startswith("export") for a in au))
check("team cannot delete demo", c.delete("/api/team/missions/DEMO", headers=H(TT)).status_code == 409)
check("delete crew", c.delete(f"/api/m/{M}/admin/crew/{NC}", headers=H(HT)).status_code == 200)
check("end mission", c.delete(f"/api/m/{M}/admin/mission", headers=H(HT)).status_code == 200)
check("ended mission gone", c.get(f"/api/missions/{M}").status_code == 404)

# ---------- rate limits (last: they lock this IP briefly; skip with SKIP_LIMITS=1) ----------
if os.environ.get("SKIP_LIMITS"):
    fails = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(fails)}/{len(results)} passed (rate-limit tests skipped)")
    for f in fails:
        print("FAILED:", f[0], f[2])
    sys.exit(0)
codes = [c.post(f"/api/m/DEMO/chat", headers=H(client="suite-rl-" + "1" * 16), json={"message": "hi"}).status_code for _ in range(11)]
check("chat rate limit 429", 429 in codes, str(codes))
c.delete("/api/m/DEMO/chat/history", headers=H(client="suite-rl-" + "1" * 16))
codes = [c.post("/api/missions/DEMO/login", json={"password": f"wrong{i}xx"}).status_code for i in range(6)]
check("login lockout 429", codes[-1] == 429, str(codes))

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} passed")
for f in fails:
    print("FAILED:", f[0], f[2])
