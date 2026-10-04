import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  Code2,
  Download,
  ExternalLink,
  Image as ImageIcon,
  Loader2,
  Pause,
  Play,
  RefreshCcw,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  TestTube2,
  ThumbsUp,
  Users,
  Wand2,
} from 'lucide-react'
import { api, duration, timeAgo, useEventStream } from '../api'
import type { EventItem, Project, Report, Snapshot, SystemStatus } from '../types'
import { ProjectStatusPill, useToast } from './ui'

const EXAMPLES = [
  { label: 'Password generator', prompt: 'A password generator with options for length, uppercase letters, numbers and symbols, and a copy button' },
  { label: 'Habit tracker', prompt: 'A habit tracker where I can add daily habits, tick them off each day and see my current streak for each habit' },
  { label: 'Expense splitter', prompt: 'A trip expense splitter: add people and expenses, and see who owes whom' },
  { label: 'Notes with API', prompt: 'A notes app with a REST API and SQLite database to create, list and delete notes' },
  { label: 'Pomodoro timer', prompt: 'A pomodoro timer with 25/5 minute cycles, start/pause/reset and a count of completed sessions' },
]

// ---- routing helpers ----------------------------------------------------------------------------------
function currentApp(): string | null {
  return new URLSearchParams(location.search).get('app')
}

export default function Studio({ system, onOpenCommand }: { system: SystemStatus | null; onOpenCommand: (pid: string) => void }) {
  const [appId, setAppId] = useState<string | null>(currentApp)

  useEffect(() => {
    const onPop = () => setAppId(currentApp())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const open = (id: string | null) => {
    const url = new URL(location.href)
    url.search = ''
    if (id) url.searchParams.set('app', id)
    history.pushState(null, '', url)
    setAppId(id)
    window.scrollTo(0, 0)
  }

  return appId ? (
    <StudioBuild key={appId} projectId={appId} onBack={() => open(null)} onOpenCommand={onOpenCommand} />
  ) : (
    <StudioHome system={system} onOpen={open} />
  )
}

// ---- home: prompt + gallery ----------------------------------------------------------------------------
function StudioHome({ system, onOpen }: { system: SystemStatus | null; onOpen: (id: string) => void }) {
  const toast = useToast()
  const [prompt, setPrompt] = useState('')
  const [appType, setAppType] = useState<'auto' | 'static_web' | 'web_with_backend'>('auto')
  const [approval, setApproval] = useState(false)
  const [busy, setBusy] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])

  useEffect(() => {
    api<Project[]>('/projects').then(setProjects).catch(() => {})
  }, [])

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    if (prompt.trim().length < 5) return
    setBusy(true)
    try {
      const snap = await api<Snapshot>('/projects', 'POST', {
        objective: prompt.trim(),
        app_type: appType,
        require_approval: approval,
        auto_start: true,
      })
      onOpen(snap.project.id)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not start the build')
    } finally {
      setBusy(false)
    }
  }

  const demo = system?.llm.provider === 'mock'
  return (
    <div className="studio">
      <section className="hero">
        <div className="hero-badge">
          <Users size={14} /> 14 AI agents · plan → code → test in a real browser → fix → ship
        </div>
        <h1>
          Describe an app.
          <br />
          <span className="hero-accent">Your AI software company builds it.</span>
        </h1>
        <p className="hero-sub">
          A CEO, product manager, architect, designer, developers, QA, security and code reviewers work together, test the
          result in a real browser, fix what fails and hand you a working app.
        </p>

        {system && !system.llm.ok && (
          <div className="banner critical hero-banner">
            <div>
              <strong>No AI model is ready.</strong> {system.llm.detail}. Install{' '}
              <a href="https://ollama.com" target="_blank" rel="noopener noreferrer">
                Ollama
              </a>{' '}
              and run <code>ollama pull llama3.1:8b</code>, or restart in demo mode: <code>python main.py --provider mock serve</code>
            </div>
          </div>
        )}
        {demo && (
          <div className="banner info hero-banner">
            <div>
              <strong>Demo mode.</strong> The offline demo model always builds a sample app (a task tracker, or a notes API when
              you ask for a backend). Connect Ollama or Claude to build what you describe.
            </div>
          </div>
        )}

        <form className="prompt-box" onSubmit={submit}>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit()
            }}
            placeholder="e.g. A recipe box where I can save recipes with ingredients and search them…"
            aria-label="Describe the app you want"
            maxLength={4000}
            rows={4}
            autoFocus
          />
          <div className="prompt-actions">
            <select className="select compact" value={appType} onChange={(e) => setAppType(e.target.value as typeof appType)} aria-label="App type">
              <option value="auto">Auto: AI picks the app type</option>
              <option value="static_web">Browser-only app</option>
              <option value="web_with_backend">App + API + database</option>
            </select>
            <label className="check small">
              <input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)} />
              Ask me before release
            </label>
            <div className="spacer" />
            <span className="muted small hide-mobile">Ctrl + Enter</span>
            <button className="btn primary big" disabled={busy || prompt.trim().length < 5}>
              {busy ? <Loader2 size={17} className="spin" /> : <Wand2 size={17} />} {busy ? 'Starting…' : 'Build it'}
            </button>
          </div>
        </form>
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button key={ex.label} type="button" className="chip" onClick={() => setPrompt(ex.prompt)}>
              <Sparkles size={13} /> {ex.label}
            </button>
          ))}
        </div>
        {system && system.llm.provider === 'ollama' && system.llm.ok && (
          <p className="muted small" style={{ marginTop: 14 }}>
            Running locally on {system.llm.model} — a build usually takes 10–20 minutes. You can close this tab and come back.
          </p>
        )}
      </section>

      {projects.length > 0 && (
        <section className="gallery-section">
          <h2>Your apps</h2>
          <div className="gallery">
            {projects.map((p) => (
              <button key={p.id} className="app-card" onClick={() => onOpen(p.id)}>
                <Cover projectId={p.id} version={p.updated_at} />
                <div className="app-card-body">
                  <div className="ellipsis" style={{ fontWeight: 600 }}>
                    {p.name}
                  </div>
                  <div className="row" style={{ marginTop: 6 }}>
                    <ProjectStatusPill status={p.status} />
                    <span className="muted small">{timeAgo(p.created_at)}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Cover({ projectId, version }: { projectId: string; version: string }) {
  const [failed, setFailed] = useState(false)
  if (failed)
    return (
      <div className="cover placeholder">
        <ImageIcon size={26} />
      </div>
    )
  return (
    <img
      className="cover"
      src={`/api/projects/${projectId}/cover?v=${encodeURIComponent(version)}`}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}

// ---- live code while the team is still building -------------------------------------------------------------
function LiveCode({ projectId, files }: { projectId: string; files: string[] }) {
  const latest = files[files.length - 1]
  const [path, setPath] = useState(latest)
  const [follow, setFollow] = useState(true)
  const [content, setContent] = useState('')

  useEffect(() => {
    if (follow) setPath(latest)
  }, [latest, follow])

  useEffect(() => {
    api<{ content: string }>(`/projects/${projectId}/files/content?path=${encodeURIComponent(path)}`)
      .then((r) => setContent(r.content))
      .catch(() => setContent(''))
  }, [projectId, path, files.length])

  return (
    <div className="live-code">
      <div className="live-tabs" role="tablist" aria-label="Files written so far">
        {files.map((f) => (
          <button
            key={f}
            role="tab"
            aria-selected={f === path}
            className={`live-tab ${f === path ? 'active' : ''}`}
            onClick={() => {
              setPath(f)
              setFollow(f === latest)
            }}
          >
            {f}
          </button>
        ))}
        <span className="spacer" />
        <span className="muted small live-note">
          <Loader2 size={12} className="spin" /> files appear as the team writes them
        </span>
      </div>
      <pre className="live-pre">{content}</pre>
    </div>
  )
}

// ---- build view ---------------------------------------------------------------------------------------------
const STEPS = [
  { label: 'Understanding your idea', phases: ['requirements'] },
  { label: 'Planning the work', phases: ['planning'] },
  { label: 'Designing architecture & UI', phases: ['architecture'] },
  { label: 'Writing the code', phases: ['implementation'] },
  { label: 'Testing in a real browser', phases: ['testing', 'review'] },
  { label: 'Fixing issues', phases: ['fixing'] },
  { label: 'Final review & release', phases: ['approval', 'deployment'] },
]

const FRIENDLY_EVENTS = new Set([
  'plan_created',
  'task_completed',
  'ceo_decision',
  'approval_requested',
  'project_completed',
  'task_failed',
  'control',
])

function StudioBuild({ projectId, onBack, onOpenCommand }: { projectId: string; onBack: () => void; onOpenCommand: (pid: string) => void }) {
  const toast = useToast()
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const [reports, setReports] = useState<Report[]>([])
  const [events, setEvents] = useState<EventItem[]>([])
  const [tokens, setTokens] = useState<Record<string, number>>({})
  const [feedback, setFeedback] = useState('')
  const [busy, setBusy] = useState(false)
  const [frameKey, setFrameKey] = useState(0)
  const previewRequested = useRef(false)
  const timer = useRef<number | null>(null)

  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([api<Snapshot>(`/projects/${projectId}`), api<Report[]>(`/projects/${projectId}/reports`)])
      setSnap(s)
      setReports(r)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not load this app')
    }
  }, [projectId, toast])

  useEffect(() => {
    load()
    api<EventItem[]>(`/projects/${projectId}/events?limit=300`).then(setEvents).catch(() => {})
  }, [projectId, load])

  useEffect(() => {
    if (!snap || snap.project.status !== 'running') return
    const id = window.setInterval(load, 4000)
    return () => window.clearInterval(id)
  }, [snap?.project.status, load])

  useEventStream(projectId, (e) => {
    if (e.type === 'agent_progress' && e.agent) {
      setTokens((t) => ({ ...t, [e.agent as string]: Number(e.data.tokens) || 0 }))
      return
    }
    if (e.id !== null && e.project_id === projectId) setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev.slice(-499), e]))
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(load, 300)
  })

  // A delivered app should always be clickable: (re)start its preview if it isn't running.
  useEffect(() => {
    if (snap?.project.status === 'completed' && !snap.project.preview_url && !previewRequested.current) {
      previewRequested.current = true
      api<Snapshot>(`/projects/${projectId}/preview`, 'POST').then(setSnap).catch(() => {})
    }
  }, [snap, projectId])

  const act = async (path: string, body?: unknown, ok?: string) => {
    setBusy(true)
    try {
      setSnap(await api<Snapshot>(`/projects/${projectId}/${path}`, 'POST', body))
      if (ok) toast(ok, true)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setBusy(false)
    }
  }

  if (!snap) return <div className="empty">Loading…</div>
  const p = snap.project
  const working = snap.agents.filter((a) => a.current_task)
  const stepIndex = p.phase === 'done' ? STEPS.length : Math.max(0, STEPS.findIndex((s) => s.phases.includes(p.phase)))
  const latest = (kind: string) => [...reports].reverse().find((r) => r.kind === kind)
  const test = latest('test')
  const security = latest('security')
  const review = latest('review')
  const scenarios = (test?.details?.scenarios ?? []).filter((s: { defect?: string }) => s.defect !== 'test')
  const passedScenarios = scenarios.filter((s: { passed: boolean }) => s.passed).length
  const friendly = events.filter((e) => FRIENDLY_EVENTS.has(e.type)).slice(-12).reverse()
  const screenshot = test?.details?.screenshot ? `/api/projects/${projectId}/artifacts/${test.details.screenshot}` : null
  // Files in the order the agents wrote them (from commit events), most recent last.
  const writtenFiles: string[] = []
  for (const e of events) {
    const files = e.type === 'task_completed' ? (e.data?.files as string[] | undefined) : undefined
    for (const f of files ?? []) {
      const i = writtenFiles.indexOf(f)
      if (i >= 0) writtenFiles.splice(i, 1)
      writtenFiles.push(f)
    }
  }
  const decisionNeeded = p.status === 'awaiting_approval' || p.status === 'needs_attention'

  const sendFeedback = async () => {
    if (!feedback.trim()) return
    const path = decisionNeeded ? 'reject' : 'feedback'
    await act(path, { message: feedback.trim() }, p.status === 'completed' || decisionNeeded ? 'Change request sent — the team is on it' : 'Guidance sent to the CEO')
    setFeedback('')
    previewRequested.current = false
  }

  return (
    <div className="studio-build">
      <div className="build-head">
        <button className="btn ghost" onClick={onBack}>
          <ArrowLeft size={16} /> All apps
        </button>
        <div className="grow">
          <div className="row wrap">
            <h1 className="build-title">{p.name}</h1>
            <ProjectStatusPill status={p.status} />
            {p.iteration > 1 && <span className="pill">round {p.iteration}</span>}
          </div>
          <div className="secondary small ellipsis" title={p.objective}>
            “{p.objective}”
          </div>
        </div>
        <div className="row wrap">
          {p.status === 'running' && (
            <button className="btn" disabled={busy} onClick={() => act('pause', undefined, 'Pausing after the current step')}>
              <Pause size={15} /> Pause
            </button>
          )}
          {(p.status === 'paused' || p.status === 'stopped') && (
            <button className="btn primary" disabled={busy} onClick={() => act('resume')}>
              <Play size={15} /> Resume
            </button>
          )}
          {!['completed', 'stopped'].includes(p.status) && (
            <button className="btn danger" disabled={busy} onClick={() => confirm('Stop building this app? You can resume later.') && act('stop')}>
              <Square size={15} /> Stop
            </button>
          )}
          <button className="btn" onClick={() => onOpenCommand(projectId)} title="Every agent, task, test, commit and log">
            <Code2 size={15} /> Details & code
          </button>
        </div>
      </div>

      {decisionNeeded && (
        <div className={`banner ${p.status === 'needs_attention' ? 'critical' : 'warning'}`} role="alert">
          <div className="grow">
            <strong>{p.status === 'awaiting_approval' ? 'Ready for your approval.' : 'The team needs your decision.'}</strong> {p.status_reason}
          </div>
          <div className="row wrap">
            {p.status === 'needs_attention' && (
              <button className="btn" disabled={busy} onClick={() => act('continue', { extra_iterations: 2 }, 'Two more fix rounds granted')}>
                <RefreshCcw size={15} /> Keep fixing
              </button>
            )}
            <button className="btn primary" disabled={busy} onClick={() => act('approve', undefined, 'Approved — releasing')}>
              <ThumbsUp size={15} /> {p.status === 'awaiting_approval' ? 'Approve & release' : 'Release as is'}
            </button>
          </div>
        </div>
      )}

      <div className="build-grid">
        <aside className="build-side">
          <div className="card card-body">
            <div className="row">
              <strong className="grow">Progress</strong>
              <span className="muted">{Math.round(p.progress)}%</span>
            </div>
            <div className="meter" role="progressbar" aria-valuenow={Math.round(p.progress)} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${p.progress}%` }} />
            </div>
            <ol className="steps">
              {STEPS.map((s, i) => {
                const state = i < stepIndex ? 'done' : i === stepIndex && p.status !== 'completed' ? 'current' : p.status === 'completed' ? 'done' : 'todo'
                return (
                  <li key={s.label} className={`step-item ${state}`}>
                    {state === 'done' ? (
                      <CheckCircle2 size={16} />
                    ) : state === 'current' ? (
                      p.status === 'running' ? <Loader2 size={16} className="spin" /> : <Circle size={16} />
                    ) : (
                      <Circle size={16} />
                    )}
                    <span>{s.label}</span>
                  </li>
                )
              })}
            </ol>
          </div>

          {working.length > 0 && (
            <div className="card card-body">
              <strong>Working right now</strong>
              <div className="stack" style={{ gap: 10, marginTop: 10 }}>
                {working.map((a) => (
                  <div key={a.role} className="now-item">
                    <div className="row">
                      <Loader2 size={14} className="spin" />
                      <strong className="grow ellipsis">{a.title}</strong>
                      <span className="muted small">{duration(a.current_task!.elapsed_s)}</span>
                    </div>
                    <div className="secondary small ellipsis">{a.current_task!.title}</div>
                    {(tokens[a.role] ?? a.current_task!.tokens) > 0 && (
                      <div className="muted small">{tokens[a.role] ?? a.current_task!.tokens} tokens written</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {(test || security || review) && (
            <div className="card card-body">
              <strong>Quality checks</strong>
              <div className="badges">
                {test && (
                  <div className={`qbadge ${test.passed ? 'ok' : 'bad'}`}>
                    <TestTube2 size={16} />
                    <div>
                      <div className="qvalue">{scenarios.length ? `${passedScenarios}/${scenarios.length}` : test.passed ? 'pass' : 'fail'}</div>
                      <div className="qlabel">browser tests</div>
                    </div>
                  </div>
                )}
                {security && (
                  <div className={`qbadge ${security.passed ? 'ok' : 'bad'}`}>
                    <ShieldCheck size={16} />
                    <div>
                      <div className="qvalue">{Math.round(security.score)}</div>
                      <div className="qlabel">security score</div>
                    </div>
                  </div>
                )}
                {review && (
                  <div className={`qbadge ${review.passed ? 'ok' : 'warn'}`}>
                    <Code2 size={16} />
                    <div>
                      <div className="qvalue">{Math.round(review.score / 10)}/10</div>
                      <div className="qlabel">code review</div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="card card-body">
            <strong>What the team did</strong>
            <ul className="timeline">
              {friendly.length === 0 && <li className="muted">Starting up…</li>}
              {friendly.map((e, i) => (
                <li key={e.id ?? i} className={e.level}>
                  {e.message}
                </li>
              ))}
            </ul>
          </div>
        </aside>

        <section className="build-main">
          <div className="card preview-card">
            <div className="preview-bar">
              <span className="dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span className="preview-url ellipsis">{p.preview_url ?? (screenshot ? 'latest test run' : 'not built yet')}</span>
              {p.preview_url && (
                <>
                  <button className="btn ghost sm" onClick={() => setFrameKey((k) => k + 1)} title="Reload preview" aria-label="Reload preview">
                    <RefreshCcw size={14} />
                  </button>
                  <a className="btn ghost sm" href={p.preview_url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink size={14} /> Open
                  </a>
                </>
              )}
              {!p.preview_url && snap.tasks.some((t) => t.kind === 'implement' && t.status === 'completed') && p.status !== 'running' && (
                <button className="btn ghost sm" disabled={busy} onClick={() => act('preview')}>
                  <Play size={14} /> Run it
                </button>
              )}
              {p.status === 'completed' && (
                <a className="btn ghost sm" href={`/api/projects/${projectId}/download`}>
                  <Download size={14} /> .zip
                </a>
              )}
            </div>
            <div className="preview-body">
              {p.preview_url ? (
                <iframe
                  key={frameKey}
                  src={p.preview_url}
                  title={`${p.name} preview`}
                  allow="clipboard-write"
                  sandbox="allow-scripts allow-forms allow-same-origin allow-modals allow-popups allow-downloads"
                />
              ) : screenshot ? (
                <img src={`${screenshot}?v=${reports.length}`} alt={`Screenshot of ${p.name} from the latest browser test`} className="preview-shot" />
              ) : writtenFiles.length > 0 ? (
                <LiveCode projectId={projectId} files={writtenFiles} />
              ) : (
                <div className="preview-empty">
                  <Loader2 size={28} className={p.status === 'running' ? 'spin' : ''} />
                  <div>Your app will appear here as soon as the first version has been built and tested.</div>
                </div>
              )}
            </div>
          </div>

          <div className="card card-body change-box">
            <div className="row">
              <input
                className="input"
                value={feedback}
                maxLength={2000}
                onChange={(e) => setFeedback(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendFeedback()}
                placeholder={
                  p.status === 'completed' || decisionNeeded
                    ? 'Want changes? e.g. “Add a dark mode” or “Streaks should count days, not clicks”'
                    : 'Guide the team while it works…'
                }
                disabled={p.status === 'stopped'}
              />
              <button className="btn primary" disabled={busy || !feedback.trim() || p.status === 'stopped'} onClick={sendFeedback}>
                <Send size={15} /> {p.status === 'completed' || decisionNeeded ? 'Request change' : 'Send'}
              </button>
            </div>
            {p.status === 'completed' && p.summary && <p className="secondary small" style={{ margin: '10px 0 0' }}>{p.summary}</p>}
          </div>
        </section>
      </div>
    </div>
  )
}
