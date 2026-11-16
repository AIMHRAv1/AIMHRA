import { useCallback, useEffect, useState } from 'react'
import { assessmentService, reportService } from '../../services/auth'
import { apiError } from '../../api/client'
import { MeasurementTrendChart, RiskTrendChart } from '../../charts'
import { Disclaimer, EmptyState, ErrorState, Loading, RiskBadge } from '../ui'
import { downloadReport } from '../../utils/reportDownload'
import { toDisplayMeasurement } from '../../utils/glucoseUnits'

const MEASUREMENT_DETAILS = {
  age: { label: 'Age', unit: 'years' },
  body_temperature: { label: 'Body temperature', unit: '°F' },
  heart_rate: { label: 'Heart rate', unit: 'bpm' },
  systolic_bp: { label: 'Systolic blood pressure', unit: 'mm Hg' },
  diastolic_bp: { label: 'Diastolic blood pressure', unit: 'mm Hg' },
  bmi: { label: 'BMI', unit: 'kg/m²' },
  hba1c: { label: 'HbA1c', unit: '%' },
  fasting_glucose: { label: 'Fasting glucose', unit: 'mg/dL' },
}

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
  const displayVisits = (measurements?.visits ?? []).map((visit) => ({
    ...visit,
    hba1c: toDisplayMeasurement('hba1c', visit.hba1c),
    fasting_glucose: toDisplayMeasurement('fasting_glucose', visit.fasting_glucose),
  }))
  const comparisons = measurements?.comparisons ?? []

  if (!showReportActions) {
    return (
      <div className="card">
        <h2 className="section-title">Assessment history</h2>
        {series.length === 0 ? (
          <EmptyState title="No assessments yet" hint="Assessment history will appear here after a healthcare worker records an assessment." />
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Date</th><th>Healthcare worker</th><th>Risk</th></tr>
            </thead>
            <tbody>
              {series.slice().reverse().map((assessment) => (
                <tr key={assessment.id}>
                  <td>{assessment.visit_date}</td>
                  <td>{assessment.recorded_by || '—'}</td>
                  <td><RiskBadge level={assessment.risk_level} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    )
  }

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

          {measurements && measurements.visits?.length > 0 && (
            <div className="card">
              <h2 className="section-title">Parameter trends over time</h2>
              <div className="measurement-charts">
                {measurements.features.map((feature) => {
                  const detail = MEASUREMENT_DETAILS[feature] || { label: feature, unit: '' }
                  return (
                    <section className="measurement-chart" key={feature}>
                      <h3>{detail.label} <span className="muted small">({detail.unit})</span></h3>
                      <MeasurementTrendChart
                        visits={displayVisits}
                        feature={feature}
                        label={detail.label}
                        unit={detail.unit}
                      />
                    </section>
                  )
                })}
              </div>
              <p className="muted small">Glucose values are converted from the model's stored scales for display.</p>
            </div>
          )}

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
                      const detail = MEASUREMENT_DETAILS[feature] || { label: feature, unit: '' }
                      const previousValue = cmp ? toDisplayMeasurement(feature, cmp.previous_value) : null
                      const latestValue = cmp ? toDisplayMeasurement(feature, cmp.latest_value) : null
                      const converted = feature === 'hba1c' || feature === 'fasting_glucose'
                      const displayedDelta = cmp
                        ? converted ? Number((latestValue - previousValue).toFixed(1)) : cmp.delta
                        : null
                      const displayedPercentChange = cmp
                        ? converted && previousValue !== 0
                          ? Number(((latestValue - previousValue) / Math.abs(previousValue) * 100).toFixed(1))
                          : cmp.percent_change
                        : null
                      return (
                        <tr key={feature}>
                          <td>{detail.label} ({detail.unit})</td>
                          {displayVisits.map((v) => (
                            <td key={v.assessment_id}>{v[feature]} {detail.unit}</td>
                          ))}
                          <td>
                            {cmp ? (
                              <>
                                {displayedDelta > 0 ? '+' : ''}{displayedDelta ?? '—'} {detail.unit}
                                {displayedPercentChange != null && (
                                  <span className="muted small"> ({displayedPercentChange > 0 ? '+' : ''}{displayedPercentChange}%)</span>
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
                  {data.measurement_rules.triggered.map((t) => {
                    const detail = MEASUREMENT_DETAILS[t.feature] || { unit: '' }
                    const delta = toDisplayMeasurement(t.feature, t.delta) - toDisplayMeasurement(t.feature, 0)
                    return (
                      <li key={t.id}><code>{t.id}</code> {t.description} — {t.feature} changed by {Number(delta.toFixed(1))} {detail.unit}</li>
                    )
                  })}
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