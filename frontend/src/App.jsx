import React, { useEffect, useState } from 'react'
import { api, isHost, lastMission, mpath, setMission, sinceMission } from './api.js'
import Dashboard from './pages/Dashboard.jsx'
import Assistant from './pages/Assistant.jsx'
import Admin from './pages/Admin.jsx'
import Host from './pages/Host.jsx'
import Team from './pages/Team.jsx'
import Crew from './pages/Crew.jsx'

function useHash() {
  const [hash, setHash] = useState(window.location.hash || '#/')
  useEffect(() => {
    const on = () => setHash(window.location.hash || '#/')
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return hash
}

// #/m/CODE[/assistant|/admin][?crew=1]   #/host   #/team
function parse(hash) {
  const [route, query] = hash.slice(1).split('?')
  const parts = route.split('/').filter(Boolean)
  const params = new URLSearchParams(query || '')
  if (parts[0] === 'host' || parts[0] === 'join') return { page: 'host', params }
  if (parts[0] === 'team') return { page: 'team', params }
  if (parts[0] === 'm' && parts[1]) {
    const sub = ['assistant', 'admin', 'crew'].includes(parts[2]) ? parts[2] : 'dashboard'
    return { page: sub, code: parts[1].toUpperCase().replace(/[^A-Z0-9]/g, ''), crewId: parts[3], params }
  }
  return { page: 'redirect', params }
}

function useOverview(code) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [missing, setMissing] = useState(false)
  useEffect(() => {
    if (!code) return
    let alive = true
    setData(null); setError(null); setMissing(false)
    const load = () => api(mpath('/overview'))
      .then(d => { if (alive) { setData(d); setError(null) } })
      .catch(e => { if (!alive) return; if (e.status === 404) setMissing(true); else setError(e.message) })
    load()
    const id = setInterval(load, 4000)
    return () => { alive = false; clearInterval(id) }
  }, [code])
  return { data, error, missing }
}

function Clock({ start }) {
  const [, tick] = useState(0)
  useEffect(() => { const id = setInterval(() => tick(t => t + 1), 1000); return () => clearInterval(id) }, [])
  return <span className="mono">{sinceMission(start)}</span>
}

export default function App() {
  const hash = useHash()
  const route = parse(hash)
  if (route.code) setMission(route.code)
  useEffect(() => {
    if (route.page === 'redirect') window.location.replace(`#/m/${lastMission()}`)
  }, [route.page])
  const code = route.code
  const { data, error, missing } = useOverview(code)

  const high = data?.crew.filter(c => c.risk === 'high').length ?? 0
  const crit = data?.alerts.filter(a => a.severity === 'critical').length ?? 0
  const inMission = !!code
  const base = `#/m/${code}`

  return (
    <div className="shell">
      <header className="top">
        <a className="brand" href={inMission ? base : '#/'}>
          <span className="mark" aria-hidden="true" />
          <span className="word">AURA</span>
          <span className="tag">Crew Health System</span>
        </a>
        <nav>
          {inMission ? (
            <>
              <a className={route.page === 'dashboard' ? 'on' : ''} href={base}>Dashboard</a>
              <a className={route.page === 'crew' ? 'on' : ''} href={`${base}/crew`}>Check-in</a>
              <a className={route.page === 'assistant' ? 'on' : ''} href={`${base}/assistant`}>Assistant</a>
              <a className={route.page === 'admin' ? 'on' : ''} href={`${base}/admin`}>Admin</a>
            </>
          ) : (
            <a href={`#/m/${lastMission()}`}>Back to mission</a>
          )}
          <a className={route.page === 'host' ? 'on' : ''} href="#/host">Host / Join</a>
        </nav>
        <div className="status">
          {inMission && (
            <>
              <div className="mission-chip">
                <span className="k">Mission{isHost(code) ? ' · admin' : ''}</span>
                <span>{data?.mission?.name || code} <span className="mono code-sm">{code}</span></span>
              </div>
              <div><span className="k">Elapsed</span><Clock start={data?.mission_start} /></div>
              <div>
                <span className="k">Status</span>
                <span className={crit || high ? 'txt-crit' : ''}>{!data ? '—' : crit || high ? `${crit + high} need attention` : 'Nominal'}</span>
              </div>
            </>
          )}
          <div><span className="k">Link</span><span className={`live ${error ? 'down' : ''}`}>{error ? 'Reconnecting' : 'Live'}</span></div>
        </div>
      </header>

      <main>
        {route.page === 'host' && <Host />}
        {route.page === 'team' && <Team />}
        {inMission && missing && (
          <div className="panel login">
            <h2>Mission not found</h2>
            <p className="sub">There's no mission with the code <span className="mono">{code}</span>. It may have ended.</p>
            <a className="btn gold" href="#/host">Host or join a mission</a>
          </div>
        )}
        {inMission && !missing && (
          <React.Fragment key={code}>
            {route.page === 'dashboard' && <Dashboard data={data} error={error} />}
            {route.page === 'crew' && <Crew data={data} crewId={route.crewId} />}
            {route.page === 'assistant' && <Assistant data={data} initialCrew={route.params.get('crew')} />}
            {route.page === 'admin' && <Admin mission={data?.mission} />}
          </React.Fragment>
        )}
      </main>
    </div>
  )
}
