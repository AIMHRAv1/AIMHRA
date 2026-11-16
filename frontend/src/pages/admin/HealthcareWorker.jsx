import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { adminService } from '../../services/auth'
import { apiError } from '../../api/client'
import { EmptyState, ErrorState, Loading, RiskBadge } from '../../components/ui'
import WorkerAvatar from '../../components/WorkerAvatar'

export default function AdminHealthcareWorker() {
  const { id } = useParams()
  const [activity, setActivity] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setError(null)
    setActivity(null)
    adminService.healthcareWorkerActivity(id)
      .then(setActivity)
      .catch((err) => setError(apiError(err)))
  }, [id])

  useEffect(() => { load() }, [load])

  if (error) {
    return (
      <div className="page">
        <ErrorState error={error} onRetry={load} />
        <Link className="btn btn-secondary" to="/app/admin/users">← All users</Link>
      </div>
    )
  }
  if (!activity) return <div className="page"><Loading /></div>

  const worker = activity.user
  const patients = activity.patients ?? []

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="muted small"><Link to="/app/admin/users">← All users</Link></div>
          <h1>{worker.username}</h1>
          <p className="muted">Healthcare worker activity and assessment summary.</p>
        </div>
      </header>

      <section className="card">
        <h2 className="section-title">Healthcare worker information</h2>
        <div className="worker-profile">
          <WorkerAvatar src={worker.photo_url} name={worker.full_name || worker.username} size={80} />
          <div>
            <strong>{worker.full_name || worker.username}</strong>
            <div className="muted">{worker.username}</div>
          </div>
        </div>
        <dl className="kv kv-lg">
          <div><dt>Username</dt><dd>{worker.username}</dd></div>
          <div><dt>Full name</dt><dd>{worker.full_name || '—'}</dd></div>
          <div><dt>Email</dt><dd>{worker.email || '—'}</dd></div>
          <div><dt>Joined date</dt><dd>{new Date(worker.date_joined).toLocaleDateString()}</dd></div>
          <div><dt>Status</dt><dd>{worker.is_active ? 'Active' : 'Inactive'}</dd></div>
          <div><dt>Patients handled</dt><dd>{worker.patients_handled ?? patients.length}</dd></div>
        </dl>
      </section>

      <section className="card">
        <h2 className="section-title">Assessments performed by patient</h2>
        {patients.length === 0 ? (
          <EmptyState title="No assessments recorded" hint="Patient assessment activity will appear here when this worker records assessments." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Patient ID</th><th>Latest assessment date</th><th>Assessment count</th><th>Latest risk</th></tr>
              </thead>
              <tbody>
                {patients.map((patient) => (
                  <tr key={patient.patient_code}>
                    <td>{patient.patient_code}</td>
                    <td>{patient.last_assessed_date}</td>
                    <td>{patient.assessment_count}</td>
                    <td>{patient.latest_risk ? <RiskBadge level={patient.latest_risk} /> : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
