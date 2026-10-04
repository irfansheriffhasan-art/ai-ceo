import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, Cpu, LayoutDashboard, LogOut, Moon, Plus, Sparkles, Sun } from 'lucide-react'
import { api, useEventStream } from './api'
import type { Project, SystemStatus } from './types'
import Login from './components/Login'
import NewProject from './components/NewProject'
import ProjectView from './components/ProjectView'
import Studio from './components/Studio'
import { ProjectStatusPill } from './components/ui'

type View = 'studio' | 'command'

/** `python main.py serve` opens the UI with #token=… so the operator is signed in automatically. */
async function loginFromFragment(): Promise<void> {
  const match = location.hash.match(/token=([^&]+)/)
  if (!match) return
  history.replaceState(null, '', location.pathname + location.search) // never keep the token in the address bar
  await api('/auth/login', 'POST', { token: decodeURIComponent(match[1]) }).catch(() => {})
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    loginFromFragment()
      .then(() => api<{ authenticated: boolean }>('/auth/session'))
      .then((r) => setAuthed(r.authenticated))
      .catch(() => setAuthed(false))
    const onUnauthorized = () => setAuthed(false)
    window.addEventListener('aiceo:unauthorized', onUnauthorized)
    return () => window.removeEventListener('aiceo:unauthorized', onUnauthorized)
  }, [])

  if (authed === null) return <div className="empty">Loading…</div>
  if (!authed) return <Login onLogin={() => setAuthed(true)} />
  return <Root onLogout={() => setAuthed(false)} />
}

function Root({ onLogout }: { onLogout: () => void }) {
  const params = new URLSearchParams(location.search)
  const [view, setView] = useState<View>(params.get('view') === 'command' ? 'command' : 'studio')
  const [commandProject, setCommandProject] = useState<string | null>(params.get('project'))
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const [dark, setDark] = useState(() => {
    const t = document.documentElement.dataset.theme
    return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    api<SystemStatus>('/system').then(setSystem).catch(() => {})
  }, [])

  const toggleTheme = () => {
    const next = dark ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    setDark(!dark)
    try {
      localStorage.setItem('aiceo.theme', next)
    } catch {
      /* storage unavailable: theme lasts for this session */
    }
  }

  const logout = async () => {
    await api('/auth/logout', 'POST').catch(() => {})
    onLogout()
  }

  const go = (next: View, projectId?: string | null) => {
    const url = new URL(location.href)
    url.search = ''
    if (next === 'command') {
      url.searchParams.set('view', 'command')
      if (projectId) url.searchParams.set('project', projectId)
      setCommandProject(projectId ?? commandProject)
    }
    history.pushState(null, '', url)
    setView(next)
  }

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand brand-btn" onClick={() => go('studio')} aria-label="AI-CEO home">
          <span className="logo">
            <Bot size={17} />
          </span>
          AI-CEO
        </button>
        <nav className="topnav" aria-label="Views">
          <button className={`topnav-item ${view === 'studio' ? 'active' : ''}`} onClick={() => go('studio')}>
            <Sparkles size={15} /> Studio
          </button>
          <button className={`topnav-item ${view === 'command' ? 'active' : ''}`} onClick={() => go('command')}>
            <LayoutDashboard size={15} /> Command center
          </button>
        </nav>
        <div className="spacer" />
        {system && (
          <span className={`pill status-pills ${system.llm.ok ? 'good' : 'critical'}`} title={system.llm.detail}>
            <Cpu size={12} />
            {system.llm.provider === 'mock' ? 'demo mode' : `${system.llm.provider} · ${system.llm.model}`}
          </span>
        )}
        <button className="btn ghost" onClick={toggleTheme} aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'} title="Toggle theme">
          {dark ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button className="btn ghost" onClick={logout} title="Sign out" aria-label="Sign out">
          <LogOut size={16} />
        </button>
      </header>
      {view === 'studio' ? (
        <main className="main">
          <Studio system={system} onOpenCommand={(pid) => go('command', pid)} />
        </main>
      ) : (
        <CommandCenter system={system} selected={commandProject} onSelect={setCommandProject} />
      )}
    </div>
  )
}

function CommandCenter({
  system,
  selected,
  onSelect,
}: {
  system: SystemStatus | null
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const [projects, setProjects] = useState<Project[]>([])
  const [creating, setCreating] = useState(false)

  const loadProjects = useCallback(() => {
    api<Project[]>('/projects').then(setProjects).catch(() => {})
  }, [])

  useEffect(() => {
    loadProjects()
  }, [loadProjects])

  // Keep the sidebar fresh: persisted events refresh the list (debounced, cheap query).
  const sidebarTimer = useRef<number | null>(null)
  useEventStream(null, (e) => {
    if (e.id === null) return
    if (sidebarTimer.current) window.clearTimeout(sidebarTimer.current)
    sidebarTimer.current = window.setTimeout(loadProjects, 600)
  })

  useEffect(() => {
    const url = new URL(location.href)
    if (selected) url.searchParams.set('project', selected)
    else url.searchParams.delete('project')
    history.replaceState(null, '', url)
  }, [selected])

  const select = (id: string) => {
    onSelect(id)
    setCreating(false)
  }
  const showNew = creating || (!selected && projects.length === 0)

  return (
    <div className="body">
      <aside className="sidebar">
        <div style={{ padding: 12 }}>
          <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }} onClick={() => setCreating(true)}>
            <Plus size={16} /> New project
          </button>
        </div>
        <div className="section-title" style={{ padding: '0 18px' }}>
          Projects
        </div>
        <nav className="list">
          {projects.length === 0 && <div className="muted small" style={{ padding: 10 }}>No projects yet.</div>}
          {projects.map((p) => (
            <button key={p.id} className={`project-link ${p.id === selected && !creating ? 'active' : ''}`} onClick={() => select(p.id)}>
              <div className="ellipsis" style={{ fontWeight: 600 }}>
                {p.name}
              </div>
              <div className="row" style={{ marginTop: 6 }}>
                <ProjectStatusPill status={p.status} />
                <span className="muted small">
                  {Math.round(p.progress)}% · it {p.iteration}
                </span>
              </div>
              <div className="meter" aria-hidden="true">
                <span style={{ width: `${p.progress}%` }} />
              </div>
            </button>
          ))}
        </nav>
      </aside>
      <main className="main">
        {projects.length > 0 && (
          <div className="mobile-projects" style={{ padding: '12px 16px 0' }}>
            <select
              className="select"
              aria-label="Select project"
              value={creating ? '__new' : selected ?? ''}
              onChange={(e) => (e.target.value === '__new' ? setCreating(true) : select(e.target.value))}
            >
              <option value="__new">+ New project</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {p.status}
                </option>
              ))}
            </select>
          </div>
        )}
        {showNew ? (
          <NewProject
            system={system}
            onCancel={projects.length ? () => setCreating(false) : undefined}
            onCreated={(id) => {
              select(id)
              loadProjects()
            }}
          />
        ) : selected ? (
          <ProjectView key={selected} projectId={selected} onChanged={loadProjects} />
        ) : (
          <div className="empty">Select a project or create a new one.</div>
        )}
      </main>
    </div>
  )
}
