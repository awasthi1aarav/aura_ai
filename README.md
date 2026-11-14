# AURA — Crew Health System

**NASA Space Apps Challenge 2026 · Create Health Monitoring Software for Astronauts on Space Missions · Team Orbital Five**

On a long mission, Earth is minutes away by radio and there is no doctor on board. AURA gathers every
astronaut's vitals and the cabin environment in one place, predicts problems before they become
emergencies, and lets the crew ask an AI assistant what is happening and what to do.

> Prototype for decision support. Not a medical device. The demo crew is fictional and live readings are simulated.

## The four parts

| Part | What it does |
|---|---|
| **1. Dashboard** | One screen with each astronaut's heart rate, SpO₂, blood pressure, respiration and temperature, plus the habitat's CO₂, O₂, pressure, temperature, humidity and radiation. Refreshes every 4 s. |
| **2. Analysis and prediction** | Three explainable checks on every sensor: **limits** (NASA-STD-3001 for the cabin, clinical early-warning bands for vitals), **personal baseline** (unusual *for this astronaut*), and a **trend forecast** (linear fit over 5 min, projected 60 min ahead, e.g. *"SpO₂ falling, critical in ~7 min"*). Each astronaut gets a risk level: Stable, Watch or Attention. |
| **3. AURA Assistant** | A chatbot that reads the live telemetry, baselines, alerts and forecasts before every answer, then assesses the crew member and suggests next steps. It uses Google Gemini (free tier) and falls back to a rule-based offline mode when no AI is available. |
| **4. Admin panel (CMS)** | Add or remove crew (and their baselines), sensors and API keys, alert limits, and manual readings; import CSV data (e.g. NASA OSDR); run demo scenarios. |

## How sensor data gets in

```
Sensor / wearable / ESP32 ──► POST /api/ingest ──► database ──► analysis + forecast ──► dashboard, alerts, assistant
```

Every sensor sends one small JSON message with its own API key:

```http
POST /api/ingest
X-API-Key: <sensor key from the admin panel>

{ "sensor_id": 8, "type": "spo2", "value": 97, "unit": "%", "timestamp": "2026-11-14T10:30:00Z" }
```

Gateways can send many readings at once to `/api/ingest/batch`. The built-in **simulator** produces
realistic readings for any sensor that has had no real data for 60 s, so connecting real hardware
needs no code changes. Interactive API docs are at `/docs`.

## Demo scenarios (Admin → Simulator)

Hypoxia · fever onset · rising blood pressure · CO₂ scrubber fault · slow cabin leak · solar particle event.
Each one develops over a few minutes, so the forecast flags it **before** it crosses a critical limit.

## Tech stack (all free tiers)

- **Backend:** Python, FastAPI, SQLAlchemy. Postgres on **Supabase** in production, SQLite locally.
- **Frontend:** React and Vite, hand-written CSS (no UI kit), served by the backend.
- **AI:** Google Gemini API (free tier; model auto-selected, override with `GEMINI_MODEL`) through a plain REST call.
- **Hosting:** Render (free web service).

## Run locally

```bash
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload            # http://localhost:8000  (admin password: aura-admin)

# optional, frontend hot-reload during design work:
cd frontend && npm install && npm run dev   # http://localhost:5173
npm run build                               # rebuild frontend/dist before committing
```

Environment variables: `DATABASE_URL` (Postgres; SQLite if unset), `GEMINI_API_KEY`, `GEMINI_MODEL`,
`ADMIN_PASSWORD`, `SECRET_KEY`.

## Project layout

```
backend/app/metrics.py    metric registry and default limits (with sources)
backend/app/simulator.py  sensor simulator and scenarios
backend/app/analysis.py   limits, baseline and trend forecast, plus risk score
backend/app/chat.py       AURA Assistant (Gemini, with offline fallback)
backend/app/main.py       API: public, ingest, admin (CMS), static web app
frontend/src/             dashboard, assistant, admin UI
docs/                     data sources and AI-use disclosure
```

See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) and [docs/AI_USE.md](docs/AI_USE.md).
