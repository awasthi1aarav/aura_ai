import React, { useState } from 'react'
import { fmt, getMission } from '../api.js'

export function Spark({ values, status }) {
  if (!values || values.length < 2) return <svg className="spark" viewBox="0 0 100 24" />
  const min = Math.min(...values), max = Math.max(...values)
  const pad = (max - min) * 0.15 || 1
  const lo = min - pad, hi = max + pad
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * 100,
    24 - ((v - lo) / (hi - lo)) * 24,
  ])
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const last = pts[pts.length - 1]
  return (
    <svg className={`spark s-${status}`} viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true">
      <path d={d} />
      <circle cx={last[0]} cy={last[1]} r="1.6" />
    </svg>
  )
}

const ARROW = { rising: '↗', falling: '↘', steady: '' }
const RISK_LABEL = { low: 'Stable', watch: 'Watch', high: 'Attention' }

function Metric({ m }) {
  return (
    <div className={`metric st-${m.status}`}>
      <div className="m-label">{m.label}</div>
      <div className="m-value">
        <span className="mono">{fmt(m.value, m.metric)}</span>
        <span className="m-unit">{m.unit}</span>
        {ARROW[m.trend] && <span className="m-trend" title={`Trend: ${m.trend}`}>{ARROW[m.trend]}</span>}
      </div>
      <Spark values={m.spark} status={m.status} />
      {m.prediction && (
        <div className="m-pred">→ {m.prediction.level} in ~{Math.max(1, m.prediction.eta_min)} min</div>
      )}
    </div>
  )
}

function CrewCard({ c }) {
  return (
    <article className={`card crew risk-${c.risk}`}>
      <div className="card-head">
        <div>
          <h3>{c.name}</h3>
          <div className="role">{c.role}</div>
        </div>
        <span className={`pill p-${c.risk}`}>{RISK_LABEL[c.risk]}</span>
      </div>
      <div className="metrics">
        {c.metrics.map(m => <Metric key={m.sensor_id} m={m} />)}
      </div>
      <div className="ck-row">
        {c.checkin?.map(i => (
          <span key={i.metric} className={`ck st-${i.status}`}>
            <span className="m-label">{i.label}</span> <span className="mono">{fmt(i.value, i.metric)}</span> <span className="m-unit">{i.unit}</span>
          </span>
        ))}
        {c.due && <span className="due">Check-in due</span>}
      </div>
      <div className="card-foot">
        <span className="sub">Score <b className="mono">{c.health}</b> · Streak <b className="mono">{c.streak}</b>d</span>
        <span>
          <a className="ask" href={`#/m/${getMission()}/crew/${c.id}`}>Health profile</a>
          <a className="ask" href={`#/m/${getMission()}/assistant?crew=${c.id}`}>Ask AURA →</a>
        </span>
      </div>
    </article>
  )
}

function AlertItem({ a }) {
  const [open, setOpen] = useState(a.severity === 'critical')
  return (
    <li className={`al al-${a.severity}`}>
      <div className="al-top">
        <span className="al-sev">{a.severity}</span>
        <span className="al-kind">{{ limit: 'Limit', prediction: 'Forecast', baseline: 'Baseline', checkin: 'Check-in', routine: 'Routine', wellbeing: 'Wellbeing' }[a.kind]}</span>
      </div>
      <div className="al-who">{a.who}</div>
      <div className="al-msg">{a.message}</div>
      {(a.hazard_label || a.risk) && (
        <div className="tags">
          {a.hazard_label && <span className="tag-hz">{a.hazard_label}</span>}
          {a.risk && <span className="tag-risk">{a.risk}</span>}
        </div>
      )}
      {a.action && (
        <>
          <button className="link act-toggle" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'What to do'}</button>
          {open && (
            <div className="action">
              <ol>{a.action.now.map((s, i) => <li key={i}>{s}</li>)}</ol>
              <div className="esc"><span className="k">When to escalate</span>{a.action.escalate}</div>
            </div>
          )}
        </>
      )}
    </li>
  )
}

function Alerts({ alerts }) {
  return (
    <aside className="panel alerts">
      <div className="panel-head">
        <h2>Alerts &amp; predictions</h2>
        <span className="count mono">{alerts.length}</span>
      </div>
      {alerts.length === 0 && <p className="empty">All values within limits and close to each crew member's baseline.</p>}
      <ol>{alerts.map((a, i) => <AlertItem key={`${a.who}-${a.metric}-${a.kind}-${i}`} a={a} />)}</ol>
      <p className="method">
        Limits: NASA-STD-3001 (cabin) and clinical early-warning bands (vitals). Baseline: each
        astronaut's pre-flight normal. Forecast: linear trend over the last 5 min, projected 60 min ahead.
        Hazards and risks: NASA Human Research Program.
      </p>
    </aside>
  )
}

const km = n => n >= 1e6 ? `${(n / 1e6).toFixed(1)} million km` : `${Math.round(n).toLocaleString()} km`

function Earth({ e, env }) {
  if (!e) return null
  return (
    <div className="card earth">
      <div className="earth-main">
        <span className="k">Distance from Earth</span>
        <span className="earth-km">{km(e.distance_km)}</span>
        <span className="sub small">{e.note}</span>
      </div>
      <div className="earth-cell"><span className="k">Signal, one way</span><span className="mono">{e.light_one_way}</span></div>
      <div className="earth-cell"><span className="k">Question &amp; answer</span><span className="mono">{e.light_round_trip}</span></div>
      <div className="earth-cell wide"><span className="k">Time to reach Earth</span><span>{e.return_time}</span></div>
      <div className="earth-cell"><span className="k">Mission day</span><span className="mono">{e.mission_day}</span>{e.extra && <span className="sub small">{e.extra}</span>}</div>
    </div>
  )
}

function Hazards({ hazards, env }) {
  const word = { ok: 'Clear', watch: 'Watch', warning: 'Caution', critical: 'Critical' }
  return (
    <div className="hazards">
      {hazards.map(h => (
        <div key={h.key} className={`hz hz-${h.status}`} title={h.risks.join(', ') || 'No active risks'}>
          <span className="k">{h.label}</span>
          <span className="hz-state">{word[h.status]}{h.count ? <span className="mono"> · {h.count}</span> : null}</span>
          <span className="hz-note">
            {h.key === 'distance' && h.earth ? `${km(h.earth.distance_km)} · signal ${h.earth.light_one_way}`
              : h.key === 'gravity' ? env?.gravity
              : h.risks[0] || 'No active risks'}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function Dashboard({ data, error }) {
  if (!data) {
    return <div className="loading">{error ? `Waiting for the AURA server… (${error})` : 'Connecting to telemetry…'}</div>
  }
  const shipLabel = { ok: 'Nominal', warning: 'Caution', critical: 'Critical' }[data.ship.status]
  return (
    <div className="dash">
      <section className="main-col">
        <div className="section-head">
          <h2>NASA hazard watch</h2>
          <span className="sub">{data.environment?.label} · crew health score <b className="mono">{data.crew_health}</b></span>
        </div>
        <Hazards hazards={data.hazards} env={data.environment} />

        <div className="section-head">
          <h2>Crew</h2>
          <span className="sub">{data.crew.length} on board · simulated demo data · updated {new Date(data.updated).toLocaleTimeString()}</span>
        </div>
        <div className="crew-grid">
          {data.crew.map(c => <CrewCard key={c.id} c={c} />)}
        </div>

        <div className="section-head">
          <h2>Earth</h2>
          <span className="sub">{data.environment?.label} · {data.environment?.gravity}</span>
        </div>
        <Earth e={data.earth} env={data.environment} />

        <div className="section-head">
          <h2>Habitat</h2>
          <span className={`sub ship-${data.ship.status}`}>Environment · {shipLabel}</span>
        </div>
        <div className="card ship">
          <div className="metrics ship-metrics">
            {data.ship.metrics.map(m => <Metric key={m.sensor_id} m={m} />)}
          </div>
        </div>
      </section>
      <Alerts alerts={data.alerts} />
    </div>
  )
}
