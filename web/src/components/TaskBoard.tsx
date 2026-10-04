import { RotateCw, Wrench } from 'lucide-react'
import type { Task } from '../types'
import { TASK_COLUMNS } from './ui'

const ROLE_LABEL: Record<string, string> = {
  ceo: 'CEO',
  planner: 'Planner',
  pm: 'PM',
  product: 'Product',
  architect: 'Architect',
  uiux: 'UI/UX',
  frontend: 'Frontend',
  backend: 'Backend',
  database: 'Database',
  aiml: 'AI/ML',
  security: 'Security',
  testing: 'Testing',
  reviewer: 'Review',
  devops: 'DevOps',
}

export default function TaskBoard({ tasks, onOpen }: { tasks: Task[]; onOpen: (id: string) => void }) {
  const byId = new Map(tasks.map((t) => [t.id, t]))
  return (
    <section className="card">
      <div className="card-head">
        <h3>Task board</h3>
        <div className="spacer" />
        <span className="muted small">{tasks.length} tasks</span>
      </div>
      <div className="card-body">
        <div className="board">
          {TASK_COLUMNS.map((col) => {
            const items = tasks
              .filter((t) => col.statuses.includes(t.status))
              .sort((a, b) => (col.key === 'completed' ? b.seq - a.seq : a.priority - b.priority || a.seq - b.seq))
            return (
              <div key={col.key} className="column" aria-label={`${col.label} column`}>
                <div className="column-head">
                  {col.label}
                  <span className="count">{items.length}</span>
                </div>
                {items.map((t) => {
                  const waitingOn = t.depends_on.map((d) => byId.get(d)).filter((d) => d && d.status !== 'completed' && d.status !== 'cancelled')
                  return (
                    <button key={t.id} className="task-card" onClick={() => onOpen(t.id)}>
                      <span className="title">{t.title}</span>
                      <span className="meta">
                        <span className="pill">{ROLE_LABEL[t.role] ?? t.role}</span>
                        <span>P{t.priority}</span>
                        <span>it {t.iteration}</span>
                        {t.kind === 'fix' && (
                          <span className="pill warning">
                            <Wrench size={11} /> fix
                          </span>
                        )}
                        {t.attempts > 1 && (
                          <span className="pill warning">
                            <RotateCw size={11} /> {t.attempts}/{t.max_attempts}
                          </span>
                        )}
                        {t.status === 'cancelled' && <span className="pill">skipped</span>}
                      </span>
                      {t.status === 'backlog' && waitingOn.length > 0 && (
                        <span className="muted small ellipsis">waits for: {waitingOn.map((d) => d!.title).join(', ')}</span>
                      )}
                      {t.status === 'failed' && t.error && <span className="small ellipsis" style={{ color: 'var(--critical-ink)' }}>{t.error}</span>}
                      {t.status === 'completed' && t.summary && <span className="muted small ellipsis">{t.summary}</span>}
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
