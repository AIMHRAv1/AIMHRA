import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { assessmentService, patientService, reportService } from '../../services/auth'
import { RiskTrendChart, ShapBars } from '../../charts'
import { CategoryBadge, Disclaimer, ErrorState, Loading, RiskBadge } from '../../components/ui'

export default function PatientDetail() {
  const { id } = useParams()
  const [patient, setPatient] = useState(null)
  const [trend, setTrend] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [assessments, setAssessments] = useState([])
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        const [p, t, a, h] = await Promise.all([
          patientService.detail(id),
          assessmentService.trend(id),
          assessmentService.alerts({ patient: id }),
          assessmentService.list({ patient: id }),
        ])
        setPatient(p)
        setTrend(t)
        setAlerts((a.results ?? []).filter((x) => x.patient === Number(id)))
        const list = h.results ?? []
        setAssessments(list)
        if (list[0]) setSelected(list[0])
      } catch (e) { setError(e) }
    }
    load()
  }, [id])

  async function generateReport(assessmentId) {
    setBusy(true)
    try {
      await reportService.generate(assessmentId)
      alert('Report generated.')
    } catch (e) { alert(e?.message || 'Failed') } finally { setBusy(false) }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!patient || !trend) return <div className="page"><Loading /></div>

  const series = trend.series ?? []

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{patient.patient_code}</h1>
          <p className="muted">{patient.full_name || patient.username} · registered {new Date(patient.created_at).toLocaleDateString()}</p>
        </div>
      </header>

      <div className="card">
        <h2 className="section-title">Risk trend</h2>
        {series.length ? <RiskTrendChart series={series} /> : <p className="muted">No assessments recorded.</p>}
        {trend.trend && series.length > 1 && (
          <p>Previous <RiskBadge level={trend.trend.previous} /> → Current <RiskBadge level={trend.trend.current} />
            {' '}<span className="trend-status">({trend.trend.status})</span></p>
        )}
      </div>

      {alerts.length > 0 && (
        <div className="card">
          <h2 className="section-title">Alert history</h2>
          <ul className="alert-list">
            {alerts.map((a) => (
              <li key={a.id} className={`alert-item cat-${a.category}`}>
                <CategoryBadge category={a.category} />
                <span>{a.message}</span>
                <span className="muted small">{new Date(a.created_at).toLocaleString()} · {a.status}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <h2 className="section-title">Assessments & explanations</h2>
        {assessments.length === 0 ? <p className="muted">No assessments recorded.</p> : (
          <>
            <div className="chip-row">
              {assessments.map((a) => (
                <button key={a.id} className={`chip${selected?.id === a.id ? ' active' : ''}`}
                        onClick={() => setSelected(a)}>
                  {a.visit_date} {a.prediction && `· ${a.prediction.risk_level.replace(' risk', '')}`}
                </button>
              ))}
            </div>
            {selected?.prediction ? (
              <div className="detail-grid">
                <div>
                  <RiskBadge level={selected.prediction.risk_level} size="lg" />
                  <p className="muted small">
                    Confidence {Math.round(selected.prediction.probability * 100)}% ·
                    model {selected.prediction.model.name} {selected.prediction.model.version}
                  </p>
                  <dl className="kv">
                    <div><dt>Visit date</dt><dd>{selected.visit_date}</dd></div>
                    <div><dt>Gestational week</dt><dd>{selected.gestational_week ?? '—'}</dd></div>
                    <div><dt>Age</dt><dd>{selected.age}</dd></div>
                    <div><dt>BP</dt><dd>{selected.systolic_bp}/{selected.diastolic_bp} mm Hg</dd></div>
                    <div><dt>Heart rate</dt><dd>{selected.heart_rate} bpm</dd></div>
                    <div><dt>Temperature</dt><dd>{selected.body_temperature} °F</dd></div>
                    <div><dt>BMI</dt><dd>{selected.bmi}</dd></div>
                    <div><dt>Symptoms</dt><dd>{selected.symptoms?.length ? selected.symptoms.join(', ') : 'none'}</dd></div>
                  </dl>
                  <button className="btn btn-small btn-secondary" disabled={busy}
                          onClick={() => generateReport(selected.id)}>Generate PDF report</button>
                </div>
                <div>
                  <h3 className="section-title">SHAP explanation</h3>
                  <ShapBars features={selected.prediction.explanation?.features} />
                  <Disclaimer text={selected.prediction.explanation?.disclaimer} />
                </div>
              </div>
            ) : <p className="muted">No prediction stored for this assessment.</p>}
          </>
        )}
      </div>
    </div>
  )
}
