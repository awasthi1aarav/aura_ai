const TOKENS_KEY = 'aura_tokens'   // { MISSIONCODE: hostToken, _team: teamToken }
const CLIENT_KEY = 'aura_client_id'
const LAST_KEY = 'aura_last_mission'
let memClient = null
let current = 'DEMO'

export function setMission(code) {
  current = (code || 'DEMO').toUpperCase()
  try { localStorage.setItem(LAST_KEY, current) } catch { /* ignore */ }
}
export function getMission() { return current }
export function lastMission() {
  try { return localStorage.getItem(LAST_KEY) || 'DEMO' } catch { return 'DEMO' }
}
export const mpath = p => `/api/m/${current}${p}`

function tokens() {
  try { return JSON.parse(sessionStorage.getItem(TOKENS_KEY) || '{}') } catch { return {} }
}
function saveTokens(t) {
  try { sessionStorage.setItem(TOKENS_KEY, JSON.stringify(t)) } catch { /* ignore */ }
}
export function setToken(scope, token) {
  const t = tokens()
  if (token) t[scope] = token; else delete t[scope]
  saveTokens(t)
}
export function getToken(scope) { return tokens()[scope] || null }
export function isHost(code = current) { return !!(getToken(code) || getToken('_team')) }

function tokenFor(path) {
  const t = tokens()
  const m = path.match(/^\/api\/m\/([A-Za-z0-9]+)\//)
  if (m) return t[m[1].toUpperCase()] || t._team || null
  if (path.startsWith('/api/team/')) return t._team || null
  return null
}

// Anonymous per-browser id: keeps each visitor's assistant conversations private.
export function clientId() {
  try {
    let id = localStorage.getItem(CLIENT_KEY)
    if (!id) { id = crypto.randomUUID(); localStorage.setItem(CLIENT_KEY, id) }
    return id
  } catch {
    memClient = memClient || (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now())
    return memClient
  }
}

export async function api(path, { method = 'GET', body, form, signal } = {}) {
  const headers = { 'X-Client-Id': clientId() }
  if (body) headers['Content-Type'] = 'application/json'
  const token = tokenFor(path)
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(path, { method, headers, signal, body: form || (body ? JSON.stringify(body) : undefined) })
  if (res.status === 401 && token) {  // session expired
    const m = path.match(/^\/api\/m\/([A-Za-z0-9]+)\//)
    setToken(m ? m[1].toUpperCase() : '_team', null)
    window.dispatchEvent(new Event('aura-auth'))
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const j = await res.json()
      msg = typeof j.detail === 'string' ? j.detail
        : (j.detail?.[0]?.msg ? `${j.detail[0].loc?.slice(-1)[0] ?? ''}: ${j.detail[0].msg}`.replace(/^: /, '') : 'Please check the form and try again.')
    } catch { /* ignore */ }
    const err = new Error(msg); err.status = res.status
    throw err
  }
  return res.json()
}

export function fmt(v, metric) {
  if (v === null || v === undefined) return '—'
  const d = { body_temp: 1, cabin_co2: 2, cabin_pressure: 1, cabin_temp: 1, sleep_hours: 1 }[metric] ?? 0
  return Number(v).toFixed(d)
}

export function sinceMission(iso) {
  if (!iso) return '—'
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
  const d = Math.floor(s / 86400)
  const hh = String(Math.floor((s % 86400) / 3600)).padStart(2, '0')
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${d}d ${hh}:${mm}:${ss}`
}
