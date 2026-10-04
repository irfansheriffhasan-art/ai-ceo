import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  CirclePause,
  Clock,
  Info,
  Loader2,
  OctagonX,
  ShieldAlert,
  XCircle,
} from 'lucide-react'
import type { ProjectStatus, TaskStatus } from '../types'

type Tone = 'good' | 'warning' | 'critical' | 'info' | 'neutral'

const PROJECT_STATUS: Record<ProjectStatus, { label: string; tone: Tone; icon: ReactNode }> = {
  created: { label: 'Created', tone: 'neutral', icon: <CircleDashed size={13} /> },
  running: { label: 'Running', tone: 'info', icon: <Loader2 size={13} className="spin" /> },
  paused: { label: 'Paused', tone: 'warning', icon: <CirclePause size={13} /> },
  awaiting_approval: { label: 'Awaiting approval', tone: 'warning', icon: <Clock size={13} /> },
  needs_attention: { label: 'Needs attention', tone: 'critical', icon: <AlertTriangle size={13} /> },
  completed: { label: 'Delivered', tone: 'good', icon: <CheckCircle2 size={13} /> },
  stopped: { label: 'Stopped', tone: 'neutral', icon: <OctagonX size={13} /> },
  failed: { label: 'Failed', tone: 'critical', icon: <XCircle size={13} /> },
}

export function ProjectStatusPill({ status }: { status: ProjectStatus }) {
  const s = PROJECT_STATUS[status] ?? PROJECT_STATUS.created
  return (
    <span className={`pill ${s.tone}`}>
      {s.icon}
      {s.label}
    </span>
  )
}

export function projectTone(status: ProjectStatus): Tone {
  return (PROJECT_STATUS[status] ?? PROJECT_STATUS.created).tone
}

export const TASK_COLUMNS: { key: string; label: string; statuses: TaskStatus[] }[] = [
  { key: 'backlog', label: 'Backlog', statuses: ['backlog'] },
  { key: 'planned', label: 'Planned', statuses: ['planned'] },
  { key: 'in_progress', label: 'In Progress', statuses: ['in_progress'] },
  { key: 'testing', label: 'Testing', statuses: ['testing'] },
  { key: 'review', label: 'Review', statuses: ['review'] },
  { key: 'completed', label: 'Completed', statuses: ['completed', 'cancelled'] },
  { key: 'failed', label: 'Failed', statuses: ['failed'] },
]

export function TaskStatusPill({ status }: { status: TaskStatus }) {
  const map: Record<TaskStatus, { tone: Tone; icon: ReactNode; label: string }> = {
    backlog: { tone: 'neutral', icon: <CircleDashed size={12} />, label: 'Backlog' },
    planned: { tone: 'neutral', icon: <Clock size={12} />, label: 'Planned' },
    in_progress: { tone: 'info', icon: <Loader2 size={12} />, label: 'In progress' },
    testing: { tone: 'info', icon: <Loader2 size={12} />, label: 'Testing' },
    review: { tone: 'info', icon: <Loader2 size={12} />, label: 'Review' },
    completed: { tone: 'good', icon: <CheckCircle2 size={12} />, label: 'Completed' },
    failed: { tone: 'critical', icon: <XCircle size={12} />, label: 'Failed' },
    cancelled: { tone: 'neutral', icon: <OctagonX size={12} />, label: 'Skipped' },
  }
  const s = map[status]
  return (
    <span className={`pill ${s.tone}`}>
      {s.icon}
      {s.label}
    </span>
  )
}

/** Severity across verifiers: tests (error/warning), security (critical..info), review (blocker..minor). */
export function SeverityPill({ severity }: { severity: string }) {
  const critical = ['critical', 'blocker', 'error']
  const serious = ['high', 'major']
  const warning = ['medium', 'warning']
  if (critical.includes(severity))
    return (
      <span className="pill critical">
        <AlertOctagon size={12} />
        {severity}
      </span>
    )
  if (serious.includes(severity))
    return (
      <span className="pill critical">
        <ShieldAlert size={12} />
        {severity}
      </span>
    )
  if (warning.includes(severity))
    return (
      <span className="pill warning">
        <AlertTriangle size={12} />
        {severity}
      </span>
    )
  return (
    <span className="pill">
      <Info size={12} />
      {severity}
    </span>
  )
}

export function PassFail({ passed, label }: { passed: boolean; label?: string }) {
  return passed ? (
    <span className="pill good">
      <CheckCircle2 size={12} />
      {label ?? 'Passed'}
    </span>
  ) : (
    <span className="pill critical">
      <XCircle size={12} />
      {label ?? 'Failed'}
    </span>
  )
}

export function Card({ title, actions, children, bodyClass = 'card-body' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; bodyClass?: string }) {
  return (
    <section className="card">
      {title !== undefined && (
        <div className="card-head">
          <h3>{title}</h3>
          <div className="spacer" />
          {actions}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

export function JsonView({ value }: { value: unknown }) {
  return <pre className="code">{JSON.stringify(value, null, 2)}</pre>
}

// ---- toasts ---------------------------------------------------------------------------------
interface Toast {
  id: number
  message: string
  ok: boolean
}
const ToastCtx = createContext<(message: string, ok?: boolean) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((message: string, ok = false) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, message, ok }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.ok ? 'ok' : ''}`}>
            {t.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export const useToast = () => useContext(ToastCtx)
