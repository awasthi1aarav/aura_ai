import React, { useState } from 'react'
import { api, setToken } from '../api.js'

export const ENVS = [['spacecraft', 'Deep-space spacecraft (transit)'], ['station', 'Space station (low Earth orbit)'], ['lunar_base', 'Lunar surface base'], ['lunar_rover', 'Pressurised lunar rover'], ['mars_base', 'Mars surface base']]

export default function Host() {
  const [form, setForm] = useState({ name: '', password: '', confirm: '', demo_crew: true, environment: 'spacecraft' })
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const [joinErr, setJoinErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [made, setMade] = useState(null)
  const [rest, setRest] = useState({ name: '', password: '', file: null })
  const [restErr, setRestErr] = useState('')

  async function restore(e) {
    e.preventDefault()
    setRestErr('')
    if (!rest.file) { setRestErr('Choose a backup file.'); return }
    setBusy(true)
    const fd = new FormData()
    fd.append('file', rest.file); fd.append('name', rest.name.trim()); fd.append('password', rest.password)
    try {
      const r = await api('/api/missions/restore', { method: 'POST', form: fd })
      setToken(r.code, r.token)
      setMade({ ...r, restoredNote: `Restored ${r.restored.crew} crew, ${r.restored.checkins} check-ins and ${r.restored.history_days} days of vitals history.` })
    } catch (e2) { setRestErr(e2.message) } finally { setBusy(false) }
  }

  async function host(e) {
    e.preventDefault()
    setErr('')
    if (form.password !== form.confirm) { setErr('Passwords do not match.'); return }
    setBusy(true)
    try {
      const r = await api('/api/missions', { method: 'POST', body: { name: form.name.trim(), password: form.password, demo_crew: form.demo_crew, environment: form.environment } })
      setToken(r.code, r.token)
      setMade(r)
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }

  async function join(e) {
    e.preventDefault()
    setJoinErr('')
    const c = code.trim().toUpperCase().replace(/[^A-Z0-9]/g, '')
    if (!c) return
    try {
      await api(`/api/missions/${c}`)
      window.location.hash = `#/m/${c}`
    } catch (e2) { setJoinErr(e2.status === 404 ? 'No mission with that code.' : e2.message) }
  }

  if (made) {
    const link = `${window.location.origin}/#/m/${made.code}`
    return (
      <div className="panel login wide">
        <h2>{made.name} is live</h2>
        {made.restoredNote && <div className="note">{made.restoredNote}</div>}
        <p className="sub">Share the code or link with your crew. Anyone with it can watch; only people with the password can change things.</p>
        <div className="bigcode mono">{made.code}</div>
        <div className="share">
          <span className="mono small muted">{link}</span>
          <button className="btn" onClick={() => navigator.clipboard?.writeText(link)}>Copy link</button>
        </div>
        <p className="sub small">Keep the password safe — it can't be recovered. Missions with no visitors for 90 days are removed; download a backup from Admin → Mission to keep data longer.</p>
        <a className="btn gold" href={`#/m/${made.code}`}>Open mission</a>
      </div>
    )
  }

  return (
    <div className="hostjoin">
      <form className="panel" onSubmit={host}>
        <h2>Host a mission</h2>
        <p className="sub">Your own private copy of AURA: crew, sensors, limits and scenarios that only your mission sees.</p>
        <label>Mission name<input required minLength={2} maxLength={60} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="e.g. Artemis Team 3" /></label>
        <label>Environment
          <select value={form.environment} onChange={e => setForm({ ...form, environment: e.target.value })}>
            {ENVS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>Mission password (min 8)<input required type="password" minLength={8} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} autoComplete="new-password" /></label>
        <label>Confirm password<input required type="password" minLength={8} value={form.confirm} onChange={e => setForm({ ...form, confirm: e.target.value })} autoComplete="new-password" /></label>
        <label className="check"><input type="checkbox" checked={form.demo_crew} onChange={e => setForm({ ...form, demo_crew: e.target.checked })} /> Start with the 4 demo crew members</label>
        {err && <div className="err">{err}</div>}
        <button className="btn gold" disabled={busy}>{busy ? 'Creating…' : 'Host mission'}</button>
      </form>
      <form className="panel" onSubmit={join}>
        <h2>Join a mission</h2>
        <p className="sub">Enter the code your mission host shared with you.</p>
        <label>Mission code<input className="mono codein" value={code} onChange={e => setCode(e.target.value)} placeholder="K7Q2PX" maxLength={12} /></label>
        {joinErr && <div className="err">{joinErr}</div>}
        <button className="btn gold">Join</button>
        <p className="sub small">Or explore the shared <a href="#/m/DEMO">Demo mission</a>.</p>
      </form>
      <form className="panel restore" onSubmit={restore}>
        <h2>Restore from backup</h2>
        <p className="sub">Bring back a mission from a backup file downloaded in Admin → Mission. It becomes a new mission with a new code.</p>
        <label>Backup file (.json)<input type="file" accept=".json,application/json" onChange={e => setRest({ ...rest, file: e.target.files?.[0] || null })} /></label>
        <label>Mission name<input required minLength={2} maxLength={60} value={rest.name} onChange={e => setRest({ ...rest, name: e.target.value })} /></label>
        <label>New mission password (min 8)<input required type="password" minLength={8} value={rest.password} onChange={e => setRest({ ...rest, password: e.target.value })} autoComplete="new-password" /></label>
        {restErr && <div className="err">{restErr}</div>}
        <button className="btn gold" disabled={busy}>{busy ? 'Restoring…' : 'Restore mission'}</button>
      </form>
    </div>
  )
}
