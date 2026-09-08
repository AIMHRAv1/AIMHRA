import { useEffect, useState } from 'react'
import { adminService } from '../../services/auth'
import { EmptyState, ErrorState, Loading } from '../../components/ui'

const ACTIONS = [
  'LOGIN', 'LOGIN_FAILED', 'PROFILE_UPDATED', 'PASSWORD_CHANGED',
  'ASSESSMENT_CREATED', 'PREDICTION', 'RULE_ESCALATION', 'CHAT_ACCESS',
  'REPORT_GENERATED', 'MODEL_TRAINED', 'MODEL_ACTIVATED', 'KB_UPLOADED',
  'KB_REINDEXED', 'KB_DELETED', 'USER_UPDATED', 'PATIENT_ASSIGNED',
  'PATIENT_CREATED', 'PATIENT_UPDATED',
]

export default function AdminAudit() {
  const [logs, setLogs] = useState(null)
  const [count, setCount] = useState(0)
  const [error, setError] = useState(null)
  const [action, setAction] = useState('')
  const [username, setUsername] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => {
    adminService.auditLogs({ action: action || undefined, username: username || undefined, page })
      .then((d) => { setLogs(d.results ?? []); setCount(d.count ?? 0) })
      .catch(setError)
  }, [action, username, page])

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!logs) return <div className="page"><Loading /></div>

  const pages = Math.max(1, Math.ceil(count / 20))

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Audit logs</h1>
          <p className="muted">{count} events — non-sensitive action records only.</p>
        </div>
        <div className="filters">
          <select className="search" value={action} onChange={(e) => { setAction(e.target.value); setPage(1) }} aria-label="Filter by action">
            <option value="">All actions</option>
            {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <input className="search" placeholder="Username…" value={username}
                 onChange={(e) => { setUsername(e.target.value); setPage(1) }} aria-label="Filter by username" />
        </div>
      </header>

      {logs.length === 0 ? (
        <EmptyState title="No matching events" />
      ) : (
        <div className="card">
          <table className="data-table">
            <thead><tr><th>Time</th><th>Actor</th><th>Event</th><th>Target</th><th>What happened</th></tr></thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td>{new Date(l.created_at).toLocaleString()}</td>
                  <td>{l.actor || l.username || <span className="muted">System</span>}</td>
                  <td>{l.action_label || l.action}</td>
                  <td className="muted small">{l.target_label || l.target_type}</td>
                  <td className="cell-detail">{l.summary || 'Event recorded.'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button className="btn btn-small btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Prev</button>
            <span>Page {page} / {pages}</span>
            <button className="btn btn-small btn-secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}
