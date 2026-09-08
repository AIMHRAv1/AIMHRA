import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminService } from '../../services/auth'
import { apiError } from '../../api/client'
import { ErrorState, Loading } from '../../components/ui'

const EMPTY_FORM = { username: '', email: '', full_name: '', phone: '', role: 'HEALTHCARE_WORKER', password: '' }

export default function AdminUsers() {
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [showCreate, setShowCreate] = useState(false)

  async function reload() {
    const data = await adminService.users()
    setUsers(data.results ?? data)
  }

  useEffect(() => { reload().catch(setError) }, [])

  function openCreate(role) {
    setNotice(null)
    setForm({ ...EMPTY_FORM, role })
    setShowCreate(true)
  }

  async function createUser(e) {
    e.preventDefault()
    try {
      await adminService.createUser(form)
      setNotice(`Created ${form.username}.`)
      setForm(EMPTY_FORM)
      setShowCreate(false)
      await reload()
    } catch (err) {
      setNotice(apiError(err).message)
    }
  }

  async function toggleActive(user) {
    try {
      await adminService.updateUser(user.id, { is_active: !user.is_active })
      await reload()
    } catch (err) {
      setNotice(apiError(err).message)
    }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!users) return <div className="page"><Loading /></div>

  const admins = users.filter((u) => u.role === 'ADMIN')
  const workers = users.filter((u) => u.role === 'HEALTHCARE_WORKER')

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Users</h1>
          <p className="muted">Manage administrator and healthcare-worker accounts.</p>
        </div>
      </header>
      {notice && <div className="alert alert-info">{notice}</div>}
      {showCreate && (
        <form className="card" onSubmit={createUser}>
          <h2 className="section-title">Create {form.role === 'ADMIN' ? 'administrator' : 'healthcare worker'}</h2>
          <div className="grid-2">
            <label className="field"><span>Username</span><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></label>
            <label className="field"><span>Email</span><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></label>
            <label className="field"><span>Full name</span><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
            <label className="field"><span>Phone</span><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
            <label className="field"><span>Password</span><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required autoComplete="new-password" /></label>
          </div>
          <div className="form-actions"><button className="btn btn-primary">Create</button><button type="button" className="btn btn-secondary" onClick={() => { setForm(EMPTY_FORM); setShowCreate(false) }}>Cancel</button></div>
        </form>
      )}
      <UserSection title="Administrators" users={admins} onCreate={() => openCreate('ADMIN')} onToggle={toggleActive} />
      <UserSection title="Healthcare workers" users={workers} onCreate={() => openCreate('HEALTHCARE_WORKER')} onToggle={toggleActive} showPatients />
    </div>
  )
}

function UserSection({ title, users, onCreate, onToggle, showPatients }) {
  return (
    <div className="card">
      <div className="page-head">
        <h2 className="section-title">{title}</h2>
        <button className="btn btn-primary" onClick={onCreate}>＋ New {showPatients ? 'healthcare worker' : 'administrator'}</button>
      </div>
      <table className="data-table">
        <thead><tr><th>Username</th><th>Full name</th><th>Email</th>{showPatients && <th>Patients handled</th>}<th>Active</th><th>Joined</th><th></th></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={!u.is_active ? 'row-muted' : ''}>
              <td>{showPatients ? <Link to={`/app/admin/users/${u.id}`}>{u.username}</Link> : u.username}</td>
              <td>{u.full_name || '—'}</td><td>{u.email}</td>
              {showPatients && <td>{u.patients_handled_count ?? 0}</td>}
              <td>{u.is_active ? '✓' : '✗'}</td><td>{new Date(u.date_joined).toLocaleDateString()}</td>
              <td><button className="btn btn-small btn-secondary" onClick={() => onToggle(u)}>{u.is_active ? 'Deactivate' : 'Reactivate'}</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
