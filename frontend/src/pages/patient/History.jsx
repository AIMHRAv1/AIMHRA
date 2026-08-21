import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { assessmentService, reportService } from '../../services/auth'
import { RiskTrendChart } from '../../charts'
import { Disclaimer, EmptyState, ErrorState, Loading, RiskBadge } from '../../components/ui'

export default function History() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [notice, setNotice] = useState(null)

  useEffect(() => {
    assessmentService.trend()
      .then(setData)
      .catch(setError)
  }, [])

  async function generateReport(assessmentId) {
    setBusyId(assessmentId)
    setNotice(null)
    try {
      await reportService.generate(assessmentId)
      setNotice('Report generated — open the Reports page to download it.')
    } catch (e) {
      setNotice(e?.message || 'Report generation failed.')
    } finally {
      setBusyId(null)
    }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!data) return <div className="page"><Loading /></div>

  const series = data.series ?? []
  const trend = data.trend

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Risk history & trend</h1>
          <p className="muted">{series.length} assessment{series.length === 1 ? '' : 's'} recorded</p>
        </div>
        <Link className="btn btn-primary" to="/app/assessment">＋ New assessment</Link>
      </header>

      {notice && <div className="alert alert-info">{notice}</div>}

      {series.length === 0 ? (
        <EmptyState title="No assessments yet" hint="Your history will appear here after your first assessment." />
      ) : (
        <>
          <div className="card">
            <h2 className="section-title">Risk category over time</h2>
            <RiskTrendChart series={series} />
            <p className="muted small">
              Sequence: {trend.sequence.join(' → ')} · status <b>{trend.status}</b>
            </p>
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
                        {busyId === s.id ? '…' : 'PDF'}
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
