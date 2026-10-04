import { useState, type FormEvent } from 'react'
import { Bot, KeyRound } from 'lucide-react'
import { api } from '../api'

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api('/auth/login', 'POST', { token })
      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <div className="card-body stack">
          <div className="brand" style={{ fontSize: 18 }}>
            <span className="logo">
              <Bot size={17} />
            </span>
            AI-CEO Command Center
          </div>
          <p className="secondary" style={{ margin: 0 }}>
            Enter the access token printed by <code>python main.py serve</code> (also stored in <code>data/auth_token</code>).
          </p>
          <label className="field">
            Access token
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoFocus
              required
            />
          </label>
          {error && (
            <div className="pill critical" role="alert">
              {error}
            </div>
          )}
          <button className="btn primary" disabled={busy || !token} style={{ justifyContent: 'center' }}>
            <KeyRound size={16} /> Sign in
          </button>
        </div>
      </form>
    </div>
  )
}
