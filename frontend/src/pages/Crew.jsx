import React, { useEffect, useMemo, useState } from 'react'
import { api, fmt, getMission, mpath } from '../api.js'
import Chart from './Chart.jsx'

const RANK = { critical: 3, warning: 2, watch: 1, ok: 0, nodata: -1, stale: -1 }
const worst = list => list.reduce((w, s) => (RANK[s] ?? -1) > (RANK[w] ?? -1) ? s : w, 'nodata')

// Body systems: what each one does in space, which readings describe it, and the NASA HRP risk.
const SYSTEMS = [
  { key: 'brain', label: 'Brain & mind', metrics: ['mood', 'sleep_hours'], cx: 96, cy: 28, risk: 'Risk of Behavioral Changes and Psychiatric Disorders',
    hazard: 'Isolation and confinement',
    space: 'Months of isolation, confinement and shifting work schedules can disturb sleep and lower mood, which in turn affects alertness and teamwork.',
    measure: 'Log hours slept and rate your mood (1–5) in the morning check-in.' },
  { key: 'eyes', label: 'Eyes & vision', metrics: [], symptom: 'eye or vision change', cx: 109, cy: 40, risk: 'Risk of Spaceflight Associated Neuro-ocular Syndrome (SANS)',
    hazard: 'Gravity fields',
    space: 'In weightlessness, body fluids shift toward the head. This is linked to changes in the eye and vision during long missions (SANS).',
    measure: 'Report any blurred or changed vision in the check-in. The flight surgeon schedules eye exams.' },
  { key: 'lungs', label: 'Lungs & breathing', metrics: ['spo2', 'resp_rate'], cx: 86, cy: 112, risk: 'Risk of Hypoxia',
    hazard: 'Hostile/closed environment',
    space: 'The crew breathes air made and cleaned by life-support. Low oxygen or high CO₂ shows up first as faster breathing and lower blood oxygen.',
    measure: 'SpO₂ and breathing rate come from the wearable sensor; re-measure at rest if they look wrong.' },
  { key: 'heart', label: 'Heart & circulation', metrics: ['heart_rate', 'bp_sys', 'bp_dia'], cx: 112, cy: 120, risk: 'Risk of Cardiovascular Adaptations',
    hazard: 'Gravity fields',
    space: 'Without gravity pulling blood toward the legs, the heart and blood vessels adapt. Blood pressure and heart rate patterns change, especially on return to gravity.',
    measure: 'Heart rate and blood pressure from the wearable or cuff. Measure seated and at rest for a fair comparison.' },
  { key: 'blood', label: 'Blood & metabolism', metrics: ['glucose'], cx: 48, cy: 160, risk: 'Risk of Inadequate Food and Nutrition',
    hazard: 'Distance from Earth',
    space: 'Far from Earth, every meal comes from stored supplies. Blood sugar shows whether energy intake, activity and health are in balance.',
    measure: 'Finger-prick glucose meter in the morning check-in (mg/dL), before breakfast for a consistent reading.' },
  { key: 'immune', label: 'Temperature & immunity', metrics: ['body_temp'], cx: 100, cy: 166, risk: 'Risk of Altered Immune System Responses',
    hazard: 'Hostile/closed environment',
    space: 'Spaceflight can change how the immune system responds, and microbes spread easily in a closed cabin. Fever is often the first sign of infection.',
    measure: 'Body temperature from the wearable; confirm a high reading with a thermometer.' },
  { key: 'bones', label: 'Bones & muscles', metrics: [], exercise: true, cx: 80, cy: 262, risk: 'Risk of Spaceflight-Induced Bone Changes',
    hazard: 'Gravity fields',
    space: 'Without weight on the skeleton, bones and muscles lose strength. Daily resistance and aerobic exercise is the main protection.',
    measure: 'Log exercise minutes in the check-in. Report back or muscle pain.' },
]

function systemState(sys, person) {
  const all = [...(person.metrics || []), ...(person.checkin || [])]
  const items = sys.metrics.map(m => all.find(i => i.metric === m)).filter(Boolean)
  let status = worst(items.map(i => i.status))
  if (sys.symptom && person.symptoms?.includes(sys.symptom)) status = worst([status, 'warning'])
  if (sys.exercise) {
    const ex = person.tasks?.find(t => t.key === 'exercise')
    status = ex ? (ex.done ? 'ok' : 'watch') : 'nodata'
    if (person.symptoms?.some(s => s === 'back pain' || s === 'muscle pain')) status = worst([status, 'watch'])
  }
  if (sys.key === 'brain' && person.symptoms?.includes('poor sleep')) status = worst([status, 'watch'])
  return { items, status }
}

function BodyMap({ person, selected, onSelect }) {
  return (
    <svg className="body" viewBox="0 0 200 330" role="img" aria-label="Body map. Select a body system.">
      <g className="figure">
        <circle cx="100" cy="36" r="21" />
        <path d="M100 60 C93 60 91 66 91 72 C72 74 60 80 55 94 L45 150 C43 168 41 186 38 198 C36 206 44 209 47 202
                 L57 156 L63 120 L64 188 C64 200 66 214 68 230 L72 312 C72 320 85 320 85 312 L92 232 L100 212
                 L108 232 L115 312 C115 320 128 320 128 312 L132 230 C134 214 136 200 136 188 L137 120 L143 156
                 L153 202 C156 209 164 206 162 198 C159 186 157 168 155 150 L145 94 C140 80 128 74 109 72
                 C109 66 107 60 100 60 Z" />
        <path d="M78 100 Q100 108 122 100" className="faint" />
      </g>
      {SYSTEMS.map(sys => {
        const { status } = systemState(sys, person)
        return (
          <g key={sys.key} className={`spot s-${status} ${selected === sys.key ? 'sel' : ''}`}
             onClick={() => onSelect(sys.key)} role="button" tabIndex="0" aria-label={sys.label}
             onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && onSelect(sys.key)}>
            <circle cx={sys.cx} cy={sys.cy} r="13" className="halo" />
            <circle cx={sys.cx} cy={sys.cy} r="5.5" className="core" />
          </g>
        )
      })}
    </svg>
  )
}

const STATUS_WORD = { ok: 'Normal', watch: 'Watch', warning: 'Outside range', critical: 'Needs attention', nodata: 'No data', stale: 'No recent data' }

function SystemPanel({ sys, person }) {
  const { items, status } = systemState(sys, person)
  return (
    <div className="syspanel">
      <div className="sys-head">
        <h3>{sys.label}</h3>
        <span className={`pill p-${status === 'ok' ? 'low' : status === 'critical' || status === 'warning' ? 'high' : 'watch'}`}>{STATUS_WORD[status]}</span>
      </div>
      {items.length > 0 && (
        <dl className="sys-vals">
          {items.map(i => (
            <React.Fragment key={i.metric}>
              <dt>{i.label}</dt>
              <dd className={`st-${i.status}`}><span className="mono">{fmt(i.value, i.metric)}</span> {i.unit}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {sys.exercise && <p className="small">Exercise today: {person.tasks?.find(t => t.key === 'exercise')?.done ? 'target met' : 'not logged yet (target 60 min)'}</p>}
      <div className="k">In space</div>
      <p>{sys.space}</p>
      <div className="k">How to measure</div>
      <p>{sys.measure}</p>
      <div className="tags"><span className="tag-hz">{sys.hazard}</span><span className="tag-risk">{sys.risk}</span></div>
    </div>
  )
}

function CheckInForm({ person, meta, onDone }) {
  const [f, setF] = useState({ glucose: '', sleep_hours: '', mood: 0, exercise_min: '', symptoms: [], note: '' })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const toggle = s => setF({ ...f, symptoms: f.symptoms.includes(s) ? f.symptoms.filter(x => x !== s) : [...f.symptoms, s] })
  async function submit(e) {
    e.preventDefault()
    setBusy(true); setMsg('')
    const num = v => (v === '' || v === null ? null : Number(v))
    try {
      await api(mpath('/checkin'), { method: 'POST', body: {
        crew_id: person.id, glucose: num(f.glucose), sleep_hours: num(f.sleep_hours), mood: f.mood || null,
        exercise_min: num(f.exercise_min), symptoms: f.symptoms, note: f.note } })
      setMsg('Check-in saved. AURA has updated your status.')
      setF({ glucose: '', sleep_hours: '', mood: 0, exercise_min: '', symptoms: [], note: '' })
      onDone()
    } catch (er) { setMsg(er.message) } finally { setBusy(false) }
  }
  return (
    <form className="checkin" onSubmit={submit}>
      <div className="grid4">
        <label><span>Blood sugar <span className="u">mg/dL</span></span><input type="number" min="20" max="600" step="1" value={f.glucose} onChange={e => setF({ ...f, glucose: e.target.value })} placeholder="e.g. 92" /></label>
        <label><span>Sleep last night <span className="u">hours</span></span><input type="number" min="0" max="24" step="0.1" value={f.sleep_hours} onChange={e => setF({ ...f, sleep_hours: e.target.value })} placeholder="e.g. 7.5" /></label>
        <label><span>Exercise yesterday <span className="u">min</span></span><input type="number" min="0" max="600" step="5" value={f.exercise_min} onChange={e => setF({ ...f, exercise_min: e.target.value })} placeholder="e.g. 90" /></label>
        <div className="mood">
          <span className="lbl">Mood</span>
          <div className="mood-row">
            {[1, 2, 3, 4, 5].map(n => (
              <button type="button" key={n} className={f.mood === n ? 'on' : ''} onClick={() => setF({ ...f, mood: n })} aria-label={`Mood ${n} of 5`}>{n}</button>
            ))}
          </div>
          <span className="u">1 low · 5 great</span>
        </div>
      </div>
      <div className="k">Any symptoms?</div>
      <div className="chips sym">
        {(meta?.symptoms || []).map(s => (
          <button type="button" key={s} className={f.symptoms.includes(s) ? 'on' : ''} onClick={() => toggle(s)}>{s}</button>
        ))}
      </div>
      <label>Note (optional)<input maxLength={300} value={f.note} onChange={e => setF({ ...f, note: e.target.value })} placeholder="Anything else the flight surgeon should know" /></label>
      <div className="actions">
        <button className="btn gold" disabled={busy}>{busy ? 'Saving…' : 'Save check-in'}</button>
        {msg && <span className="sub">{msg}</span>}
      </div>
    </form>
  )
}

const CHART_METRICS = ['heart_rate', 'spo2', 'bp_sys', 'body_temp', 'resp_rate', 'glucose', 'sleep_hours', 'mood']

function History({ person, meta }) {
  const [metric, setMetric] = useState('heart_rate')
  const [range, setRange] = useState('24h')
  const [data, setData] = useState(null)
  const checkinMetric = ['glucose', 'sleep_hours', 'mood'].includes(metric)
  useEffect(() => {
    let alive = true
    setData(null)
    api(mpath(`/history?metric=${metric}&crew_id=${person.id}&range=${checkinMetric ? '7d' : range}`))
      .then(d => alive && setData(d.points)).catch(() => alive && setData([]))
    return () => { alive = false }
  }, [metric, range, person.id, checkinMetric])
  const spec = meta?.metrics?.[metric]
  const dec = { body_temp: 1, sleep_hours: 1 }[metric] ?? 0
  return (
    <div>
      <div className="row-head">
        <div className="scen small-scen">
          {CHART_METRICS.map(m => <button key={m} className={metric === m ? 'on' : ''} onClick={() => setMetric(m)}>{meta?.metrics?.[m]?.label || m}</button>)}
        </div>
        {!checkinMetric && (
          <div className="scen small-scen">
            {['24h', '7d'].map(r => <button key={r} className={range === r ? 'on' : ''} onClick={() => setRange(r)}>{r === '24h' ? '24 hours' : '7 days'}</button>)}
          </div>
        )}
      </div>
      {data === null ? <div className="chart-empty">Loading…</div> : <Chart points={data} limit={spec} unit={spec?.unit} decimals={dec} />}
      <p className="sub small">{checkinMetric ? 'Daily values from the self check-in, last 7 days.' : 'Hourly averages.'} Shaded band = healthy range.</p>
    </div>
  )
}

function Profile({ person, meta, reload }) {
  const [sel, setSel] = useState('heart')
  const sys = SYSTEMS.find(s => s.key === sel)
  const done = person.tasks?.filter(t => t.done).length ?? 0
  return (
    <div className="profile">
      <div className="profile-head">
        <div>
          <h2>{person.name}</h2>
          <div className="role">{person.role}</div>
        </div>
        <div className="scorebox">
          <div><span className="k">Health score</span><span className="big mono">{person.health}</span></div>
          <div><span className="k">Check-in streak</span><span className="big mono">{person.streak}<small> days</small></span></div>
          <div><span className="k">Today's routine</span><span className="big mono">{done}/{person.tasks?.length ?? 3}</span></div>
        </div>
      </div>

      <div className="profile-grid">
        <section className="panel bodypanel">
          <div className="panel-head"><h2>Body map</h2><span className="sub">Select a body system</span></div>
          <div className="body-wrap">
            <BodyMap person={person} selected={sel} onSelect={setSel} />
            {sys && <SystemPanel sys={sys} person={person} />}
          </div>
          <div className="legend">
            <span><i className="lg ok" />Normal</span><span><i className="lg watch" />Watch</span>
            <span><i className="lg warning" />Outside range</span><span><i className="lg critical" />Needs attention</span>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><h2>Today's routine</h2><span className="sub">{person.due ? 'Check-in due' : 'Checked in today'}</span></div>
          <ul className="tasks">
            {person.tasks?.map(t => (
              <li key={t.key} className={t.done ? 'done' : ''}><span className="box">{t.done ? '✓' : ''}</span>{t.label}</li>
            ))}
          </ul>
          <p className="sub small">Complete all three each day to keep your streak and score up.</p>
          <div className="panel-head mt"><h2>Daily check-in</h2></div>
          <CheckInForm person={person} meta={meta} onDone={reload} />
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h2>Trends</h2></div>
        <History person={person} meta={meta} />
      </section>
    </div>
  )
}

export default function Crew({ data, crewId }) {
  const [meta, setMeta] = useState(null)
  const [, setTick] = useState(0)
  useEffect(() => { api(mpath('/meta')).then(setMeta).catch(() => {}) }, [])
  const person = useMemo(() => data?.crew.find(c => String(c.id) === String(crewId)), [data, crewId])
  if (!data) return <div className="loading">Connecting to telemetry…</div>
  if (crewId && person) return <Profile person={person} meta={meta} reload={() => setTick(t => t + 1)} />
  return (
    <div>
      <div className="section-head"><h2>Choose your profile</h2><span className="sub">Daily check-in, body map and trends for each crew member</span></div>
      <div className="picker">
        {data.crew.map(c => (
          <a key={c.id} className={`card pick risk-${c.risk}`} href={`#/m/${getMission()}/crew/${c.id}`}>
            <h3>{c.name}</h3>
            <div className="role">{c.role}</div>
            <div className="pick-row">
              <span>Score <b className="mono">{c.health}</b></span>
              <span>Streak <b className="mono">{c.streak}</b></span>
              {c.due ? <span className="due">Check-in due</span> : <span className="ok-txt">Checked in</span>}
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}
