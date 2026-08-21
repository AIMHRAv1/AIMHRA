import { useEffect, useState } from 'react'
import { reportService } from '../../services/auth'
import { EmptyState, ErrorState, Loading } from '../../components/ui'

export default function Reports() {
  const [reports, setReports] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    reportService.list().then((d) => setReports(d.reports ?? [])).catch(setError)
  }, [])

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!reports) return <div className="page"><Loading /></div>

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Reports</h1>
          <p className="muted">PDF summaries of your assessments. Generated reports are decision-support documents, not diagnoses.</p>
        </div>
      </header>
      {reports.length === 0 ? (
        <EmptyState title="No reports yet" hint="Generate a report from the Risk History page." />
      ) : (
        <div className="card">
          <table className="data-table">
            <thead><tr><th>Report</th><th>Patient code</th><th>Created</th><th>Download</th></tr></thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td>{(r.filename || '').split('/').pop() || `Report #${r.id}`}</td>
                  <td>{r.patient_code}</td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td>
                    <a className="btn btn-small btn-secondary" href={mediaUrl(r.filename)} download>PDF ↓</a>
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

function mediaUrl(filename) {
  return `/media/${(filename || '').replace(/^.*reports\//, 'reports/')}`
}
