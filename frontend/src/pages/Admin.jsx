import React, { useEffect, useState } from 'react'
import { api, getMission, isHost, mpath, setToken } from '../api.js'

const TABS = ['Crew', 'Sensors', 'Limits', 'Readings', 'Simulator', 'Connect a sensor', 'Mission', 'Activity']
const CREW_METRICS = ['heart_rate', 'spo2', 'bp_sys', 'bp_dia', 'resp_rate', 'body_temp']

function HostLogin({ onIn, mission }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  async function go(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      const r = await api(`/api/missions/${getMission()}/login`, { method: 'POST', body: { password: pw } })
      setToken(getMission(), r.token)
      onIn()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <form className="panel login" onSubmit={go}>
      <h2>Mission admin</h2>
      <p className="sub">Enter the password for <strong>{mission?.name || getMission()}</strong>. Only this mission is affected by changes made here.</p>
      <input type="text" name="username" autoComplete="username" value={getMission()} readOnly hidden />
      <label>Mission password<input type="password" value={pw} onChange={e => setPw(e.target.value)} autoComplete="current-password" autoFocus /></label>
      {err && <div className="err">{err}</div>}
      <button className="btn gold" type="submit" disabled={busy}>{busy ? 'Checking…' : 'Unlock admin'}</button>
      <p className="sub small">Want your own sandbox? <a href="#/host">Host a mission</a>. Team member? <a href="#/team">Team sign-in</a>.</p>
    </form>
  )
}

function useLoad(path, deps = []) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api(path).then(setRows).catch(e => setErr(e.message))
  useEffect(() => { load() }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return [rows, load, err]
}

function Crew({ meta }) {
  const [rows, load] = useLoad(mpath('/admin/crew'))
  const blank = { name: '', role: '', notes: '', baseline: {} }
  const [edit, setEdit] = useState(null)
  const [msg, setMsg] = useState('')
  async function save(e) {
    e.preventDefault()
    const body = { ...edit, baseline: Object.fromEntries(Object.entries(edit.baseline).filter(([, v]) => v !== '' && v !== null).map(([k, v]) => [k, Number(v)])) }
    try {
      if (edit.id) await api(mpath(`/admin/crew/${edit.id}`), { method: 'PUT', body })
      else await api(mpath('/admin/crew'), { method: 'POST', body })
      setEdit(null); setMsg('Saved.'); load()
    } catch (e) { setMsg(e.message) }
  }
  async function remove(c) {
    if (!window.confirm(`Remove ${c.name} and all their sensors and readings?`)) return
    await api(mpath(`/admin/crew/${c.id}`), { method: 'DELETE' }); load()
  }
  return (
    <div>
      <div className="row-head">
        <p className="sub">Each crew member gets six sensors automatically. Baselines are their pre-flight normals, used to spot changes that are unusual <em>for them</em>.</p>
        <button className="btn gold" onClick={() => setEdit(blank)}>Add crew member</button>
      </div>
      {msg && <div className="note">{msg}</div>}
      {edit && (
        <form className="editor" onSubmit={save}>
          <div className="grid3">
            <label>Name<input required value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} /></label>
            <label>Role<input value={edit.role} onChange={e => setEdit({ ...edit, role: e.target.value })} /></label>
            <label>Notes<input value={edit.notes} onChange={e => setEdit({ ...edit, notes: e.target.value })} /></label>
          </div>
          <div className="k">Pre-flight baseline</div>
          <div className="grid6">
            {CREW_METRICS.map(m => (
              <label key={m}>{meta?.metrics[m]?.label} <span className="u">{meta?.metrics[m]?.unit}</span>
                <input type="number" step="any" value={edit.baseline[m] ?? ''} placeholder="default"
                  onChange={e => setEdit({ ...edit, baseline: { ...edit.baseline, [m]: e.target.value } })} />
              </label>
            ))}
          </div>
          <div className="actions">
            <button className="btn gold" type="submit">Save</button>
            <button className="btn" type="button" onClick={() => setEdit(null)}>Cancel</button>
          </div>
        </form>
      )}
      <table>
        <thead><tr><th>Name</th><th>Role</th>{CREW_METRICS.map(m => <th key={m} className="num">{meta?.metrics[m]?.label}</th>)}<th /></tr></thead>
        <tbody>
          {rows?.map(c => (
            <tr key={c.id}>
              <td>{c.name}</td><td className="muted">{c.role}</td>
              {CREW_METRICS.map(m => <td key={m} className="num mono">{c.baseline[m]}</td>)}
              <td className="act">
                <button className="link" onClick={() => setEdit({ ...c })}>Edit</button>
                <button className="link danger" onClick={() => remove(c)}>Remove</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Sensors({ meta }) {
  const [rows, load] = useLoad(mpath('/admin/sensors'))
  const [crew] = useLoad(mpath('/admin/crew'))
  const [add, setAdd] = useState(null)
  const [shown, setShown] = useState({})
  async function toggle(s) {
    await api(mpath(`/admin/sensors/${s.id}`), { method: 'PUT', body: { name: s.name, metric: s.metric, active: !s.active } }); load()
  }
  async function rotate(s) {
    if (!window.confirm('Issue a new API key? The old key stops working immediately.')) return
    await api(mpath(`/admin/sensors/${s.id}/rotate-key`), { method: 'POST' }); load()
  }
  async function remove(s) {
    if (!window.confirm(`Delete sensor "${s.name}" and its readings?`)) return
    await api(mpath(`/admin/sensors/${s.id}`), { method: 'DELETE' }); load()
  }
  async function create(e) {
    e.preventDefault()
    try {
      await api(mpath('/admin/sensors'), { method: 'POST', body: { ...add, crew_id: add.crew_id ? Number(add.crew_id) : null } })
      setAdd(null); load()
    } catch (er) { window.alert(er.message) }
  }
  const crewName = id => crew?.find(c => c.id === id)?.name ?? '—'
  return (
    <div>
      <div className="row-head">
        <p className="sub">A sensor feeds one value. Real hardware sends readings with its sensor ID and key; the simulator stands in for any sensor that has been silent for 60&nbsp;s.</p>
        <button className="btn gold" onClick={() => setAdd({ name: '', metric: 'heart_rate', crew_id: crew?.[0]?.id ?? '' })}>Add sensor</button>
      </div>
      {add && (
        <form className="editor" onSubmit={create}>
          <div className="grid3">
            <label>Name<input required value={add.name} onChange={e => setAdd({ ...add, name: e.target.value })} placeholder="e.g. Chest strap HR" /></label>
            <label>Measures
              <select value={add.metric} onChange={e => setAdd({ ...add, metric: e.target.value })}>
                {meta && Object.entries(meta.metrics).map(([k, v]) => <option key={k} value={k}>{v.label} ({v.unit})</option>)}
              </select>
            </label>
            {CREW_METRICS.includes(add.metric) && (
              <label>Crew member
                <select value={add.crew_id} onChange={e => setAdd({ ...add, crew_id: e.target.value })}>
                  {crew?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
            )}
          </div>
          <div className="actions"><button className="btn gold">Create</button><button type="button" className="btn" onClick={() => setAdd(null)}>Cancel</button></div>
        </form>
      )}
      <table>
        <thead><tr><th className="num">ID</th><th>Sensor</th><th>Measures</th><th>Attached to</th><th>Feed</th><th>API key</th><th /></tr></thead>
        <tbody>
          {rows?.map(s => {
            const live = s.last_device_at && Date.now() - new Date(s.last_device_at) < 60000
            return (
              <tr key={s.id} className={s.active ? '' : 'off'}>
                <td className="num mono">{s.id}</td>
                <td>{s.name}</td>
                <td className="muted">{meta?.metrics[s.metric]?.label}</td>
                <td className="muted">{s.subject === 'ship' ? 'Habitat' : crewName(s.crew_id)}</td>
                <td>{!s.active ? 'Disabled' : live ? <span className="txt-gold">Device</span> : 'Simulator'}</td>
                <td className="mono key">
                  {shown[s.id] ? s.api_key : '••••••••••'}
                  <button className="link" onClick={() => setShown({ ...shown, [s.id]: !shown[s.id] })}>{shown[s.id] ? 'Hide' : 'Show'}</button>
                </td>
                <td className="act">
                  <button className="link" onClick={() => toggle(s)}>{s.active ? 'Disable' : 'Enable'}</button>
                  <button className="link" onClick={() => rotate(s)}>New key</button>
                  <button className="link danger" onClick={() => remove(s)}>Delete</button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Limits() {
  const [rows, load] = useLoad(mpath('/admin/limits'))
  const [draft, setDraft] = useState({})
  const [msg, setMsg] = useState('')
  const val = (r, k) => draft[r.metric]?.[k] ?? (r[k] ?? '')
  const setV = (r, k, v) => setDraft({ ...draft, [r.metric]: { ...draft[r.metric], [k]: v } })
  async function save(r) {
    const body = {}
    for (const k of ['warn_low', 'warn_high', 'crit_low', 'crit_high']) {
      const v = val(r, k); body[k] = v === '' || v === null ? null : Number(v)
    }
    await api(mpath(`/admin/limits/${r.metric}`), { method: 'PUT', body })
    setMsg(`${r.label} limits saved.`); load()
  }
  return (
    <div>
      <p className="sub">Values beyond a warning bound raise a warning; at a critical bound, a critical alert. Leave blank for no bound.</p>
      {msg && <div className="note">{msg}</div>}
      <table>
        <thead><tr><th>Metric</th><th className="num">Crit low</th><th className="num">Warn low</th><th className="num">Warn high</th><th className="num">Crit high</th><th>Source</th><th /></tr></thead>
        <tbody>
          {rows?.map(r => (
            <tr key={r.metric}>
              <td>{r.label} <span className="u">{r.unit}</span></td>
              {['crit_low', 'warn_low', 'warn_high', 'crit_high'].map(k => (
                <td key={k} className="num"><input className="cell mono" type="number" step="any" value={val(r, k)} onChange={e => setV(r, k, e.target.value)} /></td>
              ))}
              <td className="muted small">{r.source}</td>
              <td className="act"><button className="link" onClick={() => save(r)}>Save</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Readings() {
  const [sensors] = useLoad(mpath('/admin/sensors'))
  const [filter, setFilter] = useState('')
  const [rows, load] = useLoad(mpath(`/admin/readings?limit=60${filter ? `&sensor_id=${filter}` : ''}`), [filter])
  const [form, setForm] = useState({ sensor_id: '', value: '' })
  const [msg, setMsg] = useState('')
  async function add(e) {
    e.preventDefault()
    try {
      await api(mpath('/admin/readings'), { method: 'POST', body: { sensor_id: Number(form.sensor_id), value: Number(form.value) } })
      setMsg('Reading added.'); setForm({ ...form, value: '' }); load()
    } catch (er) { setMsg(er.message) }
  }
  async function upload(e) {
    const f = e.target.files?.[0]
    if (!f) return
    const fd = new FormData(); fd.append('file', f)
    try {
      const r = await api(mpath('/admin/readings/csv'), { method: 'POST', form: fd })
      setMsg(`Imported ${r.imported} readings${r.errors.length ? ` · ${r.errors.length} rows skipped (${r.errors[0]})` : ''}.`); load()
    } catch (er) { setMsg(er.message) }
    e.target.value = ''
  }
  async function remove(r) {
    await api(mpath(`/admin/readings/${r.id}`), { method: 'DELETE' }); load()
  }
  return (
    <div>
      <div className="split">
        <form className="editor" onSubmit={add}>
          <div className="k">Manual entry</div>
          <div className="grid3">
            <label>Sensor
              <select required value={form.sensor_id} onChange={e => setForm({ ...form, sensor_id: e.target.value })}>
                <option value="">Choose…</option>
                {sensors?.map(s => <option key={s.id} value={s.id}>{s.id} · {s.name}</option>)}
              </select>
            </label>
            <label>Value<input required type="number" step="any" value={form.value} onChange={e => setForm({ ...form, value: e.target.value })} /></label>
            <label>&nbsp;<button className="btn gold">Add reading</button></label>
          </div>
        </form>
        <div className="editor">
          <div className="k">Import CSV</div>
          <p className="sub small">Columns: <span className="mono">sensor_id,value,timestamp</span> (timestamp optional, ISO-8601). Use this to load NASA datasets such as OSDR records.</p>
          <input type="file" accept=".csv,text/csv" onChange={upload} />
        </div>
      </div>
      {msg && <div className="note">{msg}</div>}
      <div className="row-head">
        <div className="k">Latest readings</div>
        <select value={filter} onChange={e => setFilter(e.target.value)}>
          <option value="">All sensors</option>
          {sensors?.map(s => <option key={s.id} value={s.id}>{s.id} · {s.name}</option>)}
        </select>
      </div>
      <table>
        <thead><tr><th>Time</th><th>Sensor</th><th className="num">Value</th><th>Source</th><th /></tr></thead>
        <tbody>
          {rows?.map(r => (
            <tr key={r.id}>
              <td className="mono small">{new Date(r.ts).toLocaleString()}</td>
              <td>{r.sensor}</td>
              <td className="num mono">{r.value}</td>
              <td className="muted">{r.source}</td>
              <td className="act"><button className="link danger" onClick={() => remove(r)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Simulator({ meta }) {
  const [crew] = useLoad(mpath('/admin/crew'))
  const [state, setState] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    api(mpath('/overview')).then(d => setState({
      enabled: d.simulator.enabled, scenario: d.simulator.scenario,
      scenario_crew: d.simulator.scenario_crew ? Number(d.simulator.scenario_crew) : '',
    }))
  }, [])
  async function apply(next) {
    const s = { ...state, ...next }
    if (meta?.crew_scenarios.includes(s.scenario) && !s.scenario_crew) s.scenario_crew = crew?.[0]?.id
    setState(s)
    await api(mpath('/admin/simulator'), { method: 'POST', body: { ...s, scenario_crew: s.scenario_crew || null } })
    setMsg(s.scenario === 'none' ? 'Normal operations.' : `Scenario started: ${meta.scenarios[s.scenario]}. Values change over the next few minutes.`)
  }
  if (!state || !meta) return null
  return (
    <div>
      <p className="sub">The simulator produces realistic readings for any sensor without a live device. Scenarios inject an event that develops gradually, so the forecast engine can predict it before it becomes critical.</p>
      {msg && <div className="note">{msg}</div>}
      <div className="editor">
        <label className="check"><input type="checkbox" checked={state.enabled} onChange={e => apply({ enabled: e.target.checked })} /> Simulator running</label>
        <div className="k">Scenario</div>
        <div className="scen">
          {Object.entries(meta.scenarios).map(([k, v]) => (
            <button key={k} className={state.scenario === k ? 'on' : ''} onClick={() => apply({ scenario: k })}>{v}</button>
          ))}
        </div>
        {meta.crew_scenarios.includes(state.scenario) && (
          <label>Affected crew member
            <select value={state.scenario_crew} onChange={e => apply({ scenario_crew: Number(e.target.value) })}>
              {crew?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        )}
      </div>
    </div>
  )
}

function Connect() {
  const origin = window.location.origin
  return (
    <div className="doc">
      <p className="sub">Any device that can make an HTTPS request can feed AURA — a wearable, an ESP32 with a pulse-oximeter or CO₂ sensor, or a spacecraft data bus gateway. Register the sensor under <em>Sensors</em>, then send its readings:</p>
      <pre className="mono">{`POST ${origin}/api/ingest
X-API-Key: <sensor API key>
Content-Type: application/json

{ "sensor_id": 5, "type": "spo2", "value": 97, "unit": "%",
  "timestamp": "2026-11-14T10:30:00Z" }`}</pre>
      <p className="sub">Several readings at once (gateway):</p>
      <pre className="mono">{`POST ${origin}/api/ingest/batch
X-API-Key: 5:<key5>,6:<key6>

{ "readings": [ { "sensor_id": 5, "value": 97 },
                { "sensor_id": 6, "value": 14 } ] }`}</pre>
      <p className="sub">Arduino / ESP32 (C++):</p>
      <pre className="mono">{`HTTPClient http;
http.begin("${origin}/api/ingest");
http.addHeader("Content-Type", "application/json");
http.addHeader("X-API-Key", SENSOR_KEY);
http.POST("{\\"sensor_id\\":5,\\"value\\":" + String(spo2) + "}");`}</pre>
      <p className="sub">Once a device reports, the simulator steps aside for that sensor automatically. Interactive API reference: <a href="/docs" target="_blank" rel="noreferrer">/docs</a></p>
    </div>
  )
}

function MissionTab() {
  const [info, setInfo] = useState(null)
  const [name, setName] = useState('')
  const [pw, setPw] = useState('')
  const [msg, setMsg] = useState('')
  useEffect(() => { api(mpath('/meta')).then(d => { setInfo(d.mission); setName(d.mission.name) }).catch(() => {}) }, [])
  const link = `${window.location.origin}/#/m/${getMission()}`
  async function save(e) {
    e.preventDefault()
    try {
      await api(mpath('/admin/mission'), { method: 'PUT', body: { name: name || null, password: pw || null } })
      setPw(''); setMsg('Saved.')
    } catch (er) { setMsg(er.message) }
  }
  async function end() {
    if (!window.confirm('End this mission? Its crew, sensors, readings and chats are deleted for everyone. This cannot be undone.')) return
    try {
      await api(mpath('/admin/mission'), { method: 'DELETE' })
      setToken(getMission(), null)
      window.location.hash = '#/m/DEMO'
    } catch (er) { setMsg(er.message) }
  }
  if (!info) return null
  return (
    <div>
      <div className="editor">
        <div className="k">Share this mission</div>
        <p className="sub">Anyone with the code or link can watch the dashboard and use the assistant. Changing anything needs the mission password.</p>
        <div className="share">
          <span className="code mono">{info.code}</span>
          <span className="mono small muted">{link}</span>
          <button className="btn" onClick={() => navigator.clipboard?.writeText(link).then(() => setMsg('Link copied.'))}>Copy link</button>
        </div>
      </div>
      {msg && <div className="note">{msg}</div>}
      <form className="editor" onSubmit={save}>
        <div className="k">Settings</div>
        <div className="grid3">
          <label>Mission name<input value={name} minLength={2} maxLength={60} onChange={e => setName(e.target.value)} /></label>
          <label>New password (optional, min 8)<input type="password" minLength={8} value={pw} onChange={e => setPw(e.target.value)} autoComplete="new-password" /></label>
          <label>&nbsp;<button className="btn gold">Save</button></label>
        </div>
      </form>
      {!info.is_demo && (
        <div className="editor danger-zone">
          <div className="k">End mission</div>
          <p className="sub">Hosted missions are also removed automatically after 7 days without visitors.</p>
          <button className="btn danger" onClick={end}>End mission and delete its data</button>
        </div>
      )}
    </div>
  )
}

function Activity() {
  const [rows, load] = useLoad(mpath('/admin/audit'))
  return (
    <div>
      <div className="row-head">
        <p className="sub">Every sign-in, failed sign-in and change made in this mission's admin, with when and from where.</p>
        <button className="btn" onClick={load}>Refresh</button>
      </div>
      <table>
        <thead><tr><th>Time</th><th>User</th><th>Action</th><th>IP address</th></tr></thead>
        <tbody>
          {rows?.map((r, i) => (
            <tr key={i}>
              <td className="mono small">{new Date(r.ts).toLocaleString()}</td>
              <td>{r.username || '—'}</td>
              <td className={r.action === 'login failed' ? 'txt-crit' : ''}>{r.action}</td>
              <td className="mono small muted">{r.ip}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Admin({ mission }) {
  const [authed, setAuthed] = useState(isHost())
  const [tab, setTab] = useState(TABS[0])
  const [meta, setMeta] = useState(null)
  useEffect(() => { if (authed) api(mpath('/meta')).then(setMeta).catch(() => {}) }, [authed])
  useEffect(() => {
    const out = () => setAuthed(isHost())
    window.addEventListener('aura-auth', out)
    return () => window.removeEventListener('aura-auth', out)
  }, [])
  const signOut = () => { setToken(getMission(), null); setAuthed(isHost()) }
  if (!authed) return <HostLogin mission={mission} onIn={() => setAuthed(true)} />
  return (
    <div className="admin">
      <div className="admin-head">
        <div className="tabs">
          {TABS.map(t => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}
        </div>
        <span className="sub">{mission?.name} · <button className="link" onClick={signOut}>Lock</button></span>
      </div>
      <div className="panel">
        {tab === 'Crew' && <Crew meta={meta} />}
        {tab === 'Sensors' && <Sensors meta={meta} />}
        {tab === 'Limits' && <Limits />}
        {tab === 'Readings' && <Readings />}
        {tab === 'Simulator' && <Simulator meta={meta} />}
        {tab === 'Connect a sensor' && <Connect />}
        {tab === 'Mission' && <MissionTab />}
        {tab === 'Activity' && <Activity />}
      </div>
    </div>
  )
}
