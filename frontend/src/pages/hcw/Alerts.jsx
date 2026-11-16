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
        <div className="card global-alert-list">
          <div className="global-alert-head" aria-hidden="true">
            <span>Patient</span><span>Category</span><span>Alert</span><span>Actions</span>
          </div>
          {shown.map((a) => (
            <article
              key={a.id}
              className={`global-alert-row${a.category === 'EMERGENCY' ? ' is-emergency' : a.category === 'HIGH_CONCERN' ? ' is-high-concern' : ''}`}
            >
              <div className="global-alert-patient">
                <Link to={`/app/patients/${a.patient}?tab=overview`}>{a.patient_code}</Link>
                <time dateTime={a.created_at}>{new Date(a.created_at).toLocaleDateString()}</time>
              </div>
              <div><CategoryBadge category={a.category} /></div>
              <p className="global-alert-message" title={`${a.rule_id}: ${a.message}`}>
                <strong>{a.rule_description || a.rule_id}</strong>
                <span>{a.message}</span>
              </p>
              <div className="global-alert-actions">
                <Link className="btn btn-small btn-secondary" to={`/app/patients/${a.patient}?tab=alerts`}>View</Link>
                <button className="btn btn-small" onClick={() => acknowledge(a.id, 'ACKNOWLEDGED')}>Ack</button>
                <button className="btn btn-small btn-secondary" onClick={() => acknowledge(a.id, 'RESOLVED')}>Resolve</button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
