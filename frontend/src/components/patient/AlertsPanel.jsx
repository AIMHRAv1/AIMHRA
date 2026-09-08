import { useCallback, useEffect, useState } from 'react'
import { assessmentService } from '../../services/auth'
import { apiError } from '../../api/client'
import { CategoryBadge, EmptyState, ErrorState, Loading } from '../ui'

export default function AlertsPanel({ patientId, showStatus = 'ALL' }) {
  const [alerts, setAlerts] = useState(null)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)

  const load = useCallback(() => {
    setError(null)
    setAlerts(null)
    const params = { patient: patientId }
    if (showStatus !== 'ALL') params.status = showStatus
    assessmentService.alerts(params)
      .then((d) => setAlerts(d.results ?? []))
      .catch(setError)
  }, [patientId, showStatus])

  useEffect(() => { load() }, [load])

  async function acknowledge(id, status) {
    setBusyId(id)
    setError(null)
    try {
      await assessmentService.ackAlert(id, status)
      setAlerts((a) => a.map((x) => (x.id === id ? { ...x, status } : x)))
    } catch (e) {
      setError(apiError(e))
    } finally {
      setBusyId(null)
    }
  }

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!alerts) return <Loading />

  const rank = { EMERGENCY: 0, HIGH_CONCERN: 1, ATTENTION: 2, NORMAL: 3 }
  const shown = [...alerts].sort((a, b) => (rank[a.category] ?? 4) - (rank[b.category] ?? 4))

  if (shown.length === 0) {
    return <EmptyState title="No alerts" hint="Rule-based alerts triggered by this patient's assessments appear here." />
  }

  return (
    <div className="card">
      <h2 className="section-title">Alerts for this patient</h2>
      <ul className="alert-list">
        {shown.map((a) => (
          <li key={a.id} className={`alert-item cat-${a.category}`}>
            <CategoryBadge category={a.category} />
            <span>{a.message}</span>
            <span className="muted small">
              {new Date(a.created_at).toLocaleString()} · <code>{a.rule_id || 'rule'}</code> · {a.status}
            </span>
            {(a.status === 'OPEN' || a.status === 'ACKNOWLEDGED') && (
              <span className="cell-actions">
                <button className="btn btn-small" disabled={busyId === a.id}
                        onClick={() => acknowledge(a.id, 'ACKNOWLEDGED')}>Acknowledge</button>
                <button className="btn btn-small btn-secondary" disabled={busyId === a.id}
                        onClick={() => acknowledge(a.id, 'RESOLVED')}>Resolve</button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}