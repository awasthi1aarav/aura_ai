import React, { useEffect, useState } from 'react'
import { api, sinceMission } from './api.js'
import Dashboard from './pages/Dashboard.jsx'
import Assistant from './pages/Assistant.jsx'
import Admin from './pages/Admin.jsx'

function useHash() {
  const [hash, setHash] = useState(window.location.hash || '#/')
  useEffect(() => {
    const on = () => setHash(window.location.hash || '#/')
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return hash
}

function useOverview() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () => api('/api/overview')
      .then(d => { if (alive) { setData(d); setError(null) } })
      .catch(e => alive && setError(e.message))
    load()
    const id = setInterval(load, 4000)
    return () => { alive = false; clearInterval(id) }
  }, [])
  return { data, error }
}

function Clock({ start }) {
  const [, tick] = useState(0)
  useEffect(() => { const id = setInterval(() => tick(t => t + 1), 1000); return () => clearInterval(id) }, [])
  return <span className="mono">{sinceMission(start)}</span>
}

export default function App() {
  const hash = useHash()
  const { data, error } = useOverview()
  const [route, query] = hash.slice(1).split('?')
  const params = new URLSearchParams(query || '')
  const page = route.startsWith('/assistant') ? 'assistant' : route.startsWith('/admin') ? 'admin' : 'dashboard'

  const high = data?.crew.filter(c => c.risk === 'high').length ?? 0
  const crit = data?.alerts.filter(a => a.severity === 'critical').length ?? 0

  return (
    <div className="shell">
      <header className="top">
        <a className="brand" href="#/">
          <span className="mark" aria-hidden="true" />
          <span className="word">AURA</span>
          <span className="tag">Crew Health System</span>
        </a>
        <nav>
          <a className={page === 'dashboard' ? 'on' : ''} href="#/">Dashboard</a>
          <a className={page === 'assistant' ? 'on' : ''} href="#/assistant">Assistant</a>
          <a className={page === 'admin' ? 'on' : ''} href="#/admin">Admin</a>
        </nav>
        <div className="status">
          <div><span className="k">Mission elapsed</span><Clock start={data?.mission_start} /></div>
          <div>
            <span className="k">Link</span>
            <span className={`live ${error ? 'down' : ''}`}>{error ? 'Reconnecting' : 'Live'}</span>
          </div>
          <div>
            <span className="k">Status</span>
            <span className={crit || high ? 'txt-crit' : ''}>{!data ? '—' : crit || high ? `${crit + high} need attention` : 'Nominal'}</span>
          </div>
        </div>
      </header>

      <main>
        {page === 'dashboard' && <Dashboard data={data} error={error} />}
        {page === 'assistant' && <Assistant data={data} initialCrew={params.get('crew')} />}
        {page === 'admin' && <Admin />}
      </main>

      <footer className="foot">
        <span>AURA · NASA Space Apps Challenge 2026 · Team Orbital Five</span>
        <span>Prototype for decision support — not a medical device. Demo crew and live readings are simulated.</span>
      </footer>
    </div>
  )
}
