import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { apiError } from '../../api/client'
import { useAuth } from '../../context/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(form.username, form.password)
      navigate(location.state?.from?.pathname || '/app/dashboard', { replace: true })
    } catch (err) {
      setError(apiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={onSubmit} noValidate>
        <div className="brand auth-brand">
          <span className="brand-mark" aria-hidden="true">✚</span>
          <div>
            <div className="brand-name">AIMHRA</div>
            <div className="brand-sub">Maternal Health Decision Support</div>
          </div>
        </div>
        <h1>Sign in</h1>
        {error && <div className="alert alert-error" role="alert">{error.message}</div>}
        <label className="field">
          <span>Username</span>
          <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
                 autoComplete="username" required autoFocus />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
                 autoComplete="current-password" required />
        </label>
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="auth-alt">Healthcare-worker and administrator accounts are created by an administrator.</p>
        <p className="disclaimer">Decision-support system for education and screening support — not a replacement for professional medical care.</p>
      </form>
    </div>
  )
}
