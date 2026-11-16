import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { adminService } from '../../services/auth'
import { apiError } from '../../api/client'
import { ErrorState, Loading } from '../../components/ui'
import WorkerAvatar from '../../components/WorkerAvatar'

const EMPTY_FORM = {
  username: '',
  email: '',
  full_name: '',
  phone: '',
  password: '',
  photo: null,
}

export default function AdminUsers() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [createRole, setCreateRole] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const isSuperuser = Boolean(currentUser?.is_superuser)

  async function reload() {
    const response = await adminService.users()
    setUsers(response.results ?? response)
  }

  useEffect(() => { reload().catch(setError) }, [])

  function startCreate(role) {
    setForm(EMPTY_FORM)
    setCreateRole(role)
    setNotice(null)
  }

  async function createUser(event) {
    event.preventDefault()
    setNotice(null)
    try {
      const payload = { ...form, role: createRole }
      if (form.photo) {
        const multipart = new FormData()
        Object.entries(payload).forEach(([key, value]) => {
          if (value !== null && value !== '') multipart.append(key, value)
        })
        await adminService.createUser(multipart)
      } else {
        delete payload.photo
        await adminService.createUser(payload)
      }
      setNotice(`Created ${form.username}.`)
      setCreateRole(null)
      setForm(EMPTY_FORM)
      await reload()
    } catch (err) {
      setNotice(apiError(err).message)
    }
  }

  async function toggleActive(account) {
    setNotice(null)
    try {
      await adminService.updateUser(account.id, { is_active: !account.is_active })
      await reload()
    } catch (err) {
      setNotice(apiError(err).message)
    }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!users) return <div className="page"><Loading /></div>

  const administrators = users.filter((account) => account.role === 'ADMIN')
  const healthcareWorkers = users.filter((account) => account.role === 'HEALTHCARE_WORKER')

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Users</h1>
          <p className="muted">Manage administrator and healthcare worker accounts.</p>
        </div>
      </header>

      {notice && <div className="alert alert-info">{notice}</div>}

      <section className="card">
        <div className="page-head">
          <div>
            <h2 className="section-title">Administrators</h2>
            {!isSuperuser && (
              <p className="muted small">Only the initial superuser can create, activate, or deactivate administrator accounts.</p>
            )}
          </div>
          {isSuperuser && (
            <button className="btn btn-secondary" onClick={() => startCreate('ADMIN')}>
              + Create administrator
            </button>
          )}
        </div>
        <table className="data-table">
          <thead>
            <tr><th>Username</th><th>Full name</th><th>Email</th><th>Status</th><th>Joined date</th>{isSuperuser && <th></th>}</tr>
          </thead>
          <tbody>
            {administrators.map((account) => (
              <tr key={account.id} className={!account.is_active ? 'row-muted' : ''}>
                <td>{account.username}{account.is_superuser && <span className="muted small"> · Superuser</span>}</td>
                <td>{account.full_name || '—'}</td>
                <td>{account.email || '—'}</td>
                <td>{account.is_active ? 'Active' : 'Inactive'}</td>
                <td>{new Date(account.date_joined).toLocaleDateString()}</td>
                {isSuperuser && (
                  <td>
                    {!account.is_superuser && (
                      <button className="btn btn-small btn-secondary" onClick={() => toggleActive(account)}>
                        {account.is_active ? 'Deactivate' : 'Reactivate'}
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
            {administrators.length === 0 && <tr><td colSpan={isSuperuser ? 6 : 5} className="muted">No administrator accounts.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="page-head">
          <div>
            <h2 className="section-title">Healthcare workers</h2>
            <p className="muted small">Patient counts include distinct patients with assessments recorded by each worker.</p>
          </div>
          <button className="btn btn-primary" onClick={() => startCreate('HEALTHCARE_WORKER')}>
            + Create new healthcare worker
          </button>
        </div>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr><th>Username</th><th>Full name</th><th>Email</th><th>Patients handled</th><th>Joined date</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {healthcareWorkers.map((account) => (
                <tr key={account.id} className={!account.is_active ? 'row-muted' : ''}>
                  <td><span className="worker-cell"><WorkerAvatar src={account.photo_url} name={account.full_name || account.username} size={30} /><Link to={`/app/admin/users/${account.id}`}>{account.username}</Link></span></td>
                  <td>{account.full_name || '—'}</td>
                  <td>{account.email || '—'}</td>
                  <td>{account.patients_handled ?? 0}</td>
                  <td>{new Date(account.date_joined).toLocaleDateString()}</td>
                  <td>{account.is_active ? 'Active' : 'Inactive'}</td>
                  <td>
                    <button className="btn btn-small btn-secondary" onClick={() => toggleActive(account)}>
                      {account.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                  </td>
                </tr>
              ))}
              {healthcareWorkers.length === 0 && <tr><td colSpan="7" className="muted">No healthcare worker accounts.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {createRole && (
        <form className="card" onSubmit={createUser}>
          <div className="page-head">
            <h2 className="section-title">Create {createRole === 'ADMIN' ? 'administrator' : 'healthcare worker'}</h2>
            <button type="button" className="btn btn-ghost" onClick={() => setCreateRole(null)}>Cancel</button>
          </div>
          <div className="grid-2">
            <label className="field"><span>Username</span><input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} required /></label>
            <label className="field"><span>Email</span><input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required /></label>
            <label className="field"><span>Full name</span><input value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} /></label>
            <label className="field"><span>Phone</span><input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label>
            <label className="field"><span>Password</span><input type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required autoComplete="new-password" /></label>
            {createRole === 'HEALTHCARE_WORKER' && (
              <label className="field">
                <span>Profile photo (optional)</span>
                <input type="file" accept="image/*" onChange={(event) => setForm({ ...form, photo: event.target.files?.[0] ?? null })} />
                <small className="field-hint">Choose an image up to 5 MB.</small>
              </label>
            )}
          </div>
          <div className="form-actions"><button className="btn btn-primary">Create account</button></div>
        </form>
      )}
    </div>
  )
}
