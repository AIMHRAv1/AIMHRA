import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { assessmentService, patientService } from '../../services/auth'
import { CategoryBadge, EmptyState, ErrorState, Loading, RiskBadge, StatCard } from '../../components/ui'

export default function HcwDashboard() {
  const [patients, setPatients] = useState([])
  const [alerts, setAlerts] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [p, a] = await Promise.all([
          patientService.list(),
          assessmentService.alerts({ status: 'OPEN' }),
        ])
        setPatients(p.results ?? [])
        setAlerts(a.results ?? [])
      } catch (e) { setError(e) } finally { setLoading(false) }
    }
    load()
  }, [])

  if (loading) return <div className="page"><Loading /></div>
  if (error) return <div className="page"><ErrorState error={error} /></div>

  const emergencyCount = alerts.filter((a) => a.category === 'EMERGENCY').length

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Healthcare dashboard</h1>
          <p className="muted">Your assigned patients and their open alerts.</p>
        </div>
        <Link className="btn btn-secondary" to="/app/patients">All patients</Link>
      </header>

      <div className="stat-grid">
        <StatCard label="Assigned patients" value={patients.length} />
        <StatCard label="Open alerts" value={alerts.length} tone={alerts.length ? 'warn' : undefined} />
        <StatCard label="Emergencies" value={emergencyCount} tone={emergencyCount ? 'danger' : undefined} />
      </div>

      <div className="card">
        <h2 className="section-title">High-priority alerts</h2>
        {alerts.length === 0 ? (
          <EmptyState title="No open alerts" hint="Alerts from your patients' assessments will appear here." />
        ) : (
          <table className="data-table">
            <thead><tr><th>Patient</th><th>Category</th><th>Message</th><th>Created</th></tr></thead>
            <tbody>
              {alerts.slice(0, 8).map((a) => (
                <tr key={a.id} className={a.category === 'EMERGENCY' ? 'row-danger' : ''}>
                  <td><Link to={`/app/patients/${a.patient}`}>{a.patient_code}</Link></td>
                  <td><CategoryBadge category={a.category} /></td>
                  <td className="cell-message">{a.message}</td>
                  <td>{new Date(a.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2 className="section-title">Patients</h2>
        {patients.length === 0 ? (
          <EmptyState title="No assigned patients" hint="An administrator can assign patients to you." />
        ) : (
          <table className="data-table">
            <thead><tr><th>Code</th><th>Name</th><th>Username</th><th>Open</th></tr></thead>
            <tbody>
              {patients.slice(0, 6).map((p) => (
                <tr key={p.id}>
                  <td><Link to={`/app/patients/${p.id}`}>{p.patient_code}</Link></td>
                  <td>{p.full_name || '—'}</td>
                  <td className="muted">{p.username}</td>
                  <td>{new Date(p.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
