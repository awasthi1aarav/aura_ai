const TOKEN_KEY = 'aura_token'
const USER_KEY = 'aura_user'
const CLIENT_KEY = 'aura_client_id'
let memClient = null

export function getToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function getUser() {
  try { return JSON.parse(sessionStorage.getItem(USER_KEY) || 'null') } catch { return null }
}
export function setSession(s) {
  try {
    if (s) { sessionStorage.setItem(TOKEN_KEY, s.token); sessionStorage.setItem(USER_KEY, JSON.stringify({ username: s.username, role: s.role })) }
    else { sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(USER_KEY) }
  } catch { /* storage unavailable */ }
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
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(path, { method, headers, signal, body: form || (body ? JSON.stringify(body) : undefined) })
  if (res.status === 401 && token) {  // session expired or revoked
    setSession(null)
    window.dispatchEvent(new Event('aura-auth'))
  }
  if (!res.ok) {
    let msg = res.statusText
    try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : 'Please check the form and try again.' } catch { /* ignore */ }
    const err = new Error(msg); err.status = res.status
    throw err
  }
  return res.json()
}

export function fmt(v, metric) {
  if (v === null || v === undefined) return '—'
  const d = { body_temp: 1, cabin_co2: 2, cabin_pressure: 1, cabin_temp: 1 }[metric] ?? 0
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
