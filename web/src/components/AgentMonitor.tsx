import { AlertTriangle, CheckCircle2, Loader2, Moon, RotateCw } from 'lucide-react'
import { duration, timeAgo } from '../api'
import type { AgentInfo, Task } from '../types'
import { Card } from './ui'

const STATUS = {
  working: { icon: <Loader2 size={12} />, label: 'Working', tone: 'info' },
  retrying: { icon: <RotateCw size={12} />, label: 'Retrying', tone: 'warning' },
  error: { icon: <AlertTriangle size={12} />, label: 'Error', tone: 'critical' },
  idle: { icon: <Moon size={12} />, label: 'Idle', tone: '' },
} as const

export default function AgentMonitor({
  agents,
  tasks,
  tokens,
  onOpenTask,
}: {
  agents: AgentInfo[]
  tasks: Task[]
  tokens: Record<string, number>
  onOpenTask: (id: string) => void
}) {
  return (
    <Card title="Agent monitor" actions={<span className="muted small">{agents.length} agents</span>}>
      <div className="agents">
        {agents.map((a) => {
          const mine = tasks.filter((t) => t.role === a.role)
          const doneCount = mine.filter((t) => t.status === 'completed').length
          const failedHere = mine.filter((t) => t.status === 'failed').length
          const pct = mine.length ? Math.round((100 * doneCount) / mine.length) : 0
          const s = STATUS[a.status] ?? STATUS.idle
          const cur = a.current_task
          const liveTokens = cur ? tokens[a.role] ?? cur.tokens : 0
          const status = failedHere && a.status === 'idle' ? STATUS.error : s
          // Live activity is tracked in memory; after a restart fall back to the task history.
          const lastFinished = mine.map((t) => t.finished_at ?? '').sort().pop() || null
          const lastActive = a.last_activity ? new Date(a.last_activity * 1000).toISOString() : lastFinished
          return (
            <div key={a.role} className={`agent ${a.status}`}>
              <div className="name">
                <span className="grow ellipsis">{a.title}</span>
                <span className={`pill ${status.tone}`}>
                  {status.icon}
                  {status.label}
                </span>
              </div>
              <div className="muted small ellipsis" title={a.description}>
                {a.description}
              </div>
              <div className="task">
                {cur ? (
                  <button className="btn ghost sm" style={{ padding: 0 }} onClick={() => onOpenTask(cur.id)} title="Open task">
                    <span className="ellipsis" style={{ maxWidth: 190 }}>
                      {cur.title}
                    </span>
                  </button>
                ) : mine.length ? (
                  <span className="muted">
                    <CheckCircle2 size={12} style={{ verticalAlign: -2 }} /> {doneCount}/{mine.length} task(s) done
                  </span>
                ) : (
                  <span className="muted">No tasks in this project</span>
                )}
              </div>
              {cur ? (
                <>
                  <div className="bar indeterminate" aria-label="working">
                    <span />
                  </div>
                  <div className="muted small">
                    {duration(cur.elapsed_s)}
                    {cur.attempt > 1 ? ` · attempt ${cur.attempt}` : ''}
                    {liveTokens ? ` · ${liveTokens} tokens` : ''}
                  </div>
                </>
              ) : (
                <>
                  <div className="bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                    <span style={{ width: `${pct}%` }} />
                  </div>
                  <div className="muted small">
                    {lastActive ? `last active ${timeAgo(lastActive)}` : 'not active yet'}
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}
