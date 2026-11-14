"""AURA assistant: answers crew questions using the live data, alerts and predictions.

Uses Google Gemini (free tier) when GEMINI_API_KEY is set; otherwise falls back to a
rule-based offline responder so the system still works with no internet / no key.
"""
import logging
import os

import httpx

log = logging.getLogger("uvicorn.error")

from .analysis import compute

MODELS = [m for m in [os.getenv("GEMINI_MODEL"), "gemini-flash-latest", "gemini-3.5-flash",
                       "gemini-3-flash-preview", "gemini-2.5-flash"] if m]
_working = {"model": None}
DISCLAIMER = "AURA is a decision-support prototype, not a medical device."

SYSTEM = f"""You are AURA, the onboard health assistant of a crewed spacecraft on a long-duration mission.
Earth is minutes away by radio, so the crew relies on you first.

You receive LIVE TELEMETRY below: each astronaut's vitals (with their personal pre-flight
baseline), the cabin environment, and the alerts/predictions produced by AURA's analysis engine.

How to answer:
- Ground every statement in the telemetry. Quote the actual numbers. Never invent readings.
- Assess the person: what is abnormal, how serious it is, and the most likely causes
  (consider cabin conditions too, e.g. high CO2 causes headaches and faster breathing).
- Say what the trend predicts if nothing changes (use the prediction ETAs given).
- Give clear, practical next steps for the crew, and say when to contact the flight surgeon
  on Earth or treat it as an emergency.
- Use phrases like "possible", "consistent with" - you assess, you do not give a final diagnosis.
- Be calm, precise and brief: short paragraphs or a few bullet points, under 180 words.
- If asked something unrelated to crew health or the spacecraft, briefly steer back.
- End with one short line: "{DISCLAIMER}"
"""


def _fmt_metric(m):
    if m["value"] is None:
        return f"  - {m['label']}: no data"
    line = f"  - {m['label']}: {m['value']} {m['unit']} [{m['status']}, {m['trend']}]"
    if m.get("baseline") is not None:
        line += f" (baseline {m['baseline']})"
    if m.get("prediction"):
        p = m["prediction"]
        line += f" -> projected to reach {p['level']} ({p['bound']}) in ~{p['eta_min']} min"
    return line


def build_context(crew_id=None):
    d = compute()
    out = [f"Telemetry time (UTC): {d['updated']}"]
    for c in d["crew"]:
        if crew_id and c["id"] != crew_id:
            continue
        out.append(f"\nASTRONAUT {c['name']} ({c['role']}), overall risk: {c['risk'].upper()}")
        out += [_fmt_metric(m) for m in c["metrics"]]
    out.append(f"\nCABIN / SHIP (status {d['ship']['status']}):")
    out += [_fmt_metric(m) for m in d["ship"]["metrics"]]
    rel = [a for a in d["alerts"] if not crew_id or a["subject"] == "ship" or a["crew_id"] == crew_id]
    out.append("\nACTIVE ALERTS:" if rel else "\nACTIVE ALERTS: none")
    out += [f"  - [{a['severity']}] {a['who']}: {a['message']}" for a in rel[:15]]
    return "\n".join(out), d, rel


def offline_reply(message, d, rel, crew_id, note="AI model not configured"):
    who = next((c for c in d["crew"] if c["id"] == crew_id), None)
    lines = []
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


async def reply(message, history, crew_id=None):
    context, d, rel = build_context(crew_id)
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return offline_reply(message, d, rel, crew_id), "offline"
    contents = []
    for h in (history or [])[-8:]:
        role = "model" if h.get("role") == "assistant" else "user"
        if h.get("text"):
            contents.append({"role": role, "parts": [{"text": h["text"][:2000]}]})
    contents.append({"role": "user", "parts": [{"text": f"LIVE TELEMETRY\n{context}\n\nQUESTION: {message[:2000]}"}]})
    body = {"system_instruction": {"parts": [{"text": SYSTEM}]}, "contents": contents,
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}}
    models = [_working["model"]] if _working["model"] else MODELS
    async with httpx.AsyncClient(timeout=30) as client:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                r = await client.post(url, headers={"x-goog-api-key": key}, json=body)
            except Exception as e:
                log.error("Gemini request error (%s): %s", model, type(e).__name__)
                break
            if r.status_code == 404:
                log.error("Gemini model %s not found, trying next", model)
                continue
            if r.status_code != 200:
                log.error("Gemini HTTP %s (%s): %s", r.status_code, model, r.text[:300])
                break
            try:
                cand = r.json()["candidates"][0]
                text = "".join(p.get("text", "") for p in cand["content"]["parts"]).strip()
            except (KeyError, IndexError, ValueError):
                text = ""
            if text:
                _working["model"] = model
                return text, "gemini"
            log.error("Gemini returned no text (%s)", model)
            break
    return offline_reply(message, d, rel, crew_id, "AI model unavailable right now"), "offline"
