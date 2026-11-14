import React, { useEffect, useState } from 'react'
import { api, getToken, setToken } from '../api.js'

function TeamLogin({ onIn }) {
  const [user, setUser] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  async function go(e) {
    e.preventDefault()
    setErr('')
    try {
      const r = await api('/api/team/login', { method: 'POST', body: { username: user.trim(), password: pw } })
      setToken('_team', r.token)
      setToken('_teamname', r.username)
      onIn(r.username)
    } catch (e2) { setErr(e2.message) }
  }
  return (
    <form className="panel login" onSubmit={go}>
      <h2>Team sign-in</h2>
      <p className="sub">For the AURA team: oversee every mission, manage team accounts and see the full activity log.</p>
      <label>Username<input value={user} onChange={e => setUser(e.target.value)} autoComplete="username" autoFocus /></label>
      <label>Password<input type="password" value={pw} onChange={e => setPw(e.target.value)} autoComplete="current-password" /></label>
      {err && <div className="err">{err}</div>}
      <button className="btn gold">Sign in</button>
    </form>
  )
}

function useLoad(path) {
  const [rows, setRows] = useState(null)
  const load = () => api(path).then(setRows).catch(() => {})
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return [rows, load]
}

function Missions() {
  const [rows, load] = useLoad('/api/team/missions')
  async function remove(m) {
    if (!window.confirm(`Delete mission ${m.code} (${m.name}) and all its data?`)) return
    await api(`/api/team/missions/${m.code}`, { method: 'DELETE' }); load()
  }
  return (
    <table>
      <thead><tr><th>Code</th><th>Name</th><th className="num">Crew</th><th>Scenario</th><th>Last active</th><th /></tr></thead>
      <tbody>
        {rows?.map(m => (
          <tr key={m.code}>
            <td className="mono"><a href={`#/m/${m.code}`}>{m.code}</a></td>
            <td>{m.name}{m.is_demo && <span className="u"> (demo)</span>}</td>
            <td className="num mono">{m.crew}</td>
            <td className="muted">{m.scenario}</td>
            <td className="muted small">{m.last_active ? new Date(m.last_active).toLocaleString() : '—'}</td>
            <td className="act">
              <a className="link" href={`#/m/${m.code}/admin`}>Admin</a>
              {!m.is_demo && <button className="link danger" onClick={() => remove(m)}>Delete</button>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Accounts({ me }) {
  const [rows, load] = useLoad('/api/team/users')
  const [form, setForm] = useState({ username: '', password: '' })
  const [msg, setMsg] = useState('')
  async function add(e) {
    e.preventDefault()
    try { await api('/api/team/users', { method: 'POST', body: form }); setForm({ username: '', password: '' }); setMsg('Account created.'); load() }
    catch (er) { setMsg(er.message) }
  }
  async function reset(u) {
    const pw = window.prompt(`New password for ${u.username} (at least 10 characters):`)
    if (!pw) return
    try { await api(`/api/team/users/${u.id}/password`, { method: 'PUT', body: { password: pw } }); setMsg(`Password changed for ${u.username}.`) }
    catch (er) { setMsg(er.message) }
  }
  async function remove(u) {
    if (!window.confirm(`Delete the account "${u.username}"?`)) return
    try { await api(`/api/team/users/${u.id}`, { method: 'DELETE' }); load() } catch (er) { setMsg(er.message) }
  }
  return (
    <div>
      {msg && <div className="note">{msg}</div>}
      <form className="editor" onSubmit={add}>
        <div className="k">Add team member</div>
        <div className="grid3">
          <label>Username<input required minLength={3} maxLength={40} pattern="[A-Za-z0-9_.\-]+" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} /></label>
          <label>Password (min 10)<input required type="password" minLength={10} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} autoComplete="new-password" /></label>
          <label>&nbsp;<button className="btn gold">Create account</button></label>
        </div>
      </form>
      <table>
        <thead><tr><th>Username</th><th>Created</th><th /></tr></thead>
        <tbody>
          {rows?.map(u => (
            <tr key={u.id}>
              <td>{u.username}{u.username === me && <span className="u"> (you)</span>}</td>
              <td className="muted small">{u.created_at ? new Date(u.created_at).toLocaleString() : '—'}</td>
              <td className="act">
                <button className="link" onClick={() => reset(u)}>Reset password</button>
                {u.username !== me && <button className="link danger" onClick={() => remove(u)}>Delete</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Log() {
  const [rows, load] = useLoad('/api/team/audit')
  return (
    <div>
      <div className="row-head"><p className="sub">Activity across every mission.</p><button className="btn" onClick={load}>Refresh</button></div>
      <table>
        <thead><tr><th>Time</th><th>Mission</th><th>User</th><th>Action</th><th>IP address</th></tr></thead>
        <tbody>
          {rows?.map((r, i) => (
            <tr key={i}>
              <td className="mono small">{new Date(r.ts).toLocaleString()}</td>
              <td className="mono small">{r.mission || '—'}</td>
              <td>{r.username || '—'}</td>
              <td className={r.action.includes('failed') ? 'txt-crit' : ''}>{r.action}</td>
              <td className="mono small muted">{r.ip}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const TABS = ['Missions', 'Team accounts', 'Activity']

export default function Team() {
  const [me, setMe] = useState(getToken('_team') ? (getToken('_teamname') || 'team') : null)
  const [tab, setTab] = useState(TABS[0])
  if (!me) return <TeamLogin onIn={setMe} />
  return (
    <div className="admin">
      <div className="admin-head">
        <div className="tabs">{TABS.map(t => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>
        <span className="sub">Team · <button className="link" onClick={() => { setToken('_team', null); setMe(null) }}>Sign out</button></span>
      </div>
      <div className="panel">
        {tab === 'Missions' && <Missions />}
        {tab === 'Team accounts' && <Accounts me={me} />}
        {tab === 'Activity' && <Log />}
      </div>
    </div>
  )
}
