import { MeasurementTrendChart } from '../../charts'

const MEASUREMENTS = [
  { key: 'systolic_bp', label: 'Systolic blood pressure', unit: 'mmHg' },
  { key: 'diastolic_bp', label: 'Diastolic blood pressure', unit: 'mmHg' },
  { key: 'heart_rate', label: 'Heart rate', unit: 'bpm' },
  { key: 'body_temperature', label: 'Body temperature', unit: '°F' },
  { key: 'bmi', label: 'BMI', unit: 'kg/m²' },
  { key: 'hba1c', label: 'HbA1c', unit: 'mmol/mol' },
  { key: 'fasting_glucose', label: 'Fasting blood glucose', unit: 'mmol/L' },
]

const CHARTS = [
  {
    title: 'Blood pressure (mmHg)',
    measurements: [
      { key: 'systolic_bp', label: 'Systolic' },
      { key: 'diastolic_bp', label: 'Diastolic' },
    ],
  },
  { title: 'Heart rate (bpm)', measurements: [{ key: 'heart_rate', label: 'Heart rate' }] },
  { title: 'Body temperature (°F)', measurements: [{ key: 'body_temperature', label: 'Temperature' }] },
  { title: 'BMI (kg/m²)', measurements: [{ key: 'bmi', label: 'BMI' }] },
  { title: 'HbA1c (mmol/mol)', measurements: [{ key: 'hba1c', label: 'HbA1c' }] },
  { title: 'Fasting blood glucose (mmol/L)', measurements: [{ key: 'fasting_glucose', label: 'Fasting glucose' }] },
]

function formatValue(value, unit) {
  return value == null ? 'Not recorded' : `${value} ${unit}`
}

export default function MeasurementHistory({ series, changes }) {
  const hasPrevious = (series || []).length > 1
  return (
    <section className="stack">
      <div>
        <h2 className="section-title">Measurement trends over time</h2>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
          {CHARTS.map((chart) => (
            <MeasurementTrendChart
              key={chart.title}
              series={series}
              title={chart.title}
              measurements={chart.measurements}
            />
          ))}
        </div>
      </div>

      <div className="card">
        <h2 className="section-title">Latest assessment compared with previous</h2>
        {!hasPrevious && <p className="muted small">One assessment is available; it is the baseline and no change can be calculated yet.</p>}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Measurement</th><th>Previous</th><th>Latest</th><th>Change</th><th>Existing rule status</th></tr>
            </thead>
            <tbody>
              {(changes || []).map((change) => {
                const measurement = MEASUREMENTS.find((item) => item.key === change.feature)
                const activeRules = (change.current_triggered_rules || [])
                  .map((rule) => rule.description).join('; ')
                const rules = {
                  newly_triggered: `Newly triggered: ${activeRules}`,
                  ongoing: `Still triggered: ${activeRules}`,
                  baseline: activeRules ? `Baseline rule triggered: ${activeRules}` : 'No configured rule triggered',
                  previous_value_unavailable: activeRules
                    ? `Current rule triggered; previous value unavailable: ${activeRules}`
                    : 'Previous value unavailable; no rule triggered now',
                  measurement_unavailable: 'Current measurement unavailable',
                  no_trigger: 'No configured rule triggered',
                }[change.rule_status] || 'Rule status unavailable'
                const delta = change.difference == null
                  ? change.direction === 'baseline' ? 'Baseline' : 'Unavailable'
                  : `${change.direction} (${change.difference > 0 ? '+' : ''}${change.difference} ${measurement.unit})`
                return (
                  <tr key={change.feature}>
                    <td>{measurement.label}</td>
                    <td>{formatValue(change.previous, measurement.unit)}</td>
                    <td>{formatValue(change.current, measurement.unit)}</td>
                    <td>{delta}</td>
                    <td className="muted small">{rules}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="muted small">
          Clinical rule status uses only existing configured measurement rules. HbA1c and fasting glucose have no measurement-based rules configured. These comparisons describe recorded visits and do not predict future complications.
        </p>
      </div>
    </section>
  )
}
