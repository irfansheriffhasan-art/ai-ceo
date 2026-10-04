import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, Cpu, GitBranch, Globe, LogOut, Moon, Plus, Sun } from 'lucide-react'
import { api, useEventStream } from './api'
import type { Project, SystemStatus } from './types'
import Login from './components/Login'
import NewProject from './components/NewProject'
import ProjectView from './components/ProjectView'
import { ProjectStatusPill } from './components/ui'

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    api<{ authenticated: boolean }>('/auth/session').then((r) => setAuthed(r.authenticated)).catch(() => setAuthed(false))
    const onUnauthorized = () => setAuthed(false)
    window.addEventListener('aiceo:unauthorized', onUnauthorized)
    return () => window.removeEventListener('aiceo:unauthorized', onUnauthorized)
  }, [])

  if (authed === null) return <div className="empty">Loading…</div>
  if (!authed) return <Login onLogin={() => setAuthed(true)} />
  return <Shell onLogout={() => setAuthed(false)} />
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [selected, setSelected] = useState<string | null>(() => new URLSearchParams(location.search).get('project'))
  const [creating, setCreating] = useState(false)
  const [system, setSystem] = useState<SystemStatus | null>(null)

  const loadProjects = useCallback(() => {
    api<Project[]>('/projects').then(setProjects).catch(() => {})
  }, [])

  useEffect(() => {
    loadProjects()
    api<SystemStatus>('/system').then(setSystem).catch(() => {})
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

  const [dark, setDark] = useState(() => {
    const t = document.documentElement.dataset.theme
    return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
  })
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

  const showNew = creating || (!selected && projects.length === 0)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">
            <Bot size={17} />
          </span>
          AI-CEO <span className="sub">Command Center</span>
        </div>
        <div className="spacer" />
        {system && (
          <div className="row wrap status-pills" aria-label="System status">
            <span className={`pill ${system.llm.ok ? 'good' : 'critical'}`} title={system.llm.detail}>
              <Cpu size={12} />
              {system.llm.provider} · {system.llm.model}
            </span>
            <span className={`pill ${system.browser.ok ? 'good' : 'warning'}`} title={system.browser.detail}>
              <Globe size={12} />
              browser tests {system.browser.ok ? 'on' : 'off'}
            </span>
            <span className={`pill ${system.git.ok ? 'good' : 'critical'}`}>
              <GitBranch size={12} />
              git
            </span>
          </div>
        )}
        <button className="btn ghost" onClick={toggleTheme} aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'} title="Toggle theme">
          {dark ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button className="btn ghost" onClick={logout} title="Sign out" aria-label="Sign out">
          <LogOut size={16} />
        </button>
      </header>
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
              <button
                key={p.id}
                className={`project-link ${p.id === selected && !creating ? 'active' : ''}`}
                onClick={() => {
                  setSelected(p.id)
                  setCreating(false)
                }}
              >
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
                onChange={(e) => {
                  if (e.target.value === '__new') setCreating(true)
                  else {
                    setSelected(e.target.value)
                    setCreating(false)
                  }
                }}
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
                setCreating(false)
                setSelected(id)
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
    </div>
  )
}
