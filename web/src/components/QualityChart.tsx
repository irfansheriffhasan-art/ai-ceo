import { useEffect, useMemo, useRef, useState } from 'react'
import type { Report } from '../types'
import { Card } from './ui'

const SERIES = [
  { kind: 'test', label: 'Tests', color: 'var(--series-1)' },
  { kind: 'security', label: 'Security', color: 'var(--series-2)' },
  { kind: 'review', label: 'Code review', color: 'var(--series-3)' },
] as const

const H = 260
const M = { top: 16, right: 120, bottom: 34, left: 40 }

/** Quality score per verification gate across iterations (one shared 0–100 axis). */
export default function QualityChart({ reports }: { reports: Report[] }) {
  const wrap = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(720)
  const [hover, setHover] = useState<number | null>(null)
  const [asTable, setAsTable] = useState(false)

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(320, entry.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [asTable])

  const { iterations, values } = useMemo(() => {
    const its = [...new Set(reports.filter((r) => SERIES.some((s) => s.kind === r.kind)).map((r) => r.iteration))].sort((a, b) => a - b)
    const vals: Record<string, (number | null)[]> = {}
    for (const s of SERIES) {
      vals[s.kind] = its.map((it) => {
        const rs = reports.filter((r) => r.kind === s.kind && r.iteration === it)
        return rs.length ? rs[rs.length - 1].score : null
      })
    }
    return { iterations: its, values: vals }
  }, [reports])

  if (!iterations.length) return <div className="empty">Quality scores appear after the first verification round.</div>

  const plotW = width - M.left - M.right
  const plotH = H - M.top - M.bottom
  const x = (i: number) => M.left + (iterations.length === 1 ? plotW / 2 : (i * plotW) / (iterations.length - 1))
  const y = (v: number) => M.top + plotH - (v / 100) * plotH

  // Direct end labels, nudged apart so they never overlap.
  const ends = SERIES.map((s) => {
    const arr = values[s.kind]
    let idx = arr.length - 1
    while (idx >= 0 && arr[idx] === null) idx--
    return idx < 0 ? null : { ...s, v: arr[idx] as number, ty: y(arr[idx] as number) }
  }).filter((e): e is NonNullable<typeof e> => e !== null)
  ends.sort((a, b) => a.ty - b.ty)
  for (let i = 1; i < ends.length; i++) if (ends[i].ty - ends[i - 1].ty < 15) ends[i].ty = ends[i - 1].ty + 15

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const box = (e.currentTarget as SVGRectElement).getBoundingClientRect()
    const px = e.clientX - box.left
    let best = 0
    iterations.forEach((_, i) => {
      if (Math.abs(x(i) - M.left - px) < Math.abs(x(best) - M.left - px)) best = i
    })
    setHover(best)
  }

  return (
    <Card
      title="Quality score by iteration"
      actions={
        <button className="btn sm" onClick={() => setAsTable((t) => !t)}>
          {asTable ? 'Show chart' : 'Show table'}
        </button>
      }
    >
      <div className="legend" style={{ marginBottom: 8 }}>
        {SERIES.map((s) => (
          <span key={s.kind} className="key">
            <span className="swatch-line" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      {asTable ? (
        <table className="table">
          <thead>
            <tr>
              <th>Iteration</th>
              {SERIES.map((s) => (
                <th key={s.kind} className="num">
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {iterations.map((it, i) => (
              <tr key={it}>
                <td>{it}</td>
                {SERIES.map((s) => (
                  <td key={s.kind} className="num">
                    {values[s.kind][i] ?? '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="chart-wrap" ref={wrap}>
          <svg width={width} height={H} role="img" aria-label="Line chart of test, security and code review scores per iteration">
            {[0, 25, 50, 75, 100].map((t) => (
              <g key={t}>
                <line x1={M.left} x2={M.left + plotW} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--baseline)' : 'var(--grid)'} strokeWidth={1} />
                <text x={M.left - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--text-muted)" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {t}
                </text>
              </g>
            ))}
            {iterations.map((it, i) => (
              <text key={it} x={x(i)} y={H - 12} textAnchor="middle" fontSize={11} fill="var(--text-muted)">
                Iteration {it}
              </text>
            ))}
            {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + plotH} stroke="var(--baseline)" strokeWidth={1} />}
            {SERIES.map((s) => {
              const pts = values[s.kind].map((v, i) => (v === null ? null : [x(i), y(v)] as const)).filter((p): p is readonly [number, number] => p !== null)
              return (
                <g key={s.kind}>
                  {pts.length > 1 && (
                    <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke={s.color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
                  )}
                  {pts.map(([px, py], i) => (
                    <circle key={i} cx={px} cy={py} r={4} fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
                  ))}
                </g>
              )
            })}
            {ends.map((e) => (
              <g key={e.kind}>
                <rect x={M.left + plotW + 10} y={e.ty - 5} width={10} height={3} rx={1.5} fill={e.color} />
                <text x={M.left + plotW + 24} y={e.ty} fontSize={11.5} fill="var(--text-secondary)" dominantBaseline="middle">
                  {e.label} {Math.round(e.v)}
                </text>
              </g>
            ))}
            <rect x={M.left} y={M.top} width={plotW} height={plotH} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
          </svg>
          {hover !== null && (
            <div className="chart-tooltip" style={{ left: Math.min(x(hover) + 12, width - 170), top: M.top }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Iteration {iterations[hover]}</div>
              {SERIES.map((s) => (
                <div key={s.kind} className="row" style={{ gap: 6 }}>
                  <span className="swatch-line" style={{ background: s.color }} />
                  <span className="grow">{s.label}</span>
                  <strong style={{ fontVariantNumeric: 'tabular-nums' }}>{values[s.kind][hover] ?? '—'}</strong>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <p className="muted small" style={{ marginBottom: 0 }}>
        Tests = share of checks passed (static, load, acceptance scenarios, API). Security = 100 minus weighted findings. Review = reviewer score × 10.
      </p>
    </Card>
  )
}
