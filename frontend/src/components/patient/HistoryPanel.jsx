import { useCallback, useEffect, useState } from 'react'
import { assessmentService, reportService } from '../../services/auth'
import { apiError } from '../../api/client'
import { RiskTrendChart } from '../../charts'
import { Disclaimer, EmptyState, ErrorState, Loading, RiskBadge } from '../ui'
import { downloadReport } from '../../utils/reportDownload'

export default function HistoryPanel({ patientId, showReportActions = true }) {
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
  const measurements = data.measurements
  const comparisons = measurements?.comparisons ?? []

  return (
    <div className="stack">
      {notice && <div className="alert alert-info">{notice}</div>}

      {Array.isArray(data.treating_workers) && data.treating_workers.length > 0 && (
        <div className="card">
          <h2 className="section-title">Treating health workers</h2>
          <p className="muted">
            {data.treating_workers.join(', ')}
          </p>
          <p className="muted small">Record creator and the workers who recorded each assessment, most recent first.</p>
        </div>
      )}

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

          {measurements && measurements.visits?.length > 0 && (
            <div className="card">
              <h2 className="section-title">Measurements across visits</h2>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Measurement</th>
                      {measurements.visits.map((v) => (
                        <th key={v.assessment_id}>{v.visit_date}</th>
                      ))}
                      <th>Change vs previous</th>
                    </tr>
                  </thead>
                  <tbody>
                    {measurements.features.map((feature) => {
                      const cmp = comparisons.find((c) => c.feature === feature)
                      return (
                        <tr key={feature}>
                          <td>{cmp?.label ?? feature}</td>
                          {measurements.visits.map((v) => (
                            <td key={v.assessment_id}>{v[feature]}</td>
                          ))}
                          <td>
                            {cmp ? (
                              <>
                                {cmp.delta > 0 ? '+' : ''}{cmp.delta ?? '—'}
                                {cmp.percent_change != null && (
                                  <span className="muted small"> ({cmp.percent_change > 0 ? '+' : ''}{cmp.percent_change}%)</span>
                                )}
                                <span className="muted small"> {cmp.direction}</span>
                              </>
                            ) : <span className="muted small">first visit</span>}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p className="muted small">{measurements.note}.</p>
              {data.measurement_rules && !data.measurement_rules.active && (
                <p className="muted small">
                  Measurement-change alerts are configured but not yet clinically reviewed, so no trend alerts are generated.
                </p>
              )}
              {data.measurement_rules?.triggered?.length > 0 && (
                <ul className="rule-list">
                  {data.measurement_rules.triggered.map((t) => (
                    <li key={t.id}><code>{t.id}</code> {t.description} — {t.feature} changed by {t.delta}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="card">
            <h2 className="section-title">All assessments</h2>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Visit date</th><th>Gest. week</th><th>Risk</th><th>Confidence</th>
                  <th>Recorded by</th><th>Model</th>
                  {showReportActions && <th>Report</th>}
                </tr>
              </thead>
              <tbody>
                {series.map((s) => (
                  <tr key={s.id}>
                    <td>{s.visit_date}</td>
                    <td>{s.gestational_week ?? '—'}</td>
                    <td><RiskBadge level={s.risk_level} /></td>
                    <td>{Math.round(s.probability * 100)}%</td>
                    <td className="muted small">{s.recorded_by || '—'}</td>
                    <td className="muted small">{s.model}</td>
                    {showReportActions && (
                      <td>
                        <button className="btn btn-small btn-secondary" disabled={busyId === s.id}
                                onClick={() => generateReport(s.id)}>
                          {busyId === s.id ? '…' : 'PDF ↓'}
                        </button>
                      </td>
                    )}
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