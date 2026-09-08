import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { assessmentService, patientService } from '../../services/auth'
import { CategoryBadge, EmptyState, ErrorState, Loading, RiskBadge, StatCard } from '../../components/ui'

export default function HcwDashboard() {
  const [patients, setPatients] = useState([])
  const [alerts, setAlerts] = useState([])
  const [recent, setRecent] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [p, a, r] = await Promise.all([
        patientService.list(),
        assessmentService.alerts({ status: 'OPEN' }),
        assessmentService.list({}),
      ])
      setPatients(p.results ?? [])
      setAlerts((a.results ?? a.alerts ?? []))
      const list = r.results ?? []
      setRecent(
        [...list].sort((x, y) => (y.visit_date || '').localeCompare(x.visit_date || '') || y.id - x.id).slice(0, 6),
      )
    } catch (e) { setError(e) } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="page"><Loading /></div>
  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>

  const riskCount = (level) => patients.filter((p) => p.current_risk === level).length
  const emergencyCount = alerts.filter((a) => a.category === 'EMERGENCY').length
  const highPriority = patients.filter((p) => p.current_risk === 'high risk')
  const recentlyAdded = [...patients].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 5)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Healthcare dashboard</h1>
          <p className="muted">Your patients, their current risk and open rule-based alerts.</p>
        </div>
        <div className="quick-actions">
          <Link className="btn btn-primary" to="/app/patients/new">＋ Add Patient</Link>
          <Link className="btn btn-secondary" to="/app/patients">All patients</Link>
          <Link className="btn btn-secondary" to="/app/alerts">Risk alerts</Link>
          <Link className="btn btn-secondary" to="/app/reports">Reports</Link>
        </div>
      </header>

      <div className="stat-grid">
        <StatCard label="Total patients" value={patients.length} sub="Created or assigned" />
        <StatCard label="High-risk patients" value={riskCount('high risk')} tone={riskCount('high risk') ? 'danger' : undefined} />
        <StatCard label="Mid-risk patients" value={riskCount('mid risk')} tone={riskCount('mid risk') ? 'warn' : undefined} />
        <StatCard label="Low-risk patients" value={riskCount('low risk')} tone="good" />
        <StatCard label="Open alerts" value={alerts.length} tone={alerts.length ? 'warn' : undefined} />
        <StatCard label="Emergency alerts" value={emergencyCount} tone={emergencyCount ? 'danger' : undefined} />
      </div>

      <div className="card">
        <h2 className="section-title">High-priority alerts</h2>
        {alerts.length === 0 ? (
          <EmptyState title="No open alerts" hint="Alerts from your patients' assessments will appear here." />
        ) : (
          <table className="data-table">
            <thead><tr><th>Patient</th><th>Category</th><th>Message</th><th>Created</th><th></th></tr></thead>
            <tbody>
              {alerts.slice(0, 8).map((a) => (
                <tr key={a.id} className={a.category === 'EMERGENCY' ? 'row-danger' : a.category === 'HIGH_CONCERN' ? 'row-warn' : ''}>
                  <td><Link to={`/app/patients/${a.patient}?tab=overview`}>{a.patient_code}</Link></td>
                  <td><CategoryBadge category={a.category} /></td>
                  <td className="cell-message">{a.message}</td>
                  <td>{new Date(a.created_at).toLocaleString()}</td>
                  <td><Link className="btn btn-small btn-secondary" to={`/app/patients/${a.patient}?tab=alerts`}>Manage</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid-2-cards">
        <div className="card">
          <h2 className="section-title">High-priority patients</h2>
          {highPriority.length === 0 ? (
            <EmptyState title="No high-risk patients" hint="Patients whose latest stored assessment is high risk appear here." />
          ) : (
            <ul className="alert-list">
              {highPriority.slice(0, 5).map((p) => (
                <li key={p.id} className="alert-item cat-HIGH_CONCERN">
                  <RiskBadge level={p.current_risk} />
                  <Link to={`/app/patients/${p.id}?tab=overview`}>{p.patient_code || p.full_name}</Link>
                  <span className="muted small">{p.full_name}{p.current_confidence != null && ` · ${Math.round(p.current_confidence * 100)}% confidence`}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <h2 className="section-title">Recently added patients</h2>
          {recentlyAdded.length === 0 ? (
            <EmptyState title="No patients yet" hint="Add your first patient record."
                        action={<Link className="btn btn-primary" to="/app/patients/new">＋ Add Patient</Link>} />
          ) : (
            <ul className="alert-list">
              {recentlyAdded.map((p) => (
                <li key={p.id} className="alert-item">
                  <Link to={`/app/patients/${p.id}?tab=overview`}>{p.patient_code}</Link>
                  <span>{p.full_name || 'Unnamed'} · {new Date(p.created_at).toLocaleDateString()}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card">
        <h2 className="section-title">Recent assessments</h2>
        {recent.length === 0 ? (
          <EmptyState title="No assessments yet" hint="Assessments across your patients will appear here." />
        ) : (
          <table className="data-table">
            <thead><tr><th>Visit date</th><th>Patient</th><th>Risk</th><th>Confidence</th><th></th></tr></thead>
            <tbody>
              {recent.map((a) => (
                <tr key={a.id}>
                  <td>{a.visit_date}</td>
                  <td>{a.patient_name ? `${a.patient_code ?? ''} · ${a.patient_name}` : `#${a.patient}`}</td>
                  <td>{a.prediction && <RiskBadge level={a.prediction.risk_level} />}</td>
                  <td>{a.prediction ? `${Math.round(a.prediction.probability * 100)}%` : '—'}</td>
                  <td><Link className="btn btn-small btn-secondary" to={`/app/patients/${a.patient}?tab=overview`}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}