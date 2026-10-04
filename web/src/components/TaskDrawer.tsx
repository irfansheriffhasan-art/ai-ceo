import { useEffect, useState } from 'react'
import { RotateCw, SkipForward, UserCog, X } from 'lucide-react'
import { api, clock, duration } from '../api'
import type { EventItem, LLMCall, Task } from '../types'
import { JsonView, TaskStatusPill, useToast } from './ui'

type TaskDetail = Task & { llm_calls: LLMCall[]; events: EventItem[]; reassign_options: string[] }

export default function TaskDrawer({ taskId, onClose, onChanged }: { taskId: string; onClose: () => void; onChanged: () => void }) {
  const toast = useToast()
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [call, setCall] = useState<LLMCall | null>(null)
  const [role, setRole] = useState('')

  const load = () => api<TaskDetail>(`/tasks/${taskId}`).then((t) => {
    setTask(t)
    setRole(t.role)
  })

  useEffect(() => {
    load().catch((e) => toast(e.message))
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [taskId]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (path: string, body?: unknown) => {
    try {
      await api(`/tasks/${taskId}/${path}`, 'POST', body)
      await load()
      onChanged()
      toast('Done', true)
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Action failed')
    }
  }

  const openCall = async (id: number) => {
    try {
      setCall(await api<LLMCall>(`/llm-calls/${id}`))
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Failed to load call')
    }
  }

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Task details">
        <div className="drawer-head">
          <div className="grow">
            <div className="row wrap" style={{ marginBottom: 4 }}>
              {task && <TaskStatusPill status={task.status} />}
              {task && <span className="pill">{task.kind}</span>}
              {task && <span className="pill">iteration {task.iteration}</span>}
            </div>
            <h3 style={{ margin: 0 }}>{task?.title ?? 'Loading…'}</h3>
          </div>
          <button className="btn ghost" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        {task && (
          <div className="drawer-body">
            <dl className="kv">
              <dt>Owner</dt>
              <dd>{task.role}</dd>
              <dt>Priority</dt>
              <dd>P{task.priority}</dd>
              <dt>Attempts</dt>
              <dd>
                {task.attempts} / {task.max_attempts}
              </dd>
              <dt>Created by</dt>
              <dd>{task.created_by}</dd>
              <dt>Started</dt>
              <dd>{task.started_at ? clock(task.started_at) : '—'}</dd>
              <dt>Finished</dt>
              <dd>{task.finished_at ? clock(task.finished_at) : '—'}</dd>
            </dl>
            {task.description && (
              <div>
                <div className="section-title">Description</div>
                <div className="secondary">{task.description}</div>
              </div>
            )}
            {task.summary && (
              <div>
                <div className="section-title">Result summary</div>
                <div>{task.summary}</div>
              </div>
            )}
            {task.error && (
              <div className="banner critical">
                <div>
                  <strong>Error:</strong> {task.error}
                </div>
              </div>
            )}

            <div>
              <div className="section-title">Human controls</div>
              <div className="row wrap">
                <button className="btn" disabled={!['failed', 'cancelled'].includes(task.status)} onClick={() => act('retry')}>
                  <RotateCw size={15} /> Retry
                </button>
                <button className="btn" disabled={['completed', 'cancelled'].includes(task.status)} onClick={() => confirm('Skip this task? Tasks that depend on it will proceed without it.') && act('cancel')}>
                  <SkipForward size={15} /> Skip
                </button>
                <select className="select" style={{ width: 'auto' }} value={role} onChange={(e) => setRole(e.target.value)} aria-label="Reassign to agent">
                  {task.reassign_options.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <button
                  className="btn"
                  disabled={role === task.role || ['completed', 'in_progress', 'testing', 'review'].includes(task.status)}
                  onClick={() => act('reassign', { role })}
                >
                  <UserCog size={15} /> Reassign
                </button>
              </div>
            </div>

            {task.input && Object.keys(task.input).length > 0 && (
              <details>
                <summary className="section-title" style={{ cursor: 'pointer' }}>
                  Input
                </summary>
                <JsonView value={task.input} />
              </details>
            )}
            {task.output && Object.keys(task.output).length > 0 && (
              <details open={task.kind !== 'breakdown'}>
                <summary className="section-title" style={{ cursor: 'pointer' }}>
                  Output (agent decision summary)
                </summary>
                <JsonView value={task.output} />
              </details>
            )}

            <div>
              <div className="section-title">LLM calls ({task.llm_calls.length})</div>
              {task.llm_calls.length === 0 ? (
                <div className="muted">This agent works deterministically (no model calls).</div>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Purpose</th>
                      <th className="num">Tokens out</th>
                      <th className="num">Latency</th>
                      <th>Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {task.llm_calls.map((c) => (
                      <tr key={c.id} className="clickable" onClick={() => openCall(c.id)}>
                        <td>{c.purpose}</td>
                        <td className="num">{c.output_tokens}</td>
                        <td className="num">{duration(c.latency_ms / 1000)}</td>
                        <td>{c.ok ? <span className="pill good">ok</span> : <span className="pill critical">{c.error.slice(0, 40)}</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {call && (
                <div className="stack" style={{ marginTop: 12 }}>
                  <div className="section-title">Prompt (truncated)</div>
                  <pre className="code" style={{ maxHeight: 220 }}>{call.prompt_preview}</pre>
                  <div className="section-title">Model output</div>
                  <pre className="code" style={{ maxHeight: 320 }}>{call.response_text || '(empty)'}</pre>
                </div>
              )}
            </div>

            <div>
              <div className="section-title">Log</div>
              {task.events.map((e) => (
                <div key={e.id ?? e.ts} className={`feed-item ${e.level}`} style={{ padding: '4px 0' }}>
                  <span className="time">{clock(e.ts)}</span>
                  <span />
                  <span className="msg">{e.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </>
  )
}
