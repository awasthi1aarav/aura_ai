import React from 'react'

// Minimal line chart with the safe range shaded. points: [{t, v}]
export default function Chart({ points, limit, unit, decimals = 0, height = 260 }) {
  const W = 1200, H = height, L = 48, R = 12, T = 14, B = 28
  if (!points || points.length < 2) {
    return <div className="chart-empty">Not enough data yet — history builds up as readings arrive.</div>
  }
  const vals = points.map(p => p.v)
  const lo0 = Math.min(...vals, limit?.warn_low ?? Infinity)
  const hi0 = Math.max(...vals, limit?.warn_high ?? -Infinity)
  const pad = (hi0 - lo0) * 0.12 || 1
  const lo = lo0 - pad, hi = hi0 + pad
  const t0 = new Date(points[0].t).getTime(), t1 = new Date(points[points.length - 1].t).getTime()
  const x = t => L + ((new Date(t).getTime() - t0) / Math.max(1, t1 - t0)) * (W - L - R)
  const y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B)
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
  const ticks = [lo0, (lo0 + hi0) / 2, hi0]
  const span = t1 - t0
  const fmtT = t => {
    const d = new Date(t)
    return span > 2 * 86400000 ? d.toLocaleDateString(undefined, { weekday: 'short' })
      : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  }
  const bandLo = limit?.warn_low ?? lo, bandHi = limit?.warn_high ?? hi
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="History chart">
      {limit && (limit.warn_low != null || limit.warn_high != null) && (
        <rect x={L} width={W - L - R} y={y(Math.min(bandHi, hi))} height={Math.max(0, y(Math.max(bandLo, lo)) - y(Math.min(bandHi, hi)))} className="band" />
      )}
      {ticks.map((v, i) => (
        <g key={i}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="grid" />
          <text x={L - 6} y={y(v) + 4} className="axis" textAnchor="end">{v.toFixed(decimals)}</text>
        </g>
      ))}
      {[0, 0.5, 1].map(f => {
        const t = new Date(t0 + f * span).toISOString()
        return <text key={f} x={x(t)} y={H - 6} className="axis" textAnchor={f === 0 ? 'start' : f === 1 ? 'end' : 'middle'}>{fmtT(t)}</text>
      })}
      <path d={path} className="line" />
      {points.length <= 14 && points.map((p, i) => <circle key={i} cx={x(p.t)} cy={y(p.v)} r="3" className="dot" />)}
      <text x={W - R} y={T + 10} className="axis" textAnchor="end">{unit}</text>
    </svg>
  )
}
