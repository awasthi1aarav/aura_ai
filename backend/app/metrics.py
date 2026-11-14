"""Metric registry: every value AURA understands, with default limits and their source.

Limits can be changed later in the admin panel; these are only the starting values.
"""

VITALS_SOURCE = "Clinical early-warning bands (NEWS2-style), adjustable per mission"

CREW_METRICS = {
    "heart_rate": dict(label="Heart rate", unit="bpm", warn_low=50, warn_high=110,
                       crit_low=40, crit_high=130, source=VITALS_SOURCE),
    "spo2": dict(label="SpO₂", unit="%", warn_low=94, warn_high=None,
                 crit_low=91, crit_high=None, source=VITALS_SOURCE),
    "bp_sys": dict(label="Systolic BP", unit="mmHg", warn_low=100, warn_high=160,
                   crit_low=90, crit_high=220, source=VITALS_SOURCE),
    "bp_dia": dict(label="Diastolic BP", unit="mmHg", warn_low=55, warn_high=95,
                   crit_low=45, crit_high=110, source="Standard hypertension bands, adjustable"),
    "resp_rate": dict(label="Respiration", unit="br/min", warn_low=11, warn_high=21,
                      crit_low=8, crit_high=25, source=VITALS_SOURCE),
    "body_temp": dict(label="Body temp", unit="°C", warn_low=36.0, warn_high=38.0,
                      crit_low=35.0, crit_high=39.1, source=VITALS_SOURCE),
}

SHIP_METRICS = {
    "cabin_co2": dict(label="Cabin CO₂", unit="mmHg", warn_low=None, warn_high=2.5,
                      crit_low=None, crit_high=3.0,
                      source="NASA-STD-3001 Vol 2 [V2 6004]: 1-h avg ppCO2 ≤ 3 mmHg; "
                             "<2.5 mmHg keeps headache risk <1% (OCHMO-TB-004)"),
    "cabin_o2": dict(label="Cabin ppO₂", unit="mmHg", warn_low=145, warn_high=356,
                     crit_low=127, crit_high=None,
                     source="NASA-STD-3001 Vol 2: normoxia 145–155 mmHg, mild hypoxia limit 127 mmHg"),
    "cabin_pressure": dict(label="Cabin pressure", unit="kPa", warn_low=97.0, warn_high=104.0,
                           crit_low=91.0, crit_high=106.0,
                           source="ISS nominal ~101.3 kPa (14.7 psia); bands adjustable"),
    "cabin_temp": dict(label="Cabin temp", unit="°C", warn_low=18.0, warn_high=27.0,
                       crit_low=15.0, crit_high=30.0,
                       source="NASA-STD-3001 Vol 2 [V2 6012]: operating range 18–27 °C"),
    "humidity": dict(label="Humidity", unit="%RH", warn_low=25, warn_high=75,
                     crit_low=15, crit_high=85,
                     source="NASA-STD-3001 Vol 2 [V2 6012]: 25–75 % RH"),
    "radiation": dict(label="Radiation", unit="µSv/h", warn_low=None, warn_high=40,
                      crit_low=None, crit_high=100,
                      source="Mission-defined alert levels (ISS background is roughly 20 µSv/h)"),
}

ALL_METRICS = {**CREW_METRICS, **SHIP_METRICS}

# Normal "resting" values used by the simulator for the ship.
SHIP_NOMINAL = {
    "cabin_co2": 1.9, "cabin_o2": 152.0, "cabin_pressure": 101.3,
    "cabin_temp": 22.5, "humidity": 45.0, "radiation": 18.0,
}

# Default personal baselines (pre-flight normals) for new crew.
DEFAULT_BASELINE = {
    "heart_rate": 66, "spo2": 98, "bp_sys": 118, "bp_dia": 76,
    "resp_rate": 14, "body_temp": 36.8,
}

# How far from a person's own baseline counts as "unusual for them".
BASELINE_TOLERANCE = {
    "heart_rate": 0.25, "spo2": 0.03, "bp_sys": 0.18, "bp_dia": 0.18,
    "resp_rate": 0.35, "body_temp": 0.025,
}

# Noise and decimals the simulator uses.
SIM_NOISE = {
    "heart_rate": 1.6, "spo2": 0.35, "bp_sys": 2.0, "bp_dia": 1.5, "resp_rate": 0.6,
    "body_temp": 0.04, "cabin_co2": 0.04, "cabin_o2": 0.6, "cabin_pressure": 0.08,
    "cabin_temp": 0.08, "humidity": 0.5, "radiation": 1.2,
}
DECIMALS = {
    "heart_rate": 0, "spo2": 0, "bp_sys": 0, "bp_dia": 0, "resp_rate": 0, "body_temp": 1,
    "cabin_co2": 2, "cabin_o2": 0, "cabin_pressure": 1, "cabin_temp": 1,
    "humidity": 0, "radiation": 0,
}
