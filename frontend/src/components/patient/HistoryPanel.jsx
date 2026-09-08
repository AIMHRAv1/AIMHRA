import { useCallback, useEffect, useState } from 'react'
import { assessmentService, reportService } from '../../services/auth'
import { apiError } from '../../api/client'
import { RiskTrendChart } from '../../charts'
import { Disclaimer, EmptyState, ErrorState, Loading, RiskBadge } from '../ui'
import { downloadReport } from '../../utils/reportDownload'

export default function HistoryPanel({ patientId }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [notice, setNotice] = useState(null)

  const load = useCallback(() => {
    setError(null)
    setData(null)
    assessmentService.trend(patientId)
      .then(setData)
      .catch(setError)
  }, [patientId])

  useEffect(() => { load() }, [load])

  async function generateReport(assessmentId) {
    setBusyId(assessmentId)
    setNotice(null)
    try {
      const d = await reportService.generate(assessmentId)
      await downloadReport(d.report.id)
      setNotice('Report generated and downloaded.')
    } catch (e) {
      setNotice(apiError(e).message || 'Report generation failed.')
    } finally {
      setBusyId(null)
    }
  }

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!data) return <Loading />

  const series = data.series ?? []
  const trend = data.trend

  return (
    <div className="stack">
      {notice && <div className="alert alert-info">{notice}</div>}

      {series.length === 0 ? (
        <EmptyState title="No assessments yet" hint="Complete a New Assessment to start the patient's risk history." />
      ) : (
        <>
          <div className="card">
            <h2 className="section-title">Risk category over time</h2>
            <RiskTrendChart series={series} />
            <p className="muted small">
              Sequence: {trend.sequence.join(' → ')} · status <b>{trend.status}</b>
            </p>
            <p className="muted small">Trends describe stored assessments only — the system does not predict future risk.</p>
          </div>

          <div className="card">
            <h2 className="section-title">All assessments</h2>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Visit date</th><th>Gest. week</th><th>Risk</th><th>Confidence</th><th>Model</th><th>Report</th>
                </tr>
              </thead>
              <tbody>
                {series.map((s) => (
                  <tr key={s.id}>
                    <td>{s.visit_date}</td>
                    <td>{s.gestational_week ?? '—'}</td>
                    <td><RiskBadge level={s.risk_level} /></td>
                    <td>{Math.round(s.probability * 100)}%</td>
                    <td className="muted small">{s.model}</td>
                    <td>
                      <button className="btn btn-small btn-secondary" disabled={busyId === s.id}
                              onClick={() => generateReport(s.id)}>
                        {busyId === s.id ? '…' : 'PDF ↓'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <Disclaimer />
    </div>
  )
}