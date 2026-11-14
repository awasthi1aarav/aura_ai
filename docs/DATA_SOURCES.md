# Data and resources

## NASA

| Resource | How AURA uses it |
|---|---|
| **NASA-STD-3001 Vol. 2 [V2 6004]**: 1-hour average cabin ppCO₂ ≤ 3 mmHg | Critical limit for cabin CO₂ |
| **NASA OCHMO Technical Brief TB-004, Carbon Dioxide**: keeping CO₂ below 2.5 mmHg keeps headache risk under 1 % | Warning limit for cabin CO₂; the assistant's CO₂ explanations |
| **NASA-STD-3001 Vol. 2 [V2 6012]**: operating range 18–27 °C, 25–75 % RH | Cabin temperature and humidity limits |
| **NASA-STD-3001 Vol. 2**: inspired O₂ normoxia 145–155 mmHg, mild hypoxia lower limit 127 mmHg | Cabin ppO₂ limits |
| **NASA OCHMO Technical Briefs TB-002 (ECLSS) and TB-003 (Habitable Atmosphere)** | Which environmental parameters to monitor and trend |
| **NASA Open Science Data Repository (OSDR)**, e.g. OSD-575 (Inspiration4 crew blood panels) | Can be loaded through Admin → Readings → CSV import as reference / historical data |

Links:
- https://www.nasa.gov/reference/6-0-natural-and-induced-environments-vol-2
- https://www.nasa.gov/ochmo-tb-004-carbon-dioxide-2/
- https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-002-eclss.pdf
- https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-003-habitable-atmosphere.pdf
- https://osdr.nasa.gov/

## Partner agencies

- **CSA Bio-Monitor** smart shirt (ECG/heart rate, blood pressure, respiration, SpO₂, skin temperature):
  the model for AURA's per-astronaut sensor set. https://www.asc-csa.gc.ca/eng/sciences/bio-monitor.asp

## Other

- Vital-sign bands follow the general shape of clinical early-warning scores (NEWS2-style). They are starting values that mission medical staff can change in Admin → Limits.
- Radiation alert levels are mission-defined placeholders, not NASA limits.
- **All crew members and live readings in the demo are fictional or simulated.** No real personal health data is used.
- Open-source software: FastAPI, SQLAlchemy, React, Vite, IBM Plex and Cormorant Garamond fonts (SIL OFL).
