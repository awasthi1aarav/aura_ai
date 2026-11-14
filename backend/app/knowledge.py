"""Domain knowledge: NASA's five hazards, Human Research Program (HRP) risks, action guidance and
mission environments.

Hazards and risk names follow NASA HRP:  https://www.nasa.gov/hrp/hazards/  and  https://www.nasa.gov/hrp/risks/
Guidance is general first-response advice for a decision-support prototype - not medical protocol.
"""

HAZARDS = {
    "radiation": "Space radiation",
    "isolation": "Isolation and confinement",
    "distance": "Distance from Earth",
    "gravity": "Gravity fields",
    "environment": "Hostile/closed environment",
}

# metric -> (hazard key, NASA HRP risk name or None)
METRIC_HAZARD = {
    "heart_rate": ("gravity", "Risk of Cardiovascular Adaptations"),
    "bp_sys": ("gravity", "Risk of Cardiovascular Adaptations"),
    "bp_dia": ("gravity", "Risk of Cardiovascular Adaptations"),
    "spo2": ("environment", "Risk of Hypoxia"),
    "resp_rate": ("environment", "Risk of Hypoxia"),
    "body_temp": ("environment", "Risk of Altered Immune System Responses"),
    "glucose": ("distance", "Risk of Inadequate Food and Nutrition"),
    "sleep_hours": ("isolation", "Risk of Inadequate Sleep and Irregular Schedules"),
    "mood": ("isolation", "Risk of Behavioral Changes and Psychiatric Disorders"),
    "connection": ("isolation", "Risk of Behavioral Changes and Psychiatric Disorders"),
    "stress": ("isolation", "Risk of Behavioral Changes and Psychiatric Disorders"),
    "cabin_co2": ("environment", None),
    "cabin_o2": ("environment", "Risk of Hypoxia"),
    "cabin_pressure": ("environment", "Risk of Decompression Sickness"),
    "cabin_temp": ("environment", None),
    "humidity": ("environment", None),
    "radiation": ("radiation", "Risk of Radiation-Induced Cancers"),
}

# metric -> direction ('low' | 'high') -> what to do now, and when to involve the flight surgeon
GUIDANCE = {
    "spo2": {"low": dict(
        now=["Check the sensor fit and re-measure at rest", "Stop strenuous activity, sit upright, breathe slowly",
             "Check cabin O₂ and CO₂ readings"],
        escalate="Contact the flight surgeon if SpO₂ stays below 94% after rest, or at once if below 91% "
                 "or with breathlessness, confusion or chest pain.")},
    "heart_rate": {
        "high": dict(now=["Rest seated for 5 minutes, then re-measure", "Hydrate", "Note symptoms: palpitations, dizziness, chest pain"],
                     escalate="Contact the flight surgeon if resting heart rate stays above 110 bpm, "
                              "or at once with chest pain, fainting or an irregular rhythm."),
        "low": dict(now=["Re-measure at rest", "Note dizziness or fatigue"],
                    escalate="Contact the flight surgeon if below 50 bpm with symptoms, or below 40 bpm.")},
    "bp_sys": {
        "high": dict(now=["Rest seated 5 minutes and re-measure", "Avoid heavy exertion", "Note headache or vision changes"],
                     escalate="Contact the flight surgeon if above 160 mmHg on repeat, or at once above 180 mmHg "
                              "or with headache, vision change or chest pain."),
        "low": dict(now=["Lie or sit down; raise legs if dizzy", "Hydrate", "Re-measure in 5 minutes"],
                    escalate="Contact the flight surgeon if below 90 mmHg or with fainting.")},
    "bp_dia": {
        "high": dict(now=["Rest and re-measure"], escalate="Contact the flight surgeon if above 95 mmHg on repeat."),
        "low": dict(now=["Rest, hydrate, re-measure"], escalate="Contact the flight surgeon if with dizziness or fainting.")},
    "resp_rate": {
        "high": dict(now=["Rest and re-count breaths for a full minute", "Check cabin CO₂ and O₂"],
                     escalate="Contact the flight surgeon if above 24/min at rest or with breathlessness."),
        "low": dict(now=["Re-count for a full minute", "Check alertness"],
                    escalate="Contact the flight surgeon at once if below 8/min or hard to wake.")},
    "body_temp": {
        "high": dict(now=["Rest and hydrate", "Re-measure in 30 minutes", "Watch for infection signs; limit close contact with crew"],
                     escalate="Contact the flight surgeon if above 38 °C for more than a few hours, or at once above 39 °C."),
        "low": dict(now=["Warm up: layers, warm drink", "Check cabin temperature"],
                    escalate="Contact the flight surgeon if below 35 °C.")},
    "glucose": {
        "low": dict(now=["Take 15 g of fast-acting carbohydrate", "Re-check in 15 minutes", "Do not operate critical systems until normal"],
                    escalate="Contact the flight surgeon if below 54 mg/dL, if it stays low after two treatments, "
                             "or with confusion."),
        "high": dict(now=["Hydrate", "Re-check before the next meal", "Review recent meals and activity"],
                     escalate="Contact the flight surgeon if above 250 mg/dL or with nausea, vomiting or confusion.")},
    "sleep_hours": {
        "low": dict(now=["Protect the next sleep period", "Reduce screen light before sleep", "Avoid caffeine late in the day"],
                    escalate="Tell the flight surgeon if under 6 hours for 3 nights or performance is affected."),
        "high": dict(now=["Note fatigue, low mood or illness signs"],
                     escalate="Tell the flight surgeon if unusually long sleep continues for several days.")},
    "mood": {"low": dict(
        now=["Take a short break and talk with a crewmate", "Keep the sleep, exercise and meal routine",
             "Use a scheduled private call home if available"],
        escalate="Talk to the flight surgeon or psychologist if low mood lasts more than 2 days, "
                 "or at once if feeling unsafe.")},
    "wellbeing": {"low": dict(
        now=["Reach out: call home or spend time with a crewmate today", "Keep the routine: sleep, meals, exercise",
             "Use the Wellbeing panel to request a private talk"],
        escalate="Contact the flight psychologist. If there are thoughts of self-harm, tell a crewmate "
                 "now and contact the flight surgeon immediately.")},
    "connection": {"low": dict(
        now=["Plan a call or message home today", "Share a meal, game or film with a crewmate",
             "Spend a few minutes looking at Earth or familiar photos"],
        escalate="Talk to the flight psychologist if feeling isolated for more than a few days, "
                 "or at once if feeling unsafe.")},
    "stress": {"high": dict(
        now=["Pause for 5 minutes of slow breathing", "Break the task into smaller steps; ask a crewmate for help",
             "Protect sleep and exercise time"],
        escalate="Talk to the flight psychologist if stress stays high for several days or affects sleep or work.")},
    "cabin_co2": {"high": dict(
        now=["Check CO₂ scrubber status", "Increase ventilation / fans", "Watch crew for headache and fatigue"],
        escalate="Notify mission control if above 3 mmHg (NASA-STD-3001 1-hour limit).")},
    "cabin_o2": {
        "low": dict(now=["Check the O₂ supply system", "Have crew watch for breathlessness"],
                    escalate="Notify mission control at once; prepare emergency O₂ if below 127 mmHg."),
        "high": dict(now=["Check O₂ supply; reduce flow"], escalate="Notify mission control (fire risk rises with O₂).")},
    "cabin_pressure": {"low": dict(
        now=["Follow the depressurisation checklist", "Locate the leak", "Prepare suits / safe haven"],
        escalate="Notify mission control at once.")},
    "cabin_temp": {
        "high": dict(now=["Check thermal control system", "Hydrate crew"], escalate="Notify mission control if above 27 °C."),
        "low": dict(now=["Check thermal control system", "Add layers"], escalate="Notify mission control if below 18 °C.")},
    "humidity": {
        "high": dict(now=["Check the condensing heat exchanger"], escalate="Notify mission control if above 75% (mould/condensation risk)."),
        "low": dict(now=["Hydrate; protect eyes and airways"], escalate="Notify mission control if below 25%.")},
    "radiation": {"high": dict(
        now=["Move crew to the most shielded area", "Postpone spacewalks", "Log exposure time"],
        escalate="Notify mission control and the flight surgeon at once during a solar particle event.")},
}

# ---------- distance from Earth ----------
import math
from datetime import datetime, timezone

AU_KM = 149_597_870.7
C_KM_S = 299_792.458
J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
MOON_KM = 384_400
STATION_KM = 420
TRANSIT_DAYS = 210            # assumed Earth-to-Mars transfer for a deep-space crew vehicle


def _lon(t, l0, period):
    return math.radians((l0 + 360.0 * (t - J2000).total_seconds() / 86400 / period) % 360)


def _earth(t):
    return 1.0, _lon(t, 100.464, 365.256)


def _mars(t):
    return 1.524, _lon(t, 355.453, 686.98)


def _dist(a, b):
    (r1, l1), (r2, l2) = a, b
    return math.sqrt(r1 * r1 + r2 * r2 - 2 * r1 * r2 * math.cos(l1 - l2)) * AU_KM


def _fmt_dur(s):
    if s < 60:
        return f"{s:.1f} s" if s >= 1 else f"{s * 1000:.0f} ms"
    return f"{s / 60:.1f} min"


def earth_info(env_key, mission_start, now):
    """Where the crew is relative to Earth. Planet positions use simplified circular orbits."""
    day = max(0.0, (now - mission_start).total_seconds() / 86400) if mission_start else 0.0
    extra = None
    if env_key == "station":
        km, back = STATION_KM, "About 6\u201324 hours (undock, de-orbit and land)"
        note = "Low Earth orbit, about 420 km up"
    elif env_key in ("lunar_base", "lunar_rover"):
        km, back = MOON_KM, "About 3 days" + (" (drive back to base first)" if env_key == "lunar_rover" else "")
        note = "Average Earth\u2013Moon distance"
    elif env_key == "mars_base":
        km = _dist(_earth(now), _mars(now))
        back = "About 7\u20139 months of travel, after waiting for a launch window (about every 26 months)"
        note = "Estimated from simplified planetary orbits"
    else:  # deep-space transit to Mars
        f = min(1.0, day / TRANSIT_DAYS)
        launch = mission_start or now
        r = 1.0 + 0.524 * (1 - math.cos(math.pi * f)) / 2
        ship = (r, _earth(launch)[1] + math.pi * f)
        km = _dist(_earth(now), ship)
        left = max(0, TRANSIT_DAYS - day)
        back = "Months \u2014 a deep-space ship can't turn around; a return follows a planned trajectory"
        note = f"Estimated position on a {TRANSIT_DAYS}-day Earth\u2013Mars transfer"
        extra = f"Mars arrival in about {left:.0f} days" if left > 0 else "At Mars"
    light = km / C_KM_S
    return dict(distance_km=round(km), light_one_way=_fmt_dur(light), light_round_trip=_fmt_dur(2 * light),
                light_seconds=round(light, 3), return_time=back, mission_day=int(day) + 1, note=note, extra=extra)


ENVIRONMENTS = {
    "station": dict(label="Space station (low Earth orbit)", gravity="Microgravity",
                    delay="Near real-time (under 1 s)", g=0.0),
    "spacecraft": dict(label="Deep-space spacecraft (transit)", gravity="Microgravity",
                       delay="Seconds to over 20 min, growing with distance", g=0.0),
    "lunar_base": dict(label="Lunar surface base", gravity="About 1/6 g (Moon)",
                       delay="About 1.3 s each way", g=0.17),
    "lunar_rover": dict(label="Pressurised lunar rover", gravity="About 1/6 g (Moon)",
                        delay="About 1.3 s each way; may lose line of sight", g=0.17),
    "mars_base": dict(label="Mars surface base", gravity="About 3/8 g (Mars)",
                      delay="About 3–22 min each way", g=0.38),
}
DEFAULT_ENV = "spacecraft"


def guidance(metric, value, lim, direction=None):
    """Pick the 'low' or 'high' card for a reading outside (or heading outside) its range."""
    g = GUIDANCE.get(metric)
    if not g or lim is None:
        return None
    if direction is None:
        mid_low = lim.warn_low if lim.warn_low is not None else lim.crit_low
        direction = "low" if (mid_low is not None and value <= mid_low) else "high"
    card = g.get(direction) or next(iter(g.values()))
    return dict(now=card["now"], escalate=card["escalate"])


def tag(metric):
    hz, risk = METRIC_HAZARD.get(metric, (None, None))
    return dict(hazard=hz, hazard_label=HAZARDS.get(hz), risk=risk)
