import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { reportService } from '../../services/auth'
import { EmptyState, ErrorState, Loading } from '../../components/ui'

export default function HcwReports() {
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
          <p className="muted">PDF assessment reports for your authorized patients.</p>
        </div>
      </header>
      {reports.length === 0 ? (
        <EmptyState title="No reports" hint="Generate reports from a patient's detail page." />
      ) : (
        <div className="card">
          <table className="data-table">
            <thead><tr><th>Report</th><th>Patient</th><th>Created</th><th>Download</th></tr></thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td>{(r.filename || '').split('/').pop() || `Report #${r.id}`}</td>
                  <td><Link to={`/app/patients/${r.patient}`}>{r.patient_code}</Link></td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td><a className="btn btn-small btn-secondary" href={`/media/${(r.filename || '').replace(/^.*reports\//, 'reports/')}`} download>PDF ↓</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
