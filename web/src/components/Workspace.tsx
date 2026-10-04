import { Fragment, useEffect, useMemo, useState } from 'react'
import { api, clock, duration, timeAgo } from '../api'
import type { LLMCall, MemoryItem, Report, Snapshot } from '../types'
import { ChangesView, CodeView } from './CodeViews'
import QualityChart from './QualityChart'
import { Card, JsonView, PassFail, SeverityPill, TaskStatusPill } from './ui'

const TABS = [
  ['requirements', 'Requirements'],
  ['architecture', 'Architecture'],
  ['decisions', 'Decisions'],
  ['outputs', 'Agent outputs'],
  ['code', 'Code'],
  ['changes', 'Changes'],
  ['tests', 'Tests'],
  ['security', 'Security'],
  ['review', 'Review'],
  ['quality', 'Quality'],
  ['logs', 'Logs'],
  ['memory', 'Memory'],
] as const
type TabKey = (typeof TABS)[number][0]

export default function Workspace({
  snapshot,
  version,
  onOpenTask,
  onChanged,
}: {
  snapshot: Snapshot
  version: number
  onOpenTask: (id: string) => void
  onChanged: () => void
}) {
  const [tab, setTab] = useState<TabKey>('requirements')
  const [memory, setMemory] = useState<Record<string, MemoryItem[]>>({})
  const [reports, setReports] = useState<Report[]>([])
  const pid = snapshot.project.id

  useEffect(() => {
    api<Record<string, MemoryItem[]>>(`/projects/${pid}/memory`).then(setMemory).catch(() => {})
    api<Report[]>(`/projects/${pid}/reports`).then(setReports).catch(() => {})
  }, [pid, version])

  const mem = (kind: string, key: string) => memory[kind]?.find((m) => m.key === key)?.value
  const latest = (kind: string) => [...reports].reverse().find((r) => r.kind === kind)

  return (
    <div>
      <div className="tabs" role="tablist" aria-label="Workspace sections">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={`tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'requirements' && <Requirements objective={mem('objective', 'main')} req={mem('requirements', 'spec')} strategy={mem('strategy', 'plan')} />}
      {tab === 'architecture' && <Architecture arch={mem('architecture', 'spec')} design={mem('design', 'spec')} plan={mem('plan', 'work_breakdown')} />}
      {tab === 'decisions' && <Decisions items={memory.decision ?? []} constraints={memory.constraint ?? []} preferences={memory.preference ?? []} />}
      {tab === 'outputs' && <Outputs snapshot={snapshot} onOpenTask={onOpenTask} />}
      {tab === 'code' && <CodeView projectId={pid} version={version} />}
      {tab === 'changes' && <ChangesView projectId={pid} status={snapshot.project.status} version={version} onChanged={onChanged} />}
      {tab === 'tests' && <Tests projectId={pid} reports={reports.filter((r) => r.kind === 'test')} bugs={memory.bug ?? []} />}
      {tab === 'security' && <Security report={latest('security')} />}
      {tab === 'review' && <Review report={latest('review')} final={latest('final_review')} />}
      {tab === 'quality' && <QualityChart reports={reports} />}
      {tab === 'logs' && <Logs projectId={pid} version={version} />}
      {tab === 'memory' && <JsonView value={memory} />}
    </div>
  )
}

function Requirements({ objective, req, strategy }: { objective: any; req: any; strategy: any }) {
  if (!req) return <div className="empty">The Product Agent hasn't written requirements yet.</div>
  return (
    <div className="grid-2">
      <Card title="Charter">
        <dl className="kv">
          <dt>Objective</dt>
          <dd>{objective?.objective}</dd>
          <dt>App type</dt>
          <dd>{objective?.app_type}</dd>
          <dt>Target users</dt>
          <dd>{objective?.target_users}</dd>
          <dt>Original request</dt>
          <dd className="secondary">{objective?.request}</dd>
        </dl>
      </Card>
      <Card title="Features">
        <table className="table">
          <tbody>
            {req.features.map((f: any) => (
              <tr key={f.name}>
                <td style={{ width: 70 }}>
                  <span className={`pill ${f.priority === 'must' ? 'info' : ''}`}>{f.priority}</span>
                </td>
                <td>
                  <strong>{f.name}</strong>
                  <div className="secondary small">{f.description}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Acceptance criteria">
        <ul className="clean">{req.acceptance_criteria.map((c: string) => <li key={c}>{c}</li>)}</ul>
      </Card>
      <Card title="User stories">
        <ul className="clean">{req.user_stories.map((s: string) => <li key={s}>{s}</li>)}</ul>
        <div className="section-title" style={{ marginTop: 12 }}>Out of scope</div>
        <ul className="clean">{req.out_of_scope.map((s: string) => <li key={s}>{s}</li>)}</ul>
      </Card>
      {strategy && (
        <Card title="Delivery strategy (Strategic Planner)">
          <div className="section-title">Milestones</div>
          <ol className="clean">{strategy.milestones.map((m: any) => <li key={m.name}><strong>{m.name}</strong> — {m.goal}</li>)}</ol>
          <div className="section-title" style={{ marginTop: 12 }}>Risks</div>
          <ul className="clean">{strategy.risks.map((r: string) => <li key={r}>{r}</li>)}</ul>
          <div className="section-title" style={{ marginTop: 12 }}>Definition of done</div>
          <ul className="clean">{strategy.definition_of_done.map((r: string) => <li key={r}>{r}</li>)}</ul>
        </Card>
      )}
    </div>
  )
}

function Architecture({ arch, design, plan }: { arch: any; design: any; plan: any }) {
  if (!arch) return <div className="empty">The Architect hasn't produced an architecture yet.</div>
  return (
    <div className="grid-2">
      <Card title="Stack & files">
        <dl className="kv" style={{ marginBottom: 12 }}>
          {Object.entries(arch.stack).map(([k, v]) => (
            <Fragment key={k}>
              <dt>{k}</dt>
              <dd>{String(v)}</dd>
            </Fragment>
          ))}
        </dl>
        <table className="table">
          <thead><tr><th>File</th><th>Owner</th><th>Purpose</th></tr></thead>
          <tbody>
            {arch.files.map((f: any) => (
              <tr key={f.path}><td className="mono">{f.path}</td><td>{f.owner_role}</td><td className="secondary">{f.purpose}</td></tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Decisions">
        <ul className="clean">{arch.decisions.map((d: any) => <li key={d.decision}><strong>{d.decision}</strong> — <span className="secondary">{d.rationale}</span></li>)}</ul>
        {arch.data_model.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 12 }}>Data model</div>
            <ul className="clean">{arch.data_model.map((e: any) => <li key={e.name}><strong>{e.name}</strong>: {e.fields.join(', ')}</li>)}</ul>
          </>
        )}
        {arch.api_endpoints.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 12 }}>API</div>
            <ul className="clean">{arch.api_endpoints.map((e: any) => <li key={e.method + e.path} className="mono">{e.method} {e.path} <span className="secondary">— {e.description}</span></li>)}</ul>
          </>
        )}
      </Card>
      {design && (
        <Card title={`Design — ${design.style_name}`}>
          <div className="row wrap" style={{ marginBottom: 12 }}>
            {Object.entries(design.palette).map(([k, v]) => (
              <div key={k} className="stack" style={{ gap: 4, alignItems: 'center' }}>
                <div className="swatch" style={{ background: String(v) }} />
                <span className="small muted">{k}</span>
              </div>
            ))}
          </div>
          <p className="secondary">{design.layout}</p>
          <div className="section-title">Accessibility</div>
          <ul className="clean">{design.accessibility.map((a: string) => <li key={a}>{a}</li>)}</ul>
        </Card>
      )}
      {plan && (
        <Card title="Work breakdown (Project Manager)">
          <table className="table">
            <thead><tr><th>Task</th><th>Owner</th><th>After</th></tr></thead>
            <tbody>{plan.map((t: any) => <tr key={t.task}><td>{t.task}</td><td>{t.owner}</td><td className="mono small">{t.after.join(', ') || '—'}</td></tr>)}</tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

function Decisions({ items, constraints, preferences }: { items: MemoryItem[]; constraints: MemoryItem[]; preferences: MemoryItem[] }) {
  return (
    <div className="grid-2">
      <Card title={`Decision log (${items.length})`}>
        {items.length === 0 && <div className="muted">No decisions recorded yet.</div>}
        <div className="stack">
          {[...items].reverse().map((d) => (
            <div key={d.id}>
              <div className="row">
                <strong className="grow">{d.value.decision}</strong>
                <span className="pill">{d.value.by}</span>
                <span className="muted small">{timeAgo(d.created_at)}</span>
              </div>
              <div className="secondary small">{d.value.rationale}</div>
            </div>
          ))}
        </div>
      </Card>
      <div className="stack">
        <Card title="Constraints">
          <ul className="clean">{constraints.map((c) => <li key={c.id}>{String(c.value)}</li>)}</ul>
        </Card>
        <Card title="Client feedback & preferences">
          {preferences.length === 0 ? <div className="muted">None yet. Use the feedback box above.</div> : <ul className="clean">{preferences.map((c) => <li key={c.id}>{String(c.value)}</li>)}</ul>}
        </Card>
      </div>
    </div>
  )
}

function Outputs({ snapshot, onOpenTask }: { snapshot: Snapshot; onOpenTask: (id: string) => void }) {
  const done = snapshot.tasks.filter((t) => t.summary || t.error)
  return (
    <Card title="Agent outputs (concise decisions & results — no hidden reasoning)" bodyClass="">
      <table className="table">
        <thead><tr><th>#</th><th>Agent</th><th>Task</th><th>Status</th><th>Result</th></tr></thead>
        <tbody>
          {done.map((t) => (
            <tr key={t.id} className="clickable" onClick={() => onOpenTask(t.id)}>
              <td className="num muted">{t.seq}</td>
              <td>{t.role}</td>
              <td>{t.title}</td>
              <td><TaskStatusPill status={t.status} /></td>
              <td className="secondary">{t.summary || t.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

function Tests({ projectId, reports, bugs }: { projectId: string; reports: Report[]; bugs: MemoryItem[] }) {
  const [idx, setIdx] = useState(reports.length - 1)
  useEffect(() => setIdx(reports.length - 1), [reports.length])
  if (!reports.length) return <div className="empty">No test runs yet.</div>
  const r = reports[Math.max(0, Math.min(idx, reports.length - 1))]
  const d = r.details
  const issues: any[] = (d.issues ?? []).filter((i: any) => i.source !== 'scenario')
  return (
    <div className="stack">
      <div className="row wrap">
        {reports.map((rep, i) => (
          <button key={rep.id} className={`btn sm ${i === idx ? 'primary' : ''}`} onClick={() => setIdx(i)}>
            Iteration {rep.iteration} {rep.passed ? '✓' : '✗'}
          </button>
        ))}
      </div>
      <div className="banner" style={{ alignItems: 'center' }}>
        <PassFail passed={r.passed} />
        <div className="grow">{r.summary}</div>
        <span className="muted small">{d.channel ? `browser: ${d.channel}` : d.browser_skipped ? 'no browser' : ''}</span>
      </div>
      <div className="grid-2">
        <Card title="Acceptance scenarios (headless browser)" bodyClass="">
          {(d.scenarios ?? []).length === 0 ? (
            <div className="empty">No browser scenarios ran.</div>
          ) : (
            <table className="table">
              <thead><tr><th>Result</th><th>Scenario</th></tr></thead>
              <tbody>
                {d.scenarios.map((s: any) => (
                  <tr key={s.name}>
                    <td>{s.defect === 'test' ? <span className="pill warning">invalid test</span> : <PassFail passed={s.passed} />}</td>
                    <td>
                      <strong>{s.name}</strong>
                      <div className="secondary small">{s.criterion}</div>
                      {s.error && <div className="small" style={{ color: 'var(--critical-ink)' }}>{s.error}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="What the tester saw">
          {d.screenshot ? (
            <img className="screenshot" src={`/api/projects/${projectId}/artifacts/${d.screenshot}`} alt={`Screenshot of the app at iteration ${r.iteration}`} />
          ) : (
            <div className="muted">No screenshot.</div>
          )}
          {d.load && (
            <div className="small muted" style={{ marginTop: 8 }}>
              HTTP {d.load.status} · title “{d.load.title}” · {d.load.interactive_elements} interactive elements · {d.load.page_errors?.length ?? 0} JS errors
            </div>
          )}
        </Card>
      </div>
      {(d.api ?? []).length > 0 && (
        <Card title="API tests (live backend)" bodyClass="">
          <table className="table">
            <thead><tr><th>Result</th><th>Request</th><th className="num">Status</th><th>Detail</th></tr></thead>
            <tbody>
              {d.api.map((a: any) => (
                <tr key={a.name}><td><PassFail passed={a.passed} /></td><td className="mono">{a.method} {a.path}</td><td className="num">{a.status ?? '—'}</td><td className="secondary small">{a.name}{a.error ? ` — ${a.error}` : ''}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <Card title={`Static analysis & runtime findings (${issues.length})`} bodyClass="">
        <IssueTable issues={issues} />
      </Card>
      <Card title="Bug tracker (project memory)" bodyClass="">
        <table className="table">
          <thead><tr><th>Status</th><th>Bug</th><th>File</th><th>Found</th></tr></thead>
          <tbody>
            {bugs.map((b) => (
              <tr key={b.id}>
                <td>{b.value.status === 'open' ? <span className="pill critical">open</span> : <span className="pill good">fixed{b.value.fixed_in_iteration ? ` in it ${b.value.fixed_in_iteration}` : ''}</span>}</td>
                <td>{b.value.message}</td>
                <td className="mono small">{b.value.file}</td>
                <td className="small muted">it {b.value.iteration} · {b.value.source}</td>
              </tr>
            ))}
            {bugs.length === 0 && <tr><td colSpan={4} className="muted">No bugs recorded.</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

function IssueTable({ issues }: { issues: any[] }) {
  if (!issues.length) return <div className="empty">No findings.</div>
  return (
    <table className="table">
      <thead><tr><th>Severity</th><th>Finding</th><th>Location</th></tr></thead>
      <tbody>
        {issues.map((i, n) => (
          <tr key={i.fingerprint ?? n}>
            <td><SeverityPill severity={i.severity} /></td>
            <td>
              {i.message}
              {i.evidence && <pre className="code" style={{ marginTop: 6, maxHeight: 120 }}>{i.evidence}</pre>}
              {i.suggestion && <div className="secondary small" style={{ marginTop: 4 }}>→ {i.suggestion}</div>}
            </td>
            <td className="mono small">{i.file}{i.line ? `:${i.line}` : ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Security({ report }: { report?: Report }) {
  if (!report) return <div className="empty">No security scan yet.</div>
  return (
    <div className="stack">
      <div className="banner" style={{ alignItems: 'center' }}>
        <PassFail passed={report.passed} />
        <div className="grow">{report.summary}</div>
        <span className="muted small">{report.details.files_scanned} files scanned · iteration {report.iteration}</span>
      </div>
      <Card title="Findings" bodyClass="">
        <IssueTable issues={report.details.findings ?? []} />
      </Card>
      <div className="muted small">
        Checks: secrets & keys, eval/Function, XSS sinks (innerHTML, document.write), insecure randomness, SQL injection, shell execution,
        unsafe deserialization, unvalidated API input, missing auth on mutating endpoints, CORS, debug mode, dependency pinning, container user.
        No CVE database is bundled — run pip-audit / npm audit in CI for that.
      </div>
    </div>
  )
}

function Review({ report, final }: { report?: Report; final?: Report }) {
  if (!report) return <div className="empty">No code review yet.</div>
  const d = report.details
  return (
    <div className="stack">
      <div className="banner" style={{ alignItems: 'center' }}>
        <PassFail passed={report.passed} label={report.passed ? 'Approved' : 'Changes requested'} />
        <div className="grow">{report.summary}</div>
      </div>
      <div className="grid-2">
        <Card title="Issues" bodyClass="">
          <IssueTable issues={d.issues ?? []} />
        </Card>
        <Card title="Strengths">
          <ul className="clean">{(d.strengths ?? []).map((s: string) => <li key={s}>{s}</li>)}</ul>
        </Card>
      </div>
      {final && (
        <Card title="CEO final release review">
          <PassFail passed={final.passed} label={final.details.decision} />
          <p>{final.details.summary}</p>
          <p className="secondary">{final.details.release_notes}</p>
          {final.details.unmet_criteria?.length > 0 && <ul className="clean">{final.details.unmet_criteria.map((c: string) => <li key={c}>{c}</li>)}</ul>}
        </Card>
      )}
    </div>
  )
}

function Logs({ projectId, version }: { projectId: string; version: number }) {
  const [calls, setCalls] = useState<LLMCall[]>([])
  const [open, setOpen] = useState<LLMCall | null>(null)
  useEffect(() => {
    api<LLMCall[]>(`/projects/${projectId}/llm-calls`).then(setCalls).catch(() => {})
  }, [projectId, version])
  const totals = useMemo(
    () => calls.reduce((acc, c) => ({ inT: acc.inT + c.input_tokens, outT: acc.outT + c.output_tokens, ms: acc.ms + c.latency_ms }), { inT: 0, outT: 0, ms: 0 }),
    [calls],
  )
  return (
    <div className="split">
      <Card title={`LLM calls (${calls.length})`} bodyClass="">
        <div className="muted small" style={{ padding: '8px 16px' }}>
          {totals.inT} tokens in · {totals.outT} out · {duration(totals.ms / 1000)} model time
        </div>
        <div style={{ maxHeight: 620, overflow: 'auto' }}>
          {calls.map((c) => (
            <button key={c.id} className={`list-btn ${open?.id === c.id ? 'active' : ''}`} onClick={() => api<LLMCall>(`/llm-calls/${c.id}`).then(setOpen)}>
              <div className="row">
                <strong className="grow ellipsis">{c.role}: {c.purpose}</strong>
                {c.ok ? <span className="pill good">ok</span> : <span className="pill critical">error</span>}
              </div>
              <div className="muted small">{clock(c.created_at)} · {c.output_tokens} tok · {duration(c.latency_ms / 1000)} · {c.model}</div>
            </button>
          ))}
        </div>
      </Card>
      <Card title={open ? `${open.role}: ${open.purpose}` : 'Select a call'}>
        {open ? (
          <div className="stack">
            {open.error && <div className="banner critical">{open.error}</div>}
            <div className="section-title">Prompt (truncated)</div>
            <pre className="code" style={{ maxHeight: 280 }}>{open.prompt_preview}</pre>
            <div className="section-title">Model output</div>
            <pre className="code">{open.response_text || '(empty)'}</pre>
          </div>
        ) : (
          <div className="muted">Every model call is traced: who called it, why, tokens, latency and the exact output.</div>
        )}
      </Card>
    </div>
  )
}
