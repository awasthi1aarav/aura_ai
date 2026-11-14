import React, { useEffect, useState } from 'react'
import { api, getToken, getUser, setSession } from '../api.js'

const TABS = ['Crew', 'Sensors', 'Limits', 'Readings', 'Simulator', 'Connect a sensor', 'Team & access', 'Activity']
const CREW_METRICS = ['heart_rate', 'spo2', 'bp_sys', 'bp_dia', 'resp_rate', 'body_temp']

export function Login({ onIn, title = 'Mission control access', note = 'Sign in with your team account.' }) {
  const [user, setUser] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  async function go(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      const r = await api('/api/admin/login', { method: 'POST', body: { username: user.trim() || 'admin', password: pw } })
      setSession(r)
      onIn(r)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <form className="panel login" onSubmit={go}>
      <h2>{title}</h2>
      <p className="sub">{note}</p>
      <label>Username<input value={user} onChange={e => setUser(e.target.value)} autoComplete="username" autoFocus /></label>
      <label>Password<input type="password" value={pw} onChange={e => setPw(e.target.value)} autoComplete="current-password" /></label>
      {err && <div className="err">{err}</div>}
      <button className="btn gold" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
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
  const [rows, load] = useLoad('/api/admin/crew')
  const blank = { name: '', role: '', notes: '', baseline: {} }
  const [edit, setEdit] = useState(null)
  const [msg, setMsg] = useState('')
  async function save(e) {
    e.preventDefault()
    const body = { ...edit, baseline: Object.fromEntries(Object.entries(edit.baseline).filter(([, v]) => v !== '' && v !== null).map(([k, v]) => [k, Number(v)])) }
    try {
      if (edit.id) await api(`/api/admin/crew/${edit.id}`, { method: 'PUT', body })
      else await api('/api/admin/crew', { method: 'POST', body })
      setEdit(null); setMsg('Saved.'); load()
    } catch (e) { setMsg(e.message) }
  }
  async function remove(c) {
    if (!window.confirm(`Remove ${c.name} and all their sensors and readings?`)) return
    await api(`/api/admin/crew/${c.id}`, { method: 'DELETE' }); load()
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
  const [rows, load] = useLoad('/api/admin/sensors')
  const [crew] = useLoad('/api/admin/crew')
  const [add, setAdd] = useState(null)
  const [shown, setShown] = useState({})
  async function toggle(s) {
    await api(`/api/admin/sensors/${s.id}`, { method: 'PUT', body: { name: s.name, metric: s.metric, active: !s.active } }); load()
  }
  async function rotate(s) {
    if (!window.confirm('Issue a new API key? The old key stops working immediately.')) return
    await api(`/api/admin/sensors/${s.id}/rotate-key`, { method: 'POST' }); load()
  }
  async function remove(s) {
    if (!window.confirm(`Delete sensor "${s.name}" and its readings?`)) return
    await api(`/api/admin/sensors/${s.id}`, { method: 'DELETE' }); load()
  }
  async function create(e) {
    e.preventDefault()
    try {
      await api('/api/admin/sensors', { method: 'POST', body: { ...add, crew_id: add.crew_id ? Number(add.crew_id) : null } })
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
  const [rows, load] = useLoad('/api/admin/limits')
  const [draft, setDraft] = useState({})
  const [msg, setMsg] = useState('')
  const val = (r, k) => draft[r.metric]?.[k] ?? (r[k] ?? '')
  const setV = (r, k, v) => setDraft({ ...draft, [r.metric]: { ...draft[r.metric], [k]: v } })
  async function save(r) {
    const body = {}
    for (const k of ['warn_low', 'warn_high', 'crit_low', 'crit_high']) {
      const v = val(r, k); body[k] = v === '' || v === null ? null : Number(v)
    }
    await api(`/api/admin/limits/${r.metric}`, { method: 'PUT', body })
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
  const [sensors] = useLoad('/api/admin/sensors')
  const [filter, setFilter] = useState('')
  const [rows, load] = useLoad(`/api/admin/readings?limit=60${filter ? `&sensor_id=${filter}` : ''}`, [filter])
  const [form, setForm] = useState({ sensor_id: '', value: '' })
  const [msg, setMsg] = useState('')
  async function add(e) {
    e.preventDefault()
    try {
      await api('/api/admin/readings', { method: 'POST', body: { sensor_id: Number(form.sensor_id), value: Number(form.value) } })
      setMsg('Reading added.'); setForm({ ...form, value: '' }); load()
    } catch (er) { setMsg(er.message) }
  }
  async function upload(e) {
    const f = e.target.files?.[0]
    if (!f) return
    const fd = new FormData(); fd.append('file', f)
    try {
      const r = await api('/api/admin/readings/csv', { method: 'POST', form: fd })
      setMsg(`Imported ${r.imported} readings${r.errors.length ? ` · ${r.errors.length} rows skipped (${r.errors[0]})` : ''}.`); load()
    } catch (er) { setMsg(er.message) }
    e.target.value = ''
  }
  async function remove(r) {
    await api(`/api/admin/readings/${r.id}`, { method: 'DELETE' }); load()
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
  const [crew] = useLoad('/api/admin/crew')
  const [state, setState] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    api('/api/overview').then(d => setState({
      enabled: d.simulator.enabled, scenario: d.simulator.scenario,
      scenario_crew: d.simulator.scenario_crew ? Number(d.simulator.scenario_crew) : '',
    }))
  }, [])
  async function apply(next) {
    const s = { ...state, ...next }
    if (meta?.crew_scenarios.includes(s.scenario) && !s.scenario_crew) s.scenario_crew = crew?.[0]?.id
    setState(s)
    await api('/api/admin/simulator', { method: 'POST', body: { ...s, scenario_crew: s.scenario_crew || null } })
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

function Team() {
  const [rows, load] = useLoad('/api/admin/users')
  const [access, setAccess] = useState(null)
  const [form, setForm] = useState({ username: '', password: '', role: 'admin' })
  const [msg, setMsg] = useState('')
  const me = getUser()
  useEffect(() => { api('/api/admin/access').then(setAccess).catch(() => {}) }, [])
  async function add(e) {
    e.preventDefault()
    try { await api('/api/admin/users', { method: 'POST', body: form }); setForm({ username: '', password: '', role: 'admin' }); setMsg('Account created.'); load() }
    catch (er) { setMsg(er.message) }
  }
  async function reset(u) {
    const pw = window.prompt(`New password for ${u.username} (at least 10 characters):`)
    if (!pw) return
    try { await api(`/api/admin/users/${u.id}/password`, { method: 'PUT', body: { password: pw } }); setMsg(`Password changed for ${u.username}.`) }
    catch (er) { setMsg(er.message) }
  }
  async function remove(u) {
    if (!window.confirm(`Delete the account "${u.username}"?`)) return
    try { await api(`/api/admin/users/${u.id}`, { method: 'DELETE' }); load() } catch (er) { setMsg(er.message) }
  }
  async function toggle(pub) {
    await api('/api/admin/access', { method: 'POST', body: { public: pub } }); setAccess({ public: pub })
  }
  return (
    <div>
      <div className="editor">
        <div className="k">Who can view the dashboard and assistant</div>
        {access && (
          <div className="scen">
            <button className={access.public ? 'on' : ''} onClick={() => toggle(true)}>Public — anyone with the link (demo / judging)</button>
            <button className={!access.public ? 'on' : ''} onClick={() => toggle(false)}>Private — team accounts only (real mission)</button>
          </div>
        )}
        <p className="sub small">The admin panel always requires an admin account. Sensors always need their own API key.</p>
      </div>
      {msg && <div className="note">{msg}</div>}
      <form className="editor" onSubmit={add}>
        <div className="k">Add account</div>
        <div className="grid3">
          <label>Username<input required minLength={3} maxLength={40} pattern="[A-Za-z0-9_.\-]+" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} /></label>
          <label>Password (min 10)<input required type="password" minLength={10} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} autoComplete="new-password" /></label>
          <label>Role
            <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
              <option value="admin">Admin — can change everything</option>
              <option value="viewer">Viewer — dashboard and assistant only</option>
            </select>
          </label>
        </div>
        <button className="btn gold">Create account</button>
      </form>
      <table>
        <thead><tr><th>Username</th><th>Role</th><th>Created</th><th /></tr></thead>
        <tbody>
          {rows?.map(u => (
            <tr key={u.id}>
              <td>{u.username}{u.username === me?.username && <span className="u"> (you)</span>}</td>
              <td className="muted">{u.role}</td>
              <td className="muted small">{u.created_at ? new Date(u.created_at).toLocaleString() : '—'}</td>
              <td className="act">
                <button className="link" onClick={() => reset(u)}>Reset password</button>
                {u.username !== me?.username && <button className="link danger" onClick={() => remove(u)}>Delete</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Activity() {
  const [rows, load] = useLoad('/api/admin/audit')
  return (
    <div>
      <div className="row-head">
        <p className="sub">Every sign-in, failed sign-in and change made in the admin panel, with who did it and from where.</p>
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

export default function Admin() {
  const [user, setUser] = useState(getToken() ? getUser() : null)
  const [tab, setTab] = useState(TABS[0])
  const [meta, setMeta] = useState(null)
  useEffect(() => { if (user) api('/api/meta').then(setMeta).catch(() => {}) }, [user])
  useEffect(() => {
    const out = () => { if (!getToken()) setUser(null) }
    window.addEventListener('aura-auth', out)
    return () => window.removeEventListener('aura-auth', out)
  }, [])
  const signOut = () => { setSession(null); setUser(null); window.dispatchEvent(new Event('aura-auth')) }
  if (!user) return <Login onIn={r => setUser({ username: r.username, role: r.role })} />
  if (user.role !== 'admin') {
    return (
      <div className="panel login">
        <h2>Admins only</h2>
        <p className="sub">You're signed in as <strong>{user.username}</strong> (viewer). Ask an admin for access.</p>
        <button className="btn" onClick={signOut}>Sign out</button>
      </div>
    )
  }
  return (
    <div className="admin">
      <div className="admin-head">
        <div className="tabs">
          {TABS.map(t => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}
        </div>
        <span className="sub">{user.username} · <button className="link" onClick={signOut}>Sign out</button></span>
      </div>
      <div className="panel">
        {tab === 'Crew' && <Crew meta={meta} />}
        {tab === 'Sensors' && <Sensors meta={meta} />}
        {tab === 'Limits' && <Limits />}
        {tab === 'Readings' && <Readings />}
        {tab === 'Simulator' && <Simulator meta={meta} />}
        {tab === 'Connect a sensor' && <Connect />}
        {tab === 'Team & access' && <Team />}
        {tab === 'Activity' && <Activity />}
      </div>
    </div>
  )
}
