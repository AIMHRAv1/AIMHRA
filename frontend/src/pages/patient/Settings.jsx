import { useState } from 'react'
import { authService } from '../../services/auth'
import { apiError } from '../../api/client'

export default function Settings() {
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm: '' })
  const [notice, setNotice] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e) {
    e.preventDefault()
    setError(null)
    setNotice(null)
    if (form.new_password !== form.confirm) {
      setError({ message: 'New passwords do not match.' })
      return
    }
    setBusy(true)
    try {
      await authService.changePassword({
        current_password: form.current_password,
        new_password: form.new_password,
      })
      setNotice('Password changed successfully.')
      setForm({ current_password: '', new_password: '', confirm: '' })
    } catch (err) {
      setError(apiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Account security.</p>
        </div>
      </header>
      {notice && <div className="alert alert-success">{notice}</div>}
      {error && <div className="alert alert-error" role="alert">{error.message}</div>}
      <form className="card narrow" onSubmit={onSubmit}>
        <label className="field"><span>Current password</span>
          <input type="password" value={form.current_password} autoComplete="current-password" required
                 onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></label>
        <label className="field"><span>New password</span>
          <input type="password" value={form.new_password} autoComplete="new-password" required
                 onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></label>
        <label className="field"><span>Confirm new password</span>
          <input type="password" value={form.confirm} autoComplete="new-password" required
                 onChange={(e) => setForm({ ...form, confirm: e.target.value })} /></label>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Changing…' : 'Change password'}</button>
        </div>
      </form>
    </div>
  )
}
