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

MODELS = [m for m in [os.getenv("GEMINI_MODEL"), "gemini-flash-latest", "gemini-flash-lite-latest",
                       "gemini-3.5-flash", "gemini-2.5-flash"] if m]
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


def build_context(crew_id=None):
    d = compute()
    out = []
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
    base = {"system_instruction": {"parts": [{"text": SYSTEM}]}, "contents": contents}

    def body_for(model, thinking=True):
        gen = {"temperature": 0.3, "maxOutputTokens": 2048}
        if thinking:  # keep "thinking" short so answers arrive in a few seconds
            gen["thinkingConfig"] = ({"thinkingBudget": 0} if "2.5" in model
                                     else {"thinkingLevel": "low"})
        return {**base, "generationConfig": gen}

    models = ([_working["model"]] if _working["model"] else []) + [m for m in MODELS if m != _working["model"]]
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=30) as client:
        for model in models:
            if time.monotonic() - t0 > 50:
                break
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                r = await client.post(url, headers={"x-goog-api-key": key}, json=body_for(model))
                if r.status_code == 400:  # model doesn't accept that thinking setting
                    r = await client.post(url, headers={"x-goog-api-key": key}, json=body_for(model, False))
            except Exception as e:
                log.error("Gemini request error (%s): %s", model, type(e).__name__)
                continue
            if r.status_code == 404:
                log.error("Gemini model %s not found, trying next", model)
                continue
            if r.status_code != 200:
                log.error("Gemini HTTP %s (%s): %s", r.status_code, model, r.text[:200].replace("\n", " "))
                if r.status_code in (429, 500, 503):
                    continue  # busy or rate-limited: try the next model
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
