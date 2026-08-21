import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiError } from '../../api/client'
import { assessmentService } from '../../services/auth'
import { ShapBars } from '../../charts'
import { CategoryBadge, Disclaimer, ErrorState, RiskBadge } from '../../components/ui'

const FIELDS = [
  { name: 'age', label: 'Age (years)', min: 14, max: 55, step: 1, hint: 'Plausible range 14–55' },
  { name: 'body_temperature', label: 'Body temperature (°F)', min: 95, max: 106, step: 0.1, hint: 'Normal ≈ 97–99.5' },
  { name: 'heart_rate', label: 'Heart rate (bpm)', min: 40, max: 200, step: 1 },
  { name: 'systolic_bp', label: 'Systolic blood pressure (mm Hg)', min: 70, max: 250, step: 1 },
  { name: 'diastolic_bp', label: 'Diastolic blood pressure (mm Hg)', min: 40, max: 150, step: 1 },
  { name: 'bmi', label: 'BMI (kg/m²)', min: 12, max: 60, step: 0.1 },
  { name: 'hba1c', label: 'Blood glucose — HbA1c column (dataset units)', min: 20, max: 60, step: 0.1, hint: 'Observed dataset range 30–50' },
  { name: 'fasting_glucose', label: 'Blood glucose — fasting column (dataset units)', min: 2, max: 20, step: 0.1, hint: 'Observed dataset range 3.5–8.9' },
]

const SYMPTOMS = [
  ['none', 'No symptoms to report'],
  ['vaginal_bleeding', 'Vaginal bleeding'],
  ['severe_headache', 'Severe headache'],
  ['blurred_vision', 'Blurred vision'],
  ['convulsions', 'Convulsions / fits'],
  ['severe_abdominal_pain', 'Severe abdominal pain'],
  ['fever', 'Fever'],
  ['decreased_fetal_movement', 'Decreased fetal movement'],
  ['swelling_face_hands', 'Swelling of face/hands'],
  ['difficulty_breathing', 'Difficulty breathing'],
  ['persistent_vomiting', 'Persistent vomiting'],
  ['dizziness_fainting', 'Dizziness / fainting'],
]

const initialValues = () => ({
  visit_date: new Date().toISOString().slice(0, 10),
  gestational_week: '',
  age: '', body_temperature: '', heart_rate: '', systolic_bp: '',
  diastolic_bp: '', bmi: '', hba1c: '', fasting_glucose: '',
  symptoms: ['none'], notes: '',
})

export default function Assessment() {
  const [form, setForm] = useState(initialValues)
  const [errors, setErrors] = useState({})
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  function toggleSymptom(code) {
    setForm((f) => {
      let next = f.symptoms.includes(code)
        ? f.symptoms.filter((s) => s !== code)
        : [...f.symptoms.filter((s) => s !== 'none'), code]
      if (code === 'none') next = ['none']
      if (next.length === 0) next = ['none']
      return { ...f, symptoms: next }
    })
  }

  function validate() {
    const errs = {}
    if (!form.visit_date) errs.visit_date = 'Visit date is required.'
    for (const f of FIELDS) {
      const v = parseFloat(form[f.name])
      if (form[f.name] === '' || Number.isNaN(v)) errs[f.name] = 'This field is required.'
      else if (v < f.min || v > f.max) errs[f.name] = `Must be between ${f.min} and ${f.max}.`
    }
    if (form.gestational_week !== '' && (form.gestational_week < 1 || form.gestational_week > 45)) {
      errs.gestational_week = 'Week must be 1–45.'
    }
    if (parseFloat(form.diastolic_bp) > parseFloat(form.systolic_bp)) {
      errs.diastolic_bp = 'Diastolic cannot exceed systolic.'
    }
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  async function onSubmit(e) {
    e.preventDefault()
    setError(null)
    if (!validate()) return
    setBusy(true)
    try {
      const payload = {
        ...form,
        gestational_week: form.gestational_week === '' ? null : Number(form.gestational_week),
      }
      for (const f of FIELDS) payload[f.name] = Number(payload[f.name])
      const data = await assessmentService.create(payload)
      setResult(data)
      setForm(initialValues())
    } catch (err) {
      const e = apiError(err)
      if (e.details && typeof e.details === 'object') {
        setErrors(Object.fromEntries(Object.entries(e.details).map(([k, v]) => [k, Array.isArray(v) ? v.join(' ') : String(v)])))
      }
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>New assessment</h1>
          <p className="muted">Enter the measurements taken at this visit. All fields are validated by the backend.</p>
        </div>
      </header>

      {result ? (
        <PredictionResult result={result} onAnother={() => setResult(null)} />
      ) : (
        <form className="card" onSubmit={onSubmit} noValidate>
          {error && <div className="alert alert-error" role="alert">{error.message}</div>}
          <div className="grid-2">
            <label className="field">
              <span>Visit date</span>
              <input type="date" max={new Date().toISOString().slice(0, 10)} value={form.visit_date}
                     onChange={(e) => set('visit_date', e.target.value)} required />
              {errors.visit_date && <em className="field-error">{errors.visit_date}</em>}
            </label>
            <label className="field">
              <span>Gestational week (optional)</span>
              <input type="number" min={1} max={45} value={form.gestational_week}
                     onChange={(e) => set('gestational_week', e.target.value)} placeholder="e.g. 24" />
              {errors.gestational_week && <em className="field-error">{errors.gestational_week}</em>}
            </label>
          </div>

          <h2 className="section-title">Measurements</h2>
          <div className="grid-2">
            {FIELDS.map((f) => (
              <label className="field" key={f.name}>
                <span>{f.label}</span>
                <input type="number" inputMode="decimal" min={f.min} max={f.max} step={f.step}
                       value={form[f.name]} onChange={(e) => set(f.name, e.target.value)} required />
                {f.hint && <small className="field-hint">{f.hint}</small>}
                {errors[f.name] && <em className="field-error">{errors[f.name]}</em>}
              </label>
            ))}
          </div>

          <h2 className="section-title">Symptoms since the last visit</h2>
          <div className="symptom-grid" role="group" aria-label="Symptoms">
            {SYMPTOMS.map(([code, label]) => (
              <label key={code} className={`symptom${form.symptoms.includes(code) ? ' selected' : ''}`}>
                <input type="checkbox" checked={form.symptoms.includes(code)} onChange={() => toggleSymptom(code)} />
                {label}
              </label>
            ))}
          </div>

          <label className="field">
            <span>Notes (optional)</span>
            <textarea rows={2} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
          </label>

          <div className="form-actions">
            <button className="btn btn-primary" disabled={busy}>{busy ? 'Analyzing…' : 'Submit assessment'}</button>
          </div>
        </form>
      )}
    </div>
  )
}

function PredictionResult({ result, onAnother }) {
  const probs = Object.entries(result.probabilities || {})
  return (
    <div className="stack">
      {result.rules?.category === 'EMERGENCY' && (
        <div className="alert alert-emergency" role="alert">
          <strong>⛔ EMERGENCY — rule {result.rules.rules_version}</strong>
          <p>{result.rules.message}</p>
        </div>
      )}
      {result.rules?.category === 'HIGH_CONCERN' && (
        <div className="alert alert-warning" role="alert">
          <strong>⚠ High concern — rule {result.rules.rules_version}</strong>
          <p>{result.rules.message}</p>
        </div>
      )}

      <div className="card result-card">
        <div className="result-head">
          <div>
            <div className="muted">Assessment for {result.assessment.visit_date}</div>
            <RiskBadge level={result.risk_level} size="lg" />
          </div>
          <div className="result-probs">
            {probs.map(([level, p]) => (
              <div key={level} className={`prob-row ${level.replace(' ', '-')}`}>
                <span>{level.replace(' risk', '')} risk</span>
                <div className="prob-bar"><div className="prob-fill" style={{ width: `${Math.round(p * 100)}%` }} /></div>
                <b>{Math.round(p * 100)}%</b>
              </div>
            ))}
          </div>
        </div>
        <p className="muted small">
          Model: {result.model?.name} {result.model?.version} · confidence {Math.round(result.probability * 100)}%
        </p>
      </div>

      <div className="card">
        <h2 className="section-title">Why the model produced this result (SHAP)</h2>
        {result.explanation?.features?.length
          ? <ShapBars features={result.explanation.features} />
          : <p className="muted">Feature-level explanation is not available for this prediction.</p>}
        <Disclaimer text={result.explanation?.disclaimer} />
      </div>

      {result.trend && result.trend.visits > 1 && (
        <div className="card">
          <h2 className="section-title">Trend vs previous visit</h2>
          <p>
            Previous: <RiskBadge level={result.trend.previous} /> → Current: <RiskBadge level={result.trend.current} />
            {' '}<span className="trend-status">({result.trend.status})</span>
          </p>
        </div>
      )}

      <div className="card">
        <h2 className="section-title">Rules applied</h2>
        <p><CategoryBadge category={result.rules?.category} /> <span className="muted">rule set {result.rules?.rules_version}</span></p>
        {result.rules?.triggered?.length > 0 ? (
          <ul className="rule-list">
            {result.rules.triggered.map((t) => <li key={t.id}><code>{t.id}</code> {t.description}</li>)}
          </ul>
        ) : <p className="muted">No warning rules triggered.</p>}
      </div>

      <Disclaimer text={result.disclaimer} />
      <div className="form-actions">
        <button className="btn btn-primary" onClick={onAnother}>Start another assessment</button>
        <Link className="btn btn-secondary" to="/app/history">View history & trend</Link>
        <Link className="btn btn-secondary" to="/app/chat">Ask the assistant</Link>
      </div>
    </div>
  )
}
