import { useState, type FormEvent } from 'react'
import { Rocket } from 'lucide-react'
import { api } from '../api'
import type { Snapshot, SystemStatus } from '../types'
import { useToast } from './ui'

const EXAMPLES = [
  'A password generator that creates strong passwords with options for length, symbols and numbers',
  'A habit tracker where I can add daily habits, tick them off and see my current streak',
  'A notes app with a REST API and SQLite database to create, list and delete notes',
]

export default function NewProject({
  system,
  onCreated,
  onCancel,
}: {
  system: SystemStatus | null
  onCreated: (id: string) => void
  onCancel?: () => void
}) {
  const toast = useToast()
  const [objective, setObjective] = useState('')
  const [name, setName] = useState('')
  const [appType, setAppType] = useState<'auto' | 'static_web' | 'web_with_backend'>('auto')
  const [approval, setApproval] = useState(false)
  const [maxFix, setMaxFix] = useState(3)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      const snap = await api<Snapshot>('/projects', 'POST', {
        objective,
        name: name || undefined,
        app_type: appType,
        require_approval: approval,
        max_fix_iterations: maxFix,
        auto_start: true,
      })
      onCreated(snap.project.id)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not create project')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="content" style={{ maxWidth: 820 }}>
      <h1 style={{ marginBottom: 4 }}>What should the company build?</h1>
      <p className="secondary" style={{ marginTop: 0 }}>
        The AI CEO turns your idea into a charter, the team plans, designs, builds, tests, reviews and fixes it, then
        deploys a live preview. You can pause, steer or roll back at any time.
      </p>
      {system && !system.llm.ok && (
        <div className="banner critical">
          <div>
            <strong>LLM not ready.</strong> {system.llm.detail}
          </div>
        </div>
      )}
      <form className="card" onSubmit={submit}>
        <div className="card-body stack">
          <label className="field">
            Product idea
            <textarea
              className="textarea"
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              placeholder="Describe the app you want…"
              minLength={5}
              maxLength={4000}
              required
              autoFocus
            />
          </label>
          <div className="row wrap">
            <span className="muted small">Try:</span>
            {EXAMPLES.map((ex) => (
              <button type="button" key={ex} className="btn sm ghost" onClick={() => setObjective(ex)} title={ex}>
                {ex.split(' ').slice(0, 4).join(' ')}…
              </button>
            ))}
          </div>
          <div className="grid-2">
            <label className="field">
              Name (optional)
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
            </label>
            <label className="field">
              App type
              <select className="select" value={appType} onChange={(e) => setAppType(e.target.value as typeof appType)}>
                <option value="auto">Let the CEO decide</option>
                <option value="static_web">Static web app (browser only)</option>
                <option value="web_with_backend">Web app with FastAPI backend</option>
              </select>
            </label>
            <label className="field">
              Max fix iterations
              <input
                className="input"
                type="number"
                min={0}
                max={10}
                value={maxFix}
                onChange={(e) => setMaxFix(Number(e.target.value))}
              />
            </label>
            <label className="check" style={{ alignSelf: 'end', paddingBottom: 8 }}>
              <input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)} />
              Require my approval before deploy
            </label>
          </div>
          <div className="row">
            {onCancel && (
              <button type="button" className="btn" onClick={onCancel}>
                Cancel
              </button>
            )}
            <div className="spacer" />
            <button className="btn primary" disabled={busy || objective.trim().length < 5}>
              <Rocket size={16} /> {busy ? 'Starting…' : 'Start the company'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
