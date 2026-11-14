# AURA — Crew Health System

**NASA Space Apps Challenge 2026 · Create Health Monitoring Software for Astronauts on Space Missions · Team Orbital Five**

**Live demo:** https://aura-ai-bk7d.onrender.com

On a long mission, Earth is minutes away by radio and there is no doctor on board. AURA gathers every
astronaut's vitals and the cabin environment in one place, predicts problems before they become
emergencies, and lets the crew ask an AI assistant what is happening and what to do.

> Prototype for decision support. Not a medical device. The demo crew is fictional and live readings are simulated.

## Missions (like game servers)

Anyone can **host a mission**: give it a name and a password, and AURA creates a private copy
with its own crew, sensors, limits, simulator scenarios, assistant chats and activity log. Share the
6-character **join code** or the link `…/#/m/CODE`. Anyone with it can watch the dashboard and use
the assistant; changing anything needs the mission password. Changes in one mission never affect
another. A shared **Demo mission** (`DEMO`) is the default page. Missions with no visitors for 90 days
are removed automatically.

## Built around NASA's challenge

| Challenge asks for | AURA |
|---|---|
| Astronauts assess their own health | **Daily self check-in** (blood sugar, sleep, mood, exercise, symptoms) on each crew member's **health profile** |
| Suggested indicators: BP, heart rate, blood sugar, temperature, sleep, mood | All six, plus SpO₂, respiration and the cabin environment |
| NASA's five hazards of spaceflight | **Hazard watch** panel; every alert is tagged with its hazard and NASA HRP risk |
| Clickable human body figure | **Interactive body map**: each system shows status, readings, what spaceflight does to it, how to measure it, and the HRP risk |
| Guidance; when to involve flight surgeons | **Action cards** on every alert: what to do now and when to escalate |
| Prompt measurements as a routine; gamification | Check-in reminders, **today's routine** checklist, **streaks** and a **health score** |
| Charts over time; color coding | **Trend charts for 24 h, 7, 30 and 90 days** with the healthy range shaded; status colors throughout |
| (keeping records) | **Health records**: a searchable timeline of every check-in, symptom, note and alert per astronaut; **backup download** (JSON, or CSV for spreadsheets) and **restore** into a new mission |
| Behavioral health (isolation, low mood) | **Wellbeing panel**: mood, connection and stress trends from the check-in, calls home and crew time, pattern alerts (e.g. low mood 2 of 3 days), one-tap **request for a private talk with the flight psychologist**, and a supportive assistant with a safety response that never depends on the AI service |
| Distance from Earth | **Earth panel**: live distance, one-way signal time, question-and-answer delay, time to return to Earth and mission day, per environment (planet positions from a simplified orbit model) |
| Different environments | Each mission is a **space station, deep-space spacecraft, lunar base, lunar rover or Mars base**, with its gravity and signal delay shown and given to the assistant |

## The four parts

| Part | What it does |
|---|---|
| **1. Dashboard** | One screen with each astronaut's heart rate, SpO₂, blood pressure, respiration and temperature, plus the habitat's CO₂, O₂, pressure, temperature, humidity and radiation. Refreshes every 4 s. |
| **2. Analysis and prediction** | Three explainable checks on every sensor: **limits** (NASA-STD-3001 for the cabin, clinical early-warning bands for vitals), **personal baseline** (unusual *for this astronaut*), and a **trend forecast** (linear fit over 5 min, projected 60 min ahead, e.g. *"SpO₂ falling, critical in ~7 min"*). Each astronaut gets a risk level: Stable, Watch or Attention. |
| **3. AURA Assistant** | A chatbot that reads the live telemetry, baselines, alerts and forecasts before every answer, then assesses the crew member and suggests next steps. It uses Google Gemini (free tier) and falls back to a rule-based offline mode when no AI is available. |
| **4. Admin panel (CMS)** | Per mission, unlocked with the mission password: add or remove crew (and their baselines), sensors and API keys, alert limits and readings; import CSV data (e.g. NASA OSDR); run demo scenarios; rename the mission, change its password or end it; view its activity log. A separate **Team** page (`#/team`) lets the AURA team oversee every mission. |

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

## Team and how AURA was built

**Team Orbital Five** (5 members): Aarav Awasthi (team lead, backend), one more on backend, two on
database and one on frontend. The team set the product vision and made the design decisions; the AI coding
assistant Claude wrote most of the code under the team's direction.

**What the team brought:**
- **The product:** four parts (dashboard, analysis and alerts, AI assistant, admin panel), prediction
  from each astronaut's own baseline, a hardware-agnostic sensor pipeline, a free-tier-only budget,
  and a minimal white-and-gold design.
- **The ideas that shape AURA:** missions that work like game servers, wellbeing support for loneliness
  and low mood, distance and travel time to Earth, and long-term health records with backup.
- **Fit to the challenge:** the team brought NASA's official challenge text and resources and required
  every point to be covered.
- **Quality and security:** the team asked for privacy between users, a security review and a full
  stress test, and tested the live app (finding, for example, the assistant failures that were fixed).
- **Infrastructure:** the team set up and runs GitHub, Render, Supabase, the Gemini API key and the
  keep-alive job.

AI use is disclosed in full in [docs/AI_USE.md](docs/AI_USE.md).

## Run locally

```bash
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload            # http://localhost:8000  (Demo mission password and team login admin: aura-admin)

# optional, frontend hot-reload during design work:
cd frontend && npm install && npm run dev   # http://localhost:5173
npm run build                               # rebuild frontend/dist before committing
```

Environment variables: `DATABASE_URL` (Postgres; SQLite if unset), `GEMINI_API_KEY`, `GEMINI_MODEL`,
`ADMIN_PASSWORD` (Demo mission password and first team account), `SECRET_KEY`, `ALLOWED_ORIGINS` (optional).

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

See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), [docs/AI_USE.md](docs/AI_USE.md) and [SECURITY.md](SECURITY.md).
