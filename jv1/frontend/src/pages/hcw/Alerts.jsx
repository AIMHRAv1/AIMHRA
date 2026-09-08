import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { assessmentService } from '../../services/auth'
import { CategoryBadge, EmptyState, ErrorState, Loading } from '../../components/ui'

export default function Alerts() {
  const [alerts, setAlerts] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    assessmentService.alerts({ status: 'OPEN' })
      .then((d) => setAlerts(d.results ?? []))
      .catch(setError)
  }, [])

  async function acknowledge(id, status) {
    try {
      await assessmentService.ackAlert(id, status)
      setAlerts((a) => a.filter((x) => x.id !== id))
    } catch (e) { alert(e?.message || 'Failed') }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!alerts) return <div className="page"><Loading /></div>

  const shown = filter ? alerts.filter((a) => a.category === filter) : alerts
  const rank = { EMERGENCY: 0, HIGH_CONCERN: 1, ATTENTION: 2, NORMAL: 3 }
  shown.sort((a, b) => (rank[a.category] ?? 4) - (rank[b.category] ?? 4))

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Risk alerts</h1>
          <p className="muted">Open rule-based alerts for your patients, most severe first.</p>
        </div>
        <select className="search" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by category">
          <option value="">All categories</option>
          <option value="EMERGENCY">Emergency</option>
          <option value="HIGH_CONCERN">High concern</option>
          <option value="ATTENTION">Attention</option>
        </select>
      </header>

      {shown.length === 0 ? (
        <EmptyState title="No open alerts" hint="Rule-based alerts from patient assessments will appear here." />
      ) : (
        <div className="card">
          <table className="data-table">
            <thead><tr><th>Patient</th><th>Category</th><th>Rules</th><th>Message</th><th>Created</th><th>Actions</th></tr></thead>
            <tbody>
              {shown.map((a) => (
                <tr key={a.id} className={a.category === 'EMERGENCY' ? 'row-danger' : a.category === 'HIGH_CONCERN' ? 'row-warn' : ''}>
                  <td><Link to={`/app/patients/${a.patient}`}>{a.patient_code}</Link></td>
                  <td><CategoryBadge category={a.category} /></td>
                  <td><code className="small">{a.rule_id}</code></td>
                  <td className="cell-message">{a.message}</td>
                  <td>{new Date(a.created_at).toLocaleString()}</td>
                  <td className="cell-actions">
                    <button className="btn btn-small" onClick={() => acknowledge(a.id, 'ACKNOWLEDGED')}>Ack</button>
                    <button className="btn btn-small btn-secondary" onClick={() => acknowledge(a.id, 'RESOLVED')}>Resolve</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
