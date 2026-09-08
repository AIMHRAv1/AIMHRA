import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { adminService } from '../../services/auth'
import { ErrorState, Loading, RiskBadge } from '../../components/ui'

export default function WorkerProfile() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { adminService.workerProfile(id).then(setData).catch(setError) }, [id])
  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!data) return <div className="page"><Loading /></div>
  const user = data.user
  return (
    <div className="page">
      <div className="muted small"><Link to="/app/admin/users">← Users</Link></div>
      <h1>{user.full_name || user.username}</h1>
      <div className="card">
        <dl className="kv kv-lg">
          <div><dt>Username</dt><dd>{user.username}</dd></div>
          <div><dt>Email</dt><dd>{user.email}</dd></div>
          <div><dt>Phone</dt><dd>{user.phone || '—'}</dd></div>
          <div><dt>Status</dt><dd>{user.is_active ? 'Active' : 'Inactive'}</dd></div>
        </dl>
      </div>
      <div className="card">
        <h2 className="section-title">Assessments performed</h2>
        {data.assessments.length === 0 ? <p className="muted">No assessments recorded.</p> : (
          <table className="data-table">
            <thead><tr><th>Patient</th><th>Date</th><th>Risk</th></tr></thead>
            <tbody>{data.assessments.map((a) => <tr key={a.id}><td>{a.patient_code}</td><td>{a.visit_date}</td><td>{a.risk_level ? <RiskBadge level={a.risk_level} /> : '—'}</td></tr>)}</tbody>
          </table>
        )}
      </div>
    </div>
  )
}
