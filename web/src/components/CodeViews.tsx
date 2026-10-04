import { useEffect, useState } from 'react'
import { FileCode2, GitCommit, History, Search, Tag } from 'lucide-react'
import { api, timeAgo } from '../api'
import type { Commit, ProjectStatus } from '../types'
import { Card, useToast } from './ui'

interface FileEntry {
  path: string
  bytes: number
}

export function CodeView({ projectId, version }: { projectId: string; version: number }) {
  const [files, setFiles] = useState<FileEntry[]>([])
  const [path, setPath] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<{ path: string; line: number; text: string }[] | null>(null)
  const [analysis, setAnalysis] = useState<any>(null)

  useEffect(() => {
    api<FileEntry[]>(`/projects/${projectId}/files`).then((f) => {
      setFiles(f)
      setPath((p) => p ?? f.find((x) => x.path.endsWith('index.html'))?.path ?? f[0]?.path ?? null)
    })
    api(`/projects/${projectId}/analysis`).then(setAnalysis).catch(() => {})
  }, [projectId, version])

  useEffect(() => {
    if (!path) return
    api<{ content: string }>(`/projects/${projectId}/files/content?path=${encodeURIComponent(path)}`)
      .then((r) => setContent(r.content))
      .catch(() => setContent(''))
  }, [projectId, path, version])

  const runSearch = () => {
    if (!query.trim()) return setHits(null)
    api<typeof hits>(`/projects/${projectId}/search?q=${encodeURIComponent(query)}`).then(setHits)
  }

  const lines = content.split('\n')
  return (
    <div className="split">
      <div className="stack">
        <Card title="Files" bodyClass="">
          <div style={{ padding: 8 }}>
            {files.map((f) => (
              <button key={f.path} className={`list-btn ${f.path === path ? 'active' : ''}`} onClick={() => setPath(f.path)}>
                <span className="row">
                  <FileCode2 size={14} />
                  <span className="grow ellipsis mono">{f.path}</span>
                  <span className="muted small">{(f.bytes / 1024).toFixed(1)}k</span>
                </span>
              </button>
            ))}
          </div>
        </Card>
        <Card title="Code search">
          <div className="row">
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && runSearch()} placeholder="Search code…" />
            <button className="btn" onClick={runSearch} aria-label="Search">
              <Search size={15} />
            </button>
          </div>
          {hits && (
            <div style={{ marginTop: 8, maxHeight: 260, overflow: 'auto' }}>
              {hits.length === 0 && <div className="muted small">No matches.</div>}
              {hits.map((h) => (
                <button key={`${h.path}:${h.line}`} className="list-btn" onClick={() => setPath(h.path)}>
                  <div className="mono small">{h.path}:{h.line}</div>
                  <div className="muted small ellipsis mono">{h.text}</div>
                </button>
              ))}
            </div>
          )}
        </Card>
        {analysis && (
          <Card title="Code intelligence">
            <div className="small secondary">
              {analysis.total_lines} lines · {Object.entries(analysis.languages).map(([k, v]) => `${k} ${v}`).join(' · ')}
            </div>
            <div className="section-title" style={{ marginTop: 10 }}>Dependencies</div>
            <ul className="clean small mono">
              {analysis.dependencies.map((d: any, i: number) => (
                <li key={i}>{d.from} → {d.to} <span className="muted">({d.kind})</span></li>
              ))}
            </ul>
            {analysis.routes.length > 0 && (
              <>
                <div className="section-title" style={{ marginTop: 10 }}>API routes</div>
                <ul className="clean small mono">{analysis.routes.map((r: any) => <li key={r.method + r.path}>{r.method} {r.path}</li>)}</ul>
              </>
            )}
          </Card>
        )}
      </div>
      <Card title={path ?? 'No file selected'} bodyClass="">
        <pre className="code" style={{ borderRadius: 0, border: 'none', maxHeight: 720 }}>
          <div className="code-lines">
            {lines.map((l, i) => (
              <div key={i} style={{ display: 'contents' }}>
                <span className="ln">{i + 1}</span>
                <span>{l || ' '}</span>
              </div>
            ))}
          </div>
        </pre>
      </Card>
    </div>
  )
}

export function ChangesView({
  projectId,
  status,
  version,
  onChanged,
}: {
  projectId: string
  status: ProjectStatus
  version: number
  onChanged: () => void
}) {
  const toast = useToast()
  const [data, setData] = useState<{ branch: string; tags: string[]; commits: Commit[] } | null>(null)
  const [sha, setSha] = useState<string | null>(null)
  const [diff, setDiff] = useState('')

  const load = () =>
    api<NonNullable<typeof data>>(`/projects/${projectId}/commits`).then((d) => {
      setData(d)
      setSha((s) => s ?? d.commits[0]?.sha ?? null)
    })

  useEffect(() => {
    load()
  }, [projectId, version]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (sha) api<{ diff: string }>(`/projects/${projectId}/commits/${sha}`).then((r) => setDiff(r.diff))
  }, [projectId, sha])

  const rollback = async (target: Commit) => {
    if (!confirm(`Restore the project to "${target.message}" (${target.short})?\n\nThis creates a new commit; no history is lost.`)) return
    try {
      await api(`/projects/${projectId}/rollback`, 'POST', { commit: target.sha })
      toast(`Rolled back to ${target.short}`, true)
      setSha(null)
      await load()
      onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Rollback failed')
    }
  }

  if (!data) return <div className="empty">Loading history…</div>
  const selected = data.commits.find((c) => c.sha === sha)
  const canRollback = status !== 'running'

  return (
    <div className="split">
      <Card
        title={
          <span className="row">
            <History size={15} /> History
          </span>
        }
        actions={<span className="pill mono">{data.branch}</span>}
        bodyClass=""
      >
        <div style={{ maxHeight: 700, overflow: 'auto', padding: 8 }}>
          {data.commits.map((c) => (
            <button key={c.sha} className={`list-btn ${c.sha === sha ? 'active' : ''}`} onClick={() => setSha(c.sha)}>
              <div className="row">
                <GitCommit size={14} />
                <span className="grow ellipsis" style={{ fontWeight: 500 }}>
                  {c.message}
                </span>
              </div>
              <div className="muted small">
                <span className="mono">{c.short}</span> · {c.author} · {timeAgo(c.date)}
              </div>
            </button>
          ))}
        </div>
        {data.tags.length > 0 && (
          <div className="row wrap" style={{ padding: '8px 16px 12px' }}>
            {data.tags.map((t) => (
              <span key={t} className="pill good">
                <Tag size={11} /> {t}
              </span>
            ))}
          </div>
        )}
      </Card>
      <Card
        title={selected ? `${selected.short} — ${selected.message}` : 'Select a commit'}
        actions={
          selected && (
            <button className="btn sm" disabled={!canRollback} title={canRollback ? '' : 'Pause the project first'} onClick={() => rollback(selected)}>
              <History size={13} /> Roll back to here
            </button>
          )
        }
        bodyClass=""
      >
        <pre className="code diff" style={{ borderRadius: 0, border: 'none', maxHeight: 720 }}>
          {diff.split('\n').map((l, i) => {
            const cls = l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : l.startsWith('@@') ? 'hunk' : l.startsWith('diff ') || l.startsWith('index ') ? 'meta' : ''
            return (
              <div key={i} className={cls}>
                {l || ' '}
              </div>
            )
          })}
        </pre>
      </Card>
    </div>
  )
}
