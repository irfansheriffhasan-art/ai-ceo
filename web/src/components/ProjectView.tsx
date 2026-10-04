import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Bug,
  CheckCheck,
  CheckCircle2,
  Download,
  ExternalLink,
  Layers,
  Pause,
  Play,
  RefreshCcw,
  Send,
  Square,
  ThumbsDown,
  ThumbsUp,
  Users,
  XCircle,
} from 'lucide-react'
import { api, duration, useEventStream } from '../api'
import type { EventItem, Snapshot } from '../types'
import ActivityFeed from './ActivityFeed'
import AgentMonitor from './AgentMonitor'
import TaskBoard from './TaskBoard'
import TaskDrawer from './TaskDrawer'
import Workspace from './Workspace'
import { ProjectStatusPill, useToast } from './ui'

const PHASE_LABELS: Record<string, string> = {
  requirements: 'Requirements',
  planning: 'Plan',
  architecture: 'Architect',
  implementation: 'Implement',
  testing: 'Test',
  review: 'Review',
  fixing: 'Fix',
  approval: 'Approve',
  deployment: 'Deploy',
}

export default function ProjectView({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const toast = useToast()
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [tokens, setTokens] = useState<Record<string, number>>({})
  const [tab, setTab] = useState<'command' | 'workspace'>('command')
  const [openTask, setOpenTask] = useState<string | null>(null)
  const [feedback, setFeedback] = useState('')
  const [busy, setBusy] = useState(false)
  const [dataVersion, setDataVersion] = useState(0)
  const refreshTimer = useRef<number | null>(null)

  const load = useCallback(async () => {
    try {
      setSnap(await api<Snapshot>(`/projects/${projectId}`))
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to load project')
    }
  }, [projectId, toast])

  useEffect(() => {
    load()
    api<EventItem[]>(`/projects/${projectId}/events?limit=300`).then(setEvents).catch(() => {})
  }, [projectId, load])

  // While work is in flight, poll gently so elapsed timers stay truthful even without events.
  useEffect(() => {
    if (!snap || snap.project.status !== 'running') return
    const id = window.setInterval(load, 4000)
    return () => window.clearInterval(id)
  }, [snap?.project.status, load])

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current)
    refreshTimer.current = window.setTimeout(() => {
      load()
      setDataVersion((v) => v + 1)
    }, 250)
  }, [load])

  useEventStream(projectId, (e) => {
    if (e.type === 'agent_progress' && e.agent) {
      setTokens((t) => ({ ...t, [e.agent as string]: Number(e.data.tokens) || 0 }))
      return
    }
    if (e.type === 'agent_status') {
      scheduleRefresh()
      return
    }
    if (e.id !== null && e.project_id === projectId) {
      setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev.slice(-499), e]))
      scheduleRefresh()
      if (['control', 'project_completed', 'approval_requested', 'ceo_decision'].includes(e.type)) onChanged()
    }
  })

  const act = async (path: string, body?: unknown, okMessage?: string) => {
    setBusy(true)
    try {
      setSnap(await api<Snapshot>(`/projects/${projectId}/${path}`, 'POST', body))
      if (okMessage) toast(okMessage, true)
      onChanged()
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setBusy(false)
    }
  }

  if (!snap) return <div className="empty">Loading project…</div>
  const p = snap.project
  const tasks = snap.tasks
  const done = tasks.filter((t) => t.status === 'completed').length
  const failed = tasks.filter((t) => t.status === 'failed').length
  const working = snap.agents.filter((a) => a.status === 'working' || a.status === 'retrying').length
  const phaseKeys = snap.phases.filter((ph) => ph !== 'done')
  const phaseIndex = p.phase === 'done' ? phaseKeys.length : phaseKeys.indexOf(p.phase)

  const sendFeedback = async () => {
    if (!feedback.trim()) return
    await act(p.status === 'awaiting_approval' || p.status === 'needs_attention' ? 'reject' : 'feedback', { message: feedback }, 'Feedback sent to the CEO')
    setFeedback('')
  }

  return (
    <div className="content">
      <div className="proj-head">
        <div className="grow">
          <div className="row wrap" style={{ marginBottom: 6 }}>
            <ProjectStatusPill status={p.status} />
            <span className="pill">Phase: {PHASE_LABELS[p.phase] ?? p.phase}</span>
            <span className="pill">Iteration {p.iteration}</span>
            {snap.running_tasks > 0 && <span className="pill info">{snap.running_tasks} task(s) running</span>}
          </div>
          <h1>{p.name}</h1>
          <div className="objective">{p.objective}</div>
        </div>
        <div className="proj-actions">
          {p.status === 'running' && (
            <button className="btn" disabled={busy} onClick={() => act('pause', undefined, 'Pausing — running tasks will finish first')}>
              <Pause size={15} /> Pause
            </button>
          )}
          {(p.status === 'paused' || p.status === 'stopped') && (
            <button className="btn primary" disabled={busy} onClick={() => act('resume')}>
              <Play size={15} /> Resume
            </button>
          )}
          {p.status === 'created' && (
            <button className="btn primary" disabled={busy} onClick={() => act('start')}>
              <Play size={15} /> Start
            </button>
          )}
          {!['completed', 'stopped'].includes(p.status) && (
            <button
              className="btn danger"
              disabled={busy}
              onClick={() => confirm('Stop the project? In-flight work is cancelled (you can resume later).') && act('stop')}
            >
              <Square size={15} /> Stop
            </button>
          )}
          {p.preview_url && (
            <a className="btn" href={p.preview_url} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={15} /> Open app
            </a>
          )}
          {!p.preview_url && ['completed', 'paused', 'stopped', 'needs_attention'].includes(p.status) && tasks.some((t) => t.kind === 'implement' && t.status === 'completed') && (
            <button className="btn" disabled={busy} onClick={() => act('preview', undefined, 'Preview started')}>
              <ExternalLink size={15} /> Start preview
            </button>
          )}
          {p.status === 'completed' && (
            <a className="btn" href={`/api/projects/${p.id}/download`}>
              <Download size={15} /> Release .zip
            </a>
          )}
        </div>
      </div>

      {p.status === 'awaiting_approval' && (
        <div className="banner warning" role="status">
          <ThumbsUp size={18} />
          <div className="grow">
            <strong>Release ready for your approval.</strong> {p.status_reason}
            {p.summary && <div className="secondary" style={{ marginTop: 4 }}>{p.summary}</div>}
          </div>
          <button className="btn primary" disabled={busy} onClick={() => act('approve', undefined, 'Approved — deploying')}>
            <CheckCheck size={15} /> Approve & deploy
          </button>
        </div>
      )}
      {p.status === 'needs_attention' && (
        <div className="banner critical" role="alert">
          <AlertTriangle size={18} />
          <div className="grow">
            <strong>The CEO escalated a decision to you.</strong> {p.status_reason}
          </div>
          <div className="row wrap">
            <button className="btn" disabled={busy} onClick={() => act('continue', { extra_iterations: 2 }, 'Granted 2 more fix iterations')}>
              <RefreshCcw size={15} /> Keep fixing
            </button>
            <button className="btn" disabled={busy} onClick={() => act('approve', undefined, 'Approved — deploying')}>
              <ThumbsUp size={15} /> Approve anyway
            </button>
          </div>
        </div>
      )}
      {p.status === 'paused' && p.status_reason && (
        <div className="banner info">
          <Pause size={18} />
          <div>{p.status_reason}</div>
        </div>
      )}
      {p.status === 'completed' && (
        <div className="banner good">
          <CheckCircle2 size={18} />
          <div className="grow">
            <strong>Delivered.</strong> {p.summary || 'All quality gates passed and the release is deployed.'}
            {p.preview_url && (
              <>
                {' '}
                Live at{' '}
                <a href={p.preview_url} target="_blank" rel="noopener noreferrer">
                  {p.preview_url}
                </a>
              </>
            )}
          </div>
        </div>
      )}

      <div className="stepper" aria-label="Development phases">
        {phaseKeys.map((ph, i) => (
          <div key={ph} className={`step ${i < phaseIndex ? 'done' : i === phaseIndex ? 'current' : ''}`}>
            <div className="track" />
            <span className="ellipsis">{PHASE_LABELS[ph] ?? ph}</span>
          </div>
        ))}
      </div>

      <div className="kpis">
        <div className="card kpi">
          <div className="label">
            <Layers size={14} /> Overall progress
          </div>
          <div className="value">{Math.round(p.progress)}%</div>
          <div className="meter" role="progressbar" aria-valuenow={Math.round(p.progress)} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${p.progress}%` }} />
          </div>
        </div>
        <div className="card kpi">
          <div className="label">
            <Users size={14} /> Active agents
          </div>
          <div className="value">
            {working}
            <span className="muted" style={{ fontSize: 15 }}> / {snap.agents.length}</span>
          </div>
          <div className="hint">{working ? 'working now' : 'idle'}</div>
        </div>
        <div className="card kpi">
          <div className="label">
            <CheckCircle2 size={14} /> Tasks completed
          </div>
          <div className="value">
            {done}
            <span className="muted" style={{ fontSize: 15 }}> / {tasks.length}</span>
          </div>
        </div>
        <div className="card kpi">
          <div className="label">
            <XCircle size={14} /> Tasks failed
          </div>
          <div className="value" style={{ color: failed ? 'var(--critical-ink)' : undefined }}>
            {failed}
          </div>
          <div className="hint">{failed ? 'needs recovery' : 'none'}</div>
        </div>
        <div className="card kpi">
          <div className="label">
            <Bug size={14} /> Open bugs
          </div>
          <div className="value">{snap.open_bugs}</div>
          <div className="hint">tracked in project memory</div>
        </div>
        <div className="card kpi">
          <div className="label">
            <Activity size={14} /> LLM work
          </div>
          <div className="value">{snap.usage.calls}</div>
          <div className="hint">
            calls · {(snap.usage.output_tokens / 1000).toFixed(1)}k tokens out · {duration(snap.usage.latency_ms / 1000)}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-body row">
          <input
            className="input"
            placeholder={
              p.status === 'completed'
                ? 'Request a change (starts a new iteration)…'
                : p.status === 'awaiting_approval' || p.status === 'needs_attention'
                  ? 'Reject with feedback — what should change?'
                  : 'Send guidance to the CEO (applied to upcoming work)…'
            }
            value={feedback}
            maxLength={2000}
            onChange={(e) => setFeedback(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendFeedback()}
          />
          <button className="btn" disabled={busy || !feedback.trim() || p.status === 'stopped'} onClick={sendFeedback}>
            {p.status === 'awaiting_approval' ? <ThumbsDown size={15} /> : <Send size={15} />}
            {p.status === 'awaiting_approval' || p.status === 'needs_attention' ? 'Reject' : 'Send'}
          </button>
        </div>
      </div>

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'command'} className={`tab ${tab === 'command' ? 'active' : ''}`} onClick={() => setTab('command')}>
          Command center
        </button>
        <button role="tab" aria-selected={tab === 'workspace'} className={`tab ${tab === 'workspace' ? 'active' : ''}`} onClick={() => setTab('workspace')}>
          Project workspace
        </button>
      </div>

      {tab === 'command' ? (
        <>
          <div className="cc-grid">
            <AgentMonitor agents={snap.agents} tasks={tasks} tokens={tokens} onOpenTask={setOpenTask} />
            <ActivityFeed events={events} />
          </div>
          <TaskBoard tasks={tasks} onOpen={setOpenTask} />
        </>
      ) : (
        <Workspace snapshot={snap} version={dataVersion} onOpenTask={setOpenTask} onChanged={load} />
      )}

      {openTask && <TaskDrawer taskId={openTask} onClose={() => setOpenTask(null)} onChanged={load} />}
    </div>
  )
}
