import { useCallback, useEffect, useState } from 'react'
import { assessmentService, reportService } from '../../services/auth'
import { apiError } from '../../api/client'
import { RiskTrendChart } from '../../charts'
import { Disclaimer, EmptyState, ErrorState, Loading, RiskBadge } from '../ui'
import { downloadReport } from '../../utils/reportDownload'
import MeasurementHistory from './MeasurementHistory'
import RecommendationsPanel from './RecommendationsPanel'

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
            <RiskTrendChart series={series.filter((item) => item.risk_level)} />
            <p className="muted small">
              Latest risk: <b>{trend.current || 'Not available'}</b>
              {trend.previous && <> · previous: <b>{trend.previous}</b> · change <b>{trend.direction}</b></>}
              {!trend.previous && trend.current && <> · baseline (no previous prediction)</>}
              {!trend.current && <> · no prediction recorded for the latest assessment</>}
            </p>
            <p className="muted small">
              Sequence: {(trend.sequence || []).join(' → ') || 'No predictions recorded'} · status <b>{trend.status}</b>
            </p>
            <p className="muted small">Trends describe stored assessments only — the system does not predict future risk.</p>
          </div>

          <MeasurementHistory series={series} changes={data.measurement_trends} />

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
                  <tr key={s.assessment_id}>
                    <td>{s.visit_date}</td>
                    <td>{s.gestational_week ?? '—'}</td>
                    <td>{s.risk_level ? <RiskBadge level={s.risk_level} /> : '—'}</td>
                    <td>{s.probability == null ? '—' : `${Math.round(s.probability * 100)}%`}</td>
                    <td className="muted small">{s.model || '—'}</td>
                    <td>
                      <button className="btn btn-small btn-secondary" disabled={!s.id || busyId === s.id}
                              onClick={() => generateReport(s.id)}>
                        {!s.id ? 'No prediction' : busyId === s.id ? '…' : 'PDF ↓'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {series.filter((item) => Object.values(item.recommendations || {}).some((entries) => entries.length))
            .map((item) => (
              <div key={item.assessment_id}>
                <h2 className="section-title">Recommendations from {item.visit_date}</h2>
                <RecommendationsPanel recommendations={item.recommendations} />
              </div>
            ))}
        </>
      )}
      <Disclaimer />
    </div>
  )
}