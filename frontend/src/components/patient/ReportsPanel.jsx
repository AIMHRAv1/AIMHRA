import { useCallback, useEffect, useState } from 'react'
import { reportService } from '../../services/auth'
import { apiError } from '../../api/client'
import { EmptyState, ErrorState, Loading } from '../ui'
import { downloadReport } from '../../utils/reportDownload'

export default function ReportsPanel({ patientId }) {
  const [reports, setReports] = useState(null)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)

  const load = useCallback(() => {
    setError(null)
    setReports(null)
    reportService.list({ patient: patientId })
      .then((d) => setReports(d.reports ?? []))
      .catch(setError)
  }, [patientId])

  useEffect(() => { load() }, [load])

  async function onDownload(id) {
    setBusyId(id)
    try {
      await downloadReport(id)
    } catch (e) {
      setError(apiError(e))
    } finally {
      setBusyId(null)
    }
  }

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!reports) return <Loading />

  return (
    <div className="card">
      <h2 className="section-title">PDF reports for this patient</h2>
      {reports.length === 0 ? (
        <EmptyState title="No reports yet" hint="Generate a PDF from any assessment in the History tab." />
      ) : (
        <table className="data-table">
          <thead><tr><th>Report</th><th>Patient</th><th>Created</th><th>Download</th></tr></thead>
          <tbody>
            {reports.map((r) => (
              <tr key={r.id}>
                <td>{(r.filename || '').split('/').pop() || `Report #${r.id}`}</td>
                <td>{r.patient_code}{r.patient_name ? ` · ${r.patient_name}` : ''}</td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>
                  <button className="btn btn-small btn-secondary" disabled={busyId === r.id}
                          onClick={() => onDownload(r.id)}>
                    {busyId === r.id ? '…' : 'PDF ↓'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}