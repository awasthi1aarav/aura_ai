import React, { useEffect, useRef, useState } from 'react'
import { api, fmt, mpath } from '../api.js'

const SUGGEST = [
  'How is this crew member doing right now?',
  'Why is the risk level what it is?',
  'What will happen in the next hour if nothing changes?',
  'What should we do first?',
]

function render(text) {
  // light formatting: paragraphs, bullets and **bold** — no HTML injection
  return text.split('\n').filter(l => l.trim()).map((line, i) => {
    const bullet = /^\s*[-*•]\s+/.test(line)
    const clean = line.replace(/^\s*[-*•]\s+/, '')
    const parts = clean.split(/(\*\*[^*]+\*\*)/g).map((p, j) =>
      p.startsWith('**') && p.endsWith('**') ? <strong key={j}>{p.slice(2, -2)}</strong> : <React.Fragment key={j}>{p}</React.Fragment>)
    return bullet ? <div className="li" key={i}>{parts}</div> : <p key={i}>{parts}</p>
  })
}

export default function Assistant({ data, initialCrew }) {
  const [crewId, setCrewId] = useState(initialCrew ? Number(initialCrew) : null)
  const [msgs, setMsgs] = useState([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)

  useEffect(() => { if (initialCrew) setCrewId(Number(initialCrew)) }, [initialCrew])
  useEffect(() => { if (!crewId && data?.crew?.length) setCrewId(data.crew[0].id) }, [data, crewId])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs, busy])
  useEffect(() => {
    if (!crewId) return
    let alive = true
    api(mpath(`/chat/history?crew_id=${crewId}`)).then(h => alive && setMsgs(h)).catch(() => {})
    return () => { alive = false }
  }, [crewId])

  const person = data?.crew.find(c => c.id === crewId)

  async function send(q) {
    const message = (q ?? text).trim()
    if (!message || busy) return
    setText('')
    setMsgs(m => [...m, { role: 'user', text: message }])
    setBusy(true)
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 60000)
    try {
      const r = await api(mpath('/chat'), { method: 'POST', body: { message, crew_id: crewId }, signal: ctrl.signal })
      setMsgs(m => [...m, { role: 'assistant', text: r.reply, source: r.source }])
    } catch (e) {
      const text = e.name === 'AbortError' ? "I couldn't get an answer in time. Please ask again."
        : e.status === 429 ? e.message : `I couldn't get an answer just now (${e.message}). Please ask again.`
      setMsgs(m => [...m, { role: 'assistant', text, failed: true }])
    } finally {
      clearTimeout(timer)
      setBusy(false)
    }
  }

  function pick(id) {
    if (id === crewId) return
    setMsgs([])
    setCrewId(id)
  }

  async function clearChat() {
    if (!window.confirm('Clear this conversation?')) return
    await api(mpath(`/chat/history?crew_id=${crewId}`), { method: 'DELETE' }).catch(() => {})
    setMsgs([])
  }

  return (
    <div className="assist">
      <aside className="panel roster">
        <div className="panel-head"><h2>Crew</h2></div>
        <ul>
          {data?.crew.map(c => (
            <li key={c.id}>
              <button className={c.id === crewId ? 'on' : ''} onClick={() => pick(c.id)}>
                <span className={`dot d-${c.risk}`} />
                <span className="r-name">{c.name}</span>
                <span className="r-role">{c.role}</span>
              </button>
            </li>
          ))}
        </ul>
        {person && (
          <div className="snapshot">
            <div className="k">Live snapshot</div>
            <dl>
              {[...person.metrics, ...(person.checkin || [])].map(m => (
                <React.Fragment key={m.metric}>
                  <dt>{m.label}</dt>
                  <dd className={`st-${m.status}`}><span className="mono">{fmt(m.value, m.metric)}</span> {m.unit}</dd>
                </React.Fragment>
              ))}
            </dl>
          </div>
        )}
      </aside>

      <section className="panel chat">
        <div className="panel-head">
          <h2>AURA Assistant</h2>
          <span className="sub">
            {person ? `Assessing ${person.name}` : 'Select a crew member'}
            {msgs.length > 0 && <button className="link" onClick={clearChat}>Clear history</button>}
          </span>
        </div>
        <div className="log">
          {msgs.length === 0 && !busy && (
            <div className="intro">
              <p>
                Ask about any crew member. AURA reads their live vitals, personal baseline, the cabin
                environment and every active alert or forecast before it answers.
              </p>
              <div className="chips">
                {SUGGEST.map(s => <button key={s} onClick={() => send(s)}>{s}</button>)}
              </div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="who">{m.role === 'user' ? 'You' : 'AURA'}{m.source === 'offline' && <span className="badge">offline mode</span>}</div>
              <div className="body">{m.role === 'assistant' ? <div className="fmt">{render(m.text)}</div> : m.text}</div>
            </div>
          ))}
          {busy && <div className="msg assistant"><div className="who">AURA</div><div className="body typing">Reviewing telemetry…</div></div>}
          <div ref={endRef} />
        </div>
        <form className="composer" onSubmit={e => { e.preventDefault(); send() }}>
          <input
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder={person ? `Ask about ${person.name}…` : 'Ask a question…'}
            maxLength={2000}
          />
          <button type="submit" disabled={busy || !text.trim()}>Send</button>
        </form>
        <p className="fine">AURA assesses and flags possible issues; it does not replace the flight surgeon.</p>
      </section>
    </div>
  )
}
