const TOKEN_KEY = 'aura_admin_token'

export function getToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function setToken(t) {
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ }
}

export async function api(path, { method = 'GET', body, form, auth = false } = {}) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (auth) headers['Authorization'] = `Bearer ${getToken()}`
  const res = await fetch(path, { method, headers, body: form || (body ? JSON.stringify(body) : undefined) })
  if (res.status === 401 && auth) {
    setToken(null)
    window.dispatchEvent(new Event('aura-logout'))
  }
  if (!res.ok) {
    let msg = res.statusText
    try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* ignore */ }
    throw new Error(msg)
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
