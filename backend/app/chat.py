"""AURA assistant: answers crew questions using the live data, alerts and predictions.

Uses Google Gemini (free tier) when GEMINI_API_KEY is set; otherwise falls back to a
rule-based offline responder so the system still works with no internet / no key.
"""
import logging
import os
import time

import httpx

log = logging.getLogger("uvicorn.error")

from .analysis import compute
from .metrics import DECIMALS
from .simulator import SCENARIOS as SCENARIO_TEXT

MODELS = [m for m in [os.getenv("GEMINI_MODEL"), "gemini-flash-lite-latest", "gemini-flash-latest",
                       "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3.5-flash"] if m]
BUDGET_S = 35        # total time for one answer before falling back to offline mode
PER_CALL_S = 14      # one slow model must not use up the whole budget
_working = {"model": None}
DISCLAIMER = "AURA is a decision-support prototype, not a medical device."

SYSTEM = """You are AURA, the onboard health assistant of a crewed spacecraft on a long-duration mission.
Earth is minutes away by radio, so the crew asks you first. You talk like a calm, experienced
flight surgeon: precise, warm, never dramatic.

Each message comes with LIVE TELEMETRY (vitals with personal baselines, cabin environment,
and the alerts/forecasts from AURA's analysis engine). Use it as your source of truth.

Conversation rules:
- Answer the question that was asked, nothing more. Do not recite every vital each time;
  mention only the numbers that matter for this question.
- Short acknowledgements or small talk ("ok", "thanks", "hi") get one short, natural sentence.
- Follow the conversation: if they ask a follow-up, build on what you already said instead of repeating it.
- When something is abnormal: say what it is, how serious, the likely causes (consider the cabin too,
  e.g. high CO2 causes headache and faster breathing), what the forecast says if nothing changes,
  and the next steps, including when to call the flight surgeon on Earth or treat it as an emergency.
- You assess, you do not diagnose: use "possible", "consistent with".
- Never invent readings. If data is missing, say so.
- No timestamps, no "based on live telemetry" openers, no closing disclaimers (the app shows one).
- Keep it brief: 1-3 short paragraphs or a few bullets, under 150 words unless asked for detail.
- Off-topic questions: one friendly line steering back to crew health or the spacecraft.
- When relevant, link issues to NASA's five spaceflight hazards and the named HRP risk, and consider
  the mission environment (gravity, signal delay: the farther from Earth, the more the crew must act on
  their own before the flight surgeon can respond).
- If the daily check-in is due or a symptom is reported, you may gently suggest logging it.
- Questions about AURA itself ("what does this mean", "what is the simulation", "how does the forecast
  work") are welcome: explain plainly using ABOUT AURA below and the DATA SOURCE line. If a training
  scenario is active, say clearly that the readings are a simulated event for practice, not a real emergency.

ABOUT AURA (for questions about the app):
- Dashboard: live vitals per astronaut and the cabin, NASA's five hazards, alerts and forecasts.
- Simulator: when no real wearable is connected, AURA generates realistic readings. Mission admins can
  start training scenarios (hypoxia, fever, high blood pressure, CO2 scrubber fault, cabin leak, solar
  particle event) that develop over a few minutes so the crew can practise spotting them early.
- Forecasts: a trend line over the last 5 minutes, projected up to 60 minutes ahead.
- Alerts compare readings with safety limits (NASA-STD-3001 for the cabin, clinical bands for vitals)
  and with each astronaut's own pre-flight baseline.
- Daily check-in: blood sugar, sleep, mood, feeling of connection, stress, exercise and symptoms.
- Wellbeing: tracks mood, connection and stress, logs contact with home, and lets an astronaut ask
  for a private talk with the flight psychologist.
- Health records keep every check-in and alert; history is kept for 90 days.

WELLBEING CONVERSATIONS (loneliness, low mood, stress, homesickness):
- Be warm and human first: acknowledge the feeling, then help. Isolation and distance from home are
  well-known parts of long missions, and feeling this way is common and not a weakness.
- Offer small, concrete steps: a call or message home, time with a crewmate (shared meal, game,
  movie), a look at Earth from the window, exercise, keeping the sleep routine, a hobby or music.
- Encourage talking with the flight psychologist / behavioural health team; AURA can request a
  private talk from the Wellbeing panel.
- You are not a therapist and do not diagnose depression.
- If someone mentions hopelessness, wanting to die or harming themselves: respond with care, tell them
  they deserve support right now, and urge them to tell a crewmate immediately and contact the flight
  surgeon/psychologist now. Keep them talking; do not change the subject.
"""


def _n(metric, v):
    return f"{v:.{DECIMALS.get(metric, 1)}f}" if isinstance(v, (int, float)) else v


def _fmt_metric(m):
    if m["value"] is None:
        return f"  - {m['label']}: no data"
    line = f"  - {m['label']}: {_n(m['metric'], m['value'])} {m['unit']} [{m['status']}, {m['trend']}]"
    if m.get("baseline") is not None:
        line += f" (baseline {_n(m['metric'], m['baseline'])})"
    if m.get("prediction"):
        p = m["prediction"]
        line += f" -> projected to reach {p['level']} ({_n(m['metric'], p['bound'])}) in ~{p['eta_min']} min"
    return line


def build_context(mission_id, crew_id=None):
    d = compute(mission_id)
    env = d.get("environment") or {}
    sim = d.get("simulator") or {}
    e = d.get("earth") or {}
    out = [f"MISSION: {(d.get('mission') or {}).get('name')} | ENVIRONMENT: {env.get('label')} | gravity: "
           f"{env.get('gravity')} | mission day {e.get('mission_day')}",
           f"EARTH: {e.get('distance_km', 0):,} km away ({e.get('note')}); one-way signal {e.get('light_one_way')}, "
           f"round trip {e.get('light_round_trip')}; time to return to Earth: {e.get('return_time')}"
           + (f"; {e['extra']}" if e.get("extra") else "")]
    if sim.get("enabled"):
        sc = sim.get("scenario") or "none"
        target = next((c["name"] for c in d["crew"] if c["id"] == sim.get("scenario_crew")), None)
        out.append("DATA SOURCE: simulated sensor readings (AURA's built-in simulator stands in for real wearables; "
                   "real sensors replace it automatically when connected). "
                   + (f"Active training scenario: '{SCENARIO_TEXT.get(sc, sc)}'"
                      + (f" affecting {target}" if target else "") + "." if sc != "none"
                      else "No training scenario is running (normal operations)."))
    for c in d["crew"]:
        if crew_id and c["id"] != crew_id:
            continue
        out.append(f"\nASTRONAUT {c['name']} ({c['role']}), overall risk: {c['risk'].upper()}, "
                   f"health score {c.get('health')}/100, check-in streak {c.get('streak', 0)} days")
        out += [_fmt_metric(m) for m in c["metrics"]]
        ck = [f"{i['label']} {_n(i['metric'], i['value'])} {i['unit']} [{i['status']}]"
              for i in c.get("checkin", []) if i["value"] is not None]
        out.append("  Latest self check-in: " + ("; ".join(ck) if ck else "none in the last 36 h"))
        if c.get("symptoms"):
            out.append("  Reported symptoms: " + ", ".join(c["symptoms"]))
        wb = c.get("wellbeing") or {}
        if wb:
            out.append(f"  Wellbeing: {wb.get('state')}"
                       + (f" ({'; '.join(wb['signals'])})" if wb.get("signals") else "")
                       + f"; last call home: {wb['days_since_call']} days ago" if wb.get("days_since_call") is not None
                       else f"  Wellbeing: {wb.get('state')}; no call home logged recently")
            if wb.get("support_requested"):
                out.append("  Has requested a private talk with the flight psychologist.")
        if c.get("due"):
            out.append("  Daily check-in is due.")
    out.append(f"\nCABIN / SHIP (status {d['ship']['status']}):")
    out += [_fmt_metric(m) for m in d["ship"]["metrics"]]
    rel = [a for a in d["alerts"] if not crew_id or a["subject"] == "ship" or a["crew_id"] == crew_id]
    out.append("\nACTIVE ALERTS:" if rel else "\nACTIVE ALERTS: none")
    out += [f"  - [{a['severity']}] {a['who']}: {a['message']}"
            + (f" (NASA hazard: {a['hazard_label']}; HRP risk: {a['risk']})" if a.get("hazard_label") else "")
            for a in rel[:15]]
    hz = [f"{h['label']}: {h['status']}" for h in d.get("hazards", [])]
    out.append("\nNASA FIVE HAZARDS STATUS: " + "; ".join(hz))
    return "\n".join(out), d, rel


CRISIS_WORDS = ("suicid", "kill myself", "end my life", "want to die", "harm myself", "hurt myself",
                "self-harm", "self harm", "no reason to live", "better off without me")
FEELING_WORDS = ("lonely", "alone", "isolated", "sad", "depress", "down", "homesick", "miss home", "miss my",
                 "anxious", "anxiety", "stress", "overwhelm", "hopeless", "can't cope", "cant cope", "upset",
                 "scared", "afraid", "worried", "tired of", "low mood", "cry")


def _feelings_reply(message, who):
    text = message.lower()
    name = who["name"].split()[-1] if who else ""
    if any(w in text for w in CRISIS_WORDS):
        return ("I'm really glad you told me. What you're feeling matters, and you deserve support right now.\n"
                "- Please tell a crewmate now, so you're not alone with this.\n"
                "- Contact the flight surgeon or flight psychologist immediately; use the Wellbeing panel to request a "
                "private talk, and call mission control directly if you can.\n"
                "- Stay with someone until you've spoken to them.\n"
                "I'm here and you can keep talking to me while you reach out.")
    if any(w in text for w in FEELING_WORDS):
        return ("That sounds hard, and it makes sense. Months of isolation and distance from home weigh on everyone, "
                "and feeling this way isn't a weakness.\n"
                "A few things that often help:\n"
                "- Reach out to someone today: a call or message home, or time with a crewmate.\n"
                "- Keep the basics steady: sleep, meals and exercise.\n"
                "- Take a few minutes for something of your own, or a look at Earth from the window.\n"
                "If it has lasted more than a couple of days, please talk to the flight psychologist; you can request "
                "a private talk from the Wellbeing panel" + (f", {name}" if name else "") + ".")
    return None


def offline_reply(message, d, rel, crew_id, note="AI model not configured"):
    who = next((c for c in d["crew"] if c["id"] == crew_id), None)
    feel = _feelings_reply(message, who)
    if feel:
        return feel
    busy = "busy" in note
    lines = (["The AI assistant is busy right now, so here is AURA's automatic summary. Please ask again in a "
              "minute for a full answer."] if busy else [])
    if who:
        lines.append(f"{who['name']} — current risk: {who['risk'].upper()}.")
    if not rel:
        lines.append("All monitored values are within limits and close to baseline. No action needed; "
                     "keep normal monitoring.")
    else:
        lines.append("What I'm seeing:")
        for a in rel[:6]:
            lines.append(f"• {a['who']}: {a['message']}.")
        hints = {
            "spo2": "Low oxygen saturation: check the sensor fit, have the crew member rest, and check cabin ppO₂. "
                    "If SpO₂ keeps falling, give supplemental O₂ and contact the flight surgeon.",
            "cabin_co2": "High CO₂ commonly causes headache, fatigue and faster breathing. Check the CO₂ scrubber "
                         "and increase ventilation.",
            "body_temp": "Rising temperature with a faster heart rate is consistent with infection or overheating. "
                         "Hydrate, rest, and re-check every 15 min.",
            "bp_sys": "Rising blood pressure: have them rest seated, re-measure in 5 min and report to the flight surgeon.",
            "cabin_pressure": "Falling cabin pressure suggests a leak: follow the depress checklist.",
            "radiation": "Elevated radiation: move the crew to the shielded area until levels drop.",
        }
        seen = set()
        for a in rel:
            h = hints.get(a["metric"])
            if h and h not in seen:
                seen.add(h)
                lines.append(h)
    lines.append(f"(Offline mode — {note}.) {DISCLAIMER}")
    return "\n".join(lines)


async def reply(mission_id, message, history, crew_id=None):
    context, d, rel = build_context(mission_id, crew_id)
    if any(w in message.lower() for w in CRISIS_WORDS):
        # never depend on an external AI (which may be busy) for a safety-critical message
        return _feelings_reply(message, next((c for c in d["crew"] if c["id"] == crew_id), None)), "safety"
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return offline_reply(message, d, rel, crew_id), "offline"
    contents = []
    for h in (history or [])[-8:]:
        role = "model" if h.get("role") == "assistant" else "user"
        if h.get("text"):
            contents.append({"role": role, "parts": [{"text": h["text"][:2000]}]})
    contents.append({"role": "user", "parts": [{"text": f"LIVE TELEMETRY\n{context}\n\nQUESTION: {message[:2000]}"}]})
    base = {"system_instruction": {"parts": [{"text": SYSTEM}]}, "contents": contents}

    def body_for(model, thinking=True):
        gen = {"temperature": 0.3, "maxOutputTokens": 2048}
        if thinking:  # keep "thinking" short so answers arrive in a few seconds
            gen["thinkingConfig"] = ({"thinkingBudget": 0} if "2.5" in model
                                     else {"thinkingLevel": "low"})
        return {**base, "generationConfig": gen}

    models = ([_working["model"]] if _working["model"] else []) + [m for m in MODELS if m != _working["model"]]
    deadline = time.monotonic() + BUDGET_S
    missing = set()
    async with httpx.AsyncClient() as client:
        for attempt in range(2):                      # second pass retries models that were only busy
            for model in models:
                left = deadline - time.monotonic()
                if left < 3:
                    break
                if model in missing:
                    continue
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                tmo = httpx.Timeout(min(PER_CALL_S, left), connect=5)
                try:
                    r = await client.post(url, headers={"x-goog-api-key": key}, json=body_for(model), timeout=tmo)
                    if r.status_code == 400:  # model doesn't accept that thinking setting
                        r = await client.post(url, headers={"x-goog-api-key": key}, json=body_for(model, False),
                                              timeout=tmo)
                except Exception as e:
                    log.error("Gemini request error (%s): %s", model, type(e).__name__)
                    continue
                if r.status_code == 404:
                    missing.add(model)
                    continue
                if r.status_code != 200:
                    log.error("Gemini HTTP %s (%s): %s", r.status_code, model, r.text[:160].replace("\n", " "))
                    if r.status_code in (429, 500, 502, 503, 504):
                        continue  # busy or rate-limited: try the next model
                    missing.add(model)
                    continue
                try:
                    cand = r.json()["candidates"][0]
                    text = "".join(p.get("text", "") for p in cand["content"]["parts"]).strip()
                except (KeyError, IndexError, ValueError):
                    text = ""
                if text:
                    _working["model"] = model
                    return text, "gemini"
                log.error("Gemini returned no text (%s)", model)
    return offline_reply(message, d, rel, crew_id, "the AI service is busy"), "offline"


async def warm_up():
    """Find a working Gemini model at startup so the first crew question is fast."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return
    body = {"contents": [{"role": "user", "parts": [{"text": "Reply with OK."}]}],
            "generationConfig": {"maxOutputTokens": 20}}
    async with httpx.AsyncClient(timeout=30) as client:
        for model in MODELS:
            try:
                r = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                      headers={"x-goog-api-key": key}, json=body)
            except Exception:
                continue
            if r.status_code == 200:
                _working["model"] = model
                log.info("Assistant model ready: %s", model)
                return
