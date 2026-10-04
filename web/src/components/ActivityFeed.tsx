import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Crown, GitCommit, Info, PlayCircle, User, XCircle } from 'lucide-react'
import { clock } from '../api'
import type { EventItem } from '../types'
import { Card } from './ui'

const HIDDEN = new Set(['agent_progress', 'agent_status'])

function icon(e: EventItem) {
  if (e.level === 'error' || e.type === 'task_failed') return <XCircle size={14} color="var(--critical)" />
  if (e.level === 'warning') return <AlertTriangle size={14} color="var(--warning-ink)" />
  if (e.type === 'ceo_decision' || e.type === 'plan_created' || e.type === 'phase') return <Crown size={14} color="var(--accent)" />
  if (e.type === 'control' || e.type === 'project_created') return <User size={14} />
  if (e.type === 'task_completed' && e.data?.commit) return <GitCommit size={14} color="var(--good)" />
  if (e.type === 'task_completed' || e.type === 'project_completed') return <CheckCircle2 size={14} color="var(--good)" />
  if (e.type === 'task_started') return <PlayCircle size={14} className="muted" />
  return <Info size={14} className="muted" />
}

export default function ActivityFeed({ events }: { events: EventItem[] }) {
  const [filter, setFilter] = useState<'all' | 'decisions' | 'problems'>('all')
  const visible = events.filter((e) => {
    if (HIDDEN.has(e.type)) return false
    if (filter === 'decisions') return ['ceo_decision', 'control', 'plan_created', 'phase', 'approval_requested'].includes(e.type)
    if (filter === 'problems') return e.level !== 'info'
    return true
  })
  visible.reverse() // newest first

  return (
    <Card
      title="Activity feed"
      bodyClass=""
      actions={
        <select className="select" style={{ width: 'auto', padding: '3px 6px' }} value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} aria-label="Filter activity">
          <option value="all">All</option>
          <option value="decisions">Decisions</option>
          <option value="problems">Problems</option>
        </select>
      }
    >
      <div className="feed" aria-live="polite">
        {visible.length === 0 && <div className="empty">No activity yet.</div>}
        {visible.map((e, i) => (
          <div key={e.id ?? `t${i}`} className={`feed-item ${e.level}`}>
            <span className="time">{clock(e.ts)}</span>
            <span className="icon">{icon(e)}</span>
            <span className="msg">{e.message}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}
