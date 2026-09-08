import { useEffect, useState } from 'react'
import { adminService, patientService } from '../../services/auth'
import { apiError } from '../../api/client'
import { EmptyState, ErrorState, Loading } from '../../components/ui'

export default function AdminUsers() {
  const [users, setUsers] = useState(null)
  const [patients, setPatients] = useState([])
  const [assignments, setAssignments] = useState([])
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [creating, setCreating] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ username: '', email: '', full_name: '', phone: '', role: 'HEALTHCARE_WORKER', password: '' })
  const [assignForm, setAssignForm] = useState({ healthcare_worker: '', patient: '' })

  async function reload() {
    const [u, p, a] = await Promise.all([
      adminService.users(),
      patientService.list(),
      patientService.assignments(),
    ])
    setUsers(u.results ?? u)
    setPatients(p.results ?? [])
    setAssignments(a.results ?? a)
  }

  useEffect(() => { reload().catch(setError) }, [])

  async function createUser(e) {
    e.preventDefault()
    setNotice(null)
    try {
      await adminService.createUser(form)
      setNotice(`Created ${form.username} (${form.role}).`)
      setShowCreate(false)
      setForm({ username: '', email: '', full_name: '', phone: '', role: 'HEALTHCARE_WORKER', password: '' })
      await reload()
    } catch (err) { setNotice(apiError(err).message) }
  }

  async function toggleActive(user) {
    try {
      await adminService.updateUser(user.id, { is_active: !user.is_active })
      await reload()
    } catch (err) { setNotice(apiError(err).message) }
  }

  async function assign(e) {
    e.preventDefault()
    try {
      await patientService.createAssignment({
        healthcare_worker: Number(assignForm.healthcare_worker),
        patient: Number(assignForm.patient),
      })
      setNotice('Patient assigned.')
      setAssignForm({ healthcare_worker: '', patient: '' })
      await reload()
    } catch (err) { setNotice(apiError(err).message) }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!users) return <div className="page"><Loading /></div>

  const workers = users.filter((u) => u.role === 'HEALTHCARE_WORKER' && u.is_active)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Users</h1>
          <p className="muted">Create staff accounts and manage patient assignments.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>＋ New user</button>
      </header>

      {notice && <div className="alert alert-info">{notice}</div>}

      {showCreate && (
        <form className="card" onSubmit={createUser}>
          <h2 className="section-title">Create user</h2>
          <div className="grid-2">
            <label className="field"><span>Username</span><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></label>
            <label className="field"><span>Email</span><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></label>
            <label className="field"><span>Full name</span><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
            <label className="field"><span>Phone</span><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
            <label className="field"><span>Role</span>
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="HEALTHCARE_WORKER">Healthcare worker</option>
                <option value="ADMIN">Administrator</option>
              </select>
            </label>
            <label className="field"><span>Password</span><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required autoComplete="new-password" /></label>
          </div>
          <div className="form-actions"><button className="btn btn-primary">Create</button></div>
        </form>
      )}

      <div className="card">
        <h2 className="section-title">All users</h2>
        <table className="data-table">
          <thead><tr><th>Username</th><th>Email</th><th>Role</th><th>Active</th><th>Joined</th><th></th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={!u.is_active ? 'row-muted' : ''}>
                <td>{u.username}</td><td>{u.email}</td><td>{u.role}</td>
                <td>{u.is_active ? '✓' : '✗'}</td>
                <td>{new Date(u.date_joined).toLocaleDateString()}</td>
                <td><button className="btn btn-small btn-secondary" onClick={() => toggleActive(u)}>{u.is_active ? 'Deactivate' : 'Reactivate'}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2 className="section-title">Patient assignments</h2>
        <form className="assign-form" onSubmit={assign}>
          <select value={assignForm.healthcare_worker} onChange={(e) => setAssignForm({ ...assignForm, healthcare_worker: e.target.value })} required>
            <option value="">— healthcare worker —</option>
            {workers.map((w) => <option key={w.id} value={w.id}>{w.full_name || w.username}</option>)}
          </select>
          <select value={assignForm.patient} onChange={(e) => setAssignForm({ ...assignForm, patient: e.target.value })} required>
            <option value="">— patient —</option>
            {patients.map((p) => <option key={p.id} value={p.id}>{p.patient_code} ({p.full_name || 'Unnamed'})</option>)}
          </select>
          <button className="btn btn-primary">Assign</button>
        </form>
        {assignments.length === 0 ? (
          <EmptyState title="No assignments" hint="Assign patients to healthcare workers to grant access." />
        ) : (
          <table className="data-table">
            <thead><tr><th>Healthcare worker</th><th>Patient</th><th>Assigned</th></tr></thead>
            <tbody>
              {assignments.map((a) => (
                <tr key={a.id}>
                  <td>{a.healthcare_worker_username}</td>
                  <td>{a.patient_code}</td>
                  <td>{new Date(a.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
