import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiError } from '../../api/client'
import { useAuth } from '../../context/AuthContext'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({
    username: '', email: '', full_name: '', phone: '', password: '', confirm_password: '',
  })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  function set(k) {
    return (e) => setForm({ ...form, [k]: e.target.value })
  }

  async function onSubmit(e) {
    e.preventDefault()
    setError(null)
    if (form.password !== form.confirm_password) {
      setError({ message: 'Passwords do not match.' })
      return
    }
    setBusy(true)
    try {
      await register(form)
      navigate('/app/dashboard', { replace: true })
    } catch (err) {
      setError(apiError(err))
    } finally {
      setBusy(false)
    }
  }

  const details = error?.details

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={onSubmit} noValidate>
        <h1>Create your account</h1>
        <p className="muted">Patient accounts can complete risk assessments, track trends and ask the assistant questions.</p>
        {error && (
          <div className="alert alert-error" role="alert">
            {error.message}
            {details && typeof details === 'object' && (
              <ul className="error-detail">
                {Object.entries(details).map(([k, v]) => <li key={k}>{k}: {Array.isArray(v) ? v.join(', ') : String(v)}</li>)}
              </ul>
            )}
          </div>
        )}
        <div className="grid-2">
          <label className="field"><span>Full name</span>
            <input value={form.full_name} onChange={set('full_name')} required /></label>
          <label className="field"><span>Phone</span>
            <input value={form.phone} onChange={set('phone')} placeholder="+94 …" /></label>
        </div>
        <label className="field"><span>Username</span>
          <input value={form.username} onChange={set('username')} autoComplete="username" required /></label>
        <label className="field"><span>Email</span>
          <input type="email" value={form.email} onChange={set('email')} autoComplete="email" required /></label>
        <div className="grid-2">
          <label className="field"><span>Password</span>
            <input type="password" value={form.password} onChange={set('password')} autoComplete="new-password" required /></label>
          <label className="field"><span>Confirm password</span>
            <input type="password" value={form.confirm_password} onChange={set('confirm_password')} autoComplete="new-password" required /></label>
        </div>
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Creating account…' : 'Create account'}
        </button>
        <p className="auth-alt">Already registered? <Link to="/login">Sign in</Link></p>
        <p className="disclaimer">Healthcare-worker and administrator accounts are created by an administrator.</p>
      </form>
    </div>
  )
}
