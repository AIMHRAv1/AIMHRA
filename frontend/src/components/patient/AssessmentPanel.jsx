import { useMemo, useState } from 'react'
import { apiError } from '../../api/client'
import { assessmentService, ocrService } from '../../services/auth'
import { ShapBars } from '../../charts'
import { CategoryBadge, Disclaimer, EmptyState, ErrorState, Loading, RiskBadge } from '../ui'
import { IconAlertTriangle, IconOctagonAlert } from '../icons'
import { AdvisoryCard } from './AdvisoryPanel'
import { ageAtDateOfBirth, currentGestationalWeek } from '../../utils/patientDates'
import { glucoseToMmolL, hbA1cToMmolMol, hbA1cToPercent } from '../../utils/glucoseUnits'

const FIELDS = [
  { name: 'age', label: 'Age (years)', min: 14, max: 55, step: 1, hint: 'Average range: 18–35 years.' },
  { name: 'body_temperature', label: 'Body temperature (°F)', min: 95, max: 106, step: 0.1, hint: 'Average range: 97–99.5 °F.' },
  { name: 'heart_rate', label: 'Heart rate (bpm)', min: 40, max: 200, step: 1, hint: 'Average range: 60–100 bpm.' },
  { name: 'systolic_bp', label: 'Systolic blood pressure (mm Hg)', min: 70, max: 250, step: 1, hint: 'Average range: 90–139 mm Hg.' },
  { name: 'diastolic_bp', label: 'Diastolic blood pressure (mm Hg)', min: 40, max: 150, step: 1, hint: 'Average range: 60–89 mm Hg.' },
  { name: 'bmi', label: 'BMI (kg/m²)', min: 12, max: 60, step: 0.1, hint: 'Average range: 18.5–24.9 kg/m².' },
  { name: 'hba1c', label: 'HbA1c (%)', min: 3.98, max: 7.64, step: 0.01, hint: 'Average range: 4.0–5.6%.' },
  { name: 'fasting_glucose', label: 'Fasting glucose (mg/dL)', min: 36, max: 360.4, step: 0.1, hint: 'Average range: 70–99 mg/dL.' },
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

const emptyScan = () => ({ file: null, preview: null, busy: false, error: null, result: null })

// OCR confidence badge: green = valid and confident, amber = review, red = invalid/low.
function scanBadgeClass(entry) {
  if (!entry) return null
  const conf = typeof entry.confidence === 'number' ? entry.confidence : 0
  if (entry.valid === false || conf < 0.6) return 'field-badge red'
  // Uncertain fields are never green: warnings, suggestions or disagreements
  // force at least amber.
  if (entry.warning || entry.suggestion || entry.candidates) return 'field-badge amber'
  if (conf >= 0.85) return 'field-badge green'
  return 'field-badge amber'
}

export default function AssessmentPanel({ patient, onViewHistory, onAskAssistant, onViewAdvisory }) {
  const [form, setForm] = useState(initialValues)
  const [errors, setErrors] = useState({})
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('manual') // 'manual' (default) | 'scan'
  const [scan, setScan] = useState(emptyScan)
  const [checkedFields, setCheckedFields] = useState({})

  const patientLabel = useMemo(
    () => `${patient?.patient_code || ''}${patient?.full_name ? ` · ${patient.full_name}` : ''}`,
    [patient],
  )
  const calculatedAge = ageAtDateOfBirth(patient?.date_of_birth, form.visit_date)
  const ageIsCalculated = Boolean(patient?.date_of_birth)
  const calculatedGestationalWeek = currentGestationalWeek(
    patient?.gestational_week_at_registration,
    patient?.created_at,
    form.visit_date,
  )

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  // --- OCR scan mode: pre-fill only; the operator reviews and confirms. ---
  function pickScanFile(file) {
    if (!file) return
    if (scan.preview) URL.revokeObjectURL(scan.preview)
    setScan({ ...emptyScan(), file, preview: URL.createObjectURL(file) })
  }

  async function extractScan() {
    if (!scan.file) return
    setScan((s) => ({ ...s, busy: true, error: null }))
    try {
      const data = await ocrService.extract(scan.file)
      const applied = applyScan(data)
      setScan((s) => ({ ...s, busy: false, result: data, applied }))
    } catch (e) {
      setScan((s) => ({ ...s, busy: false, error: apiError(e) }))
    }
  }

  function applyScan(data) {
    // Fill ONLY fields the OCR actually found; missing fields stay blank.
    // Returns the applied snapshot (for edit tracking — names only).
    const applied = {}
    setForm((f) => {
      const next = { ...f }
      const fields = data.fields || {}
      for (const [name, entry] of Object.entries(fields)) {
        const { value } = entry
        if (value === null || value === undefined || value === '') continue
        if (name === 'visit_date') next.visit_date = String(value)
        else if (name === 'gestational_week') next.gestational_week = String(Math.round(Number(value)))
        else if (name === 'age' && ageIsCalculated) continue
        else if (name === 'hba1c') {
          const scannedValue = Number(value)
          next.hba1c = String(scannedValue > 20 ? hbA1cToPercent(scannedValue) : scannedValue)
        } else if (name === 'fasting_glucose') {
          const scannedValue = Number(value)
          next.fasting_glucose = String(scannedValue > 20 ? scannedValue : scannedValue * 18.0182)
        } else if (FIELDS.some((fl) => fl.name === name)) next[name] = String(value)
        applied[name] = next[name]
      }
      return next
    })
    return applied
  }

  function applySuggestion(field, value) {
    // Explicit operator action — suggestions are never auto-applied.
    let displayValue = Number(value)
    if (field === 'hba1c' && displayValue > 20) displayValue = hbA1cToPercent(displayValue)
    if (field === 'fasting_glucose' && displayValue <= 20) displayValue *= 18.0182
    set(field, String(displayValue))
  }

  function resetScan() {
    if (scan.preview) URL.revokeObjectURL(scan.preview)
    setScan(emptyScan())
  }

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
      const fieldValue = f.name === 'age' && ageIsCalculated ? calculatedAge : form[f.name]
      const v = parseFloat(fieldValue)
      if (fieldValue === '' || fieldValue == null || Number.isNaN(v)) errs[f.name] = 'This field is required.'
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

  function uncheckedUncertain() {
    // Amber/red OCR fields the operator has not explicitly confirmed.
    if (mode !== 'scan' || !scan.result) return []
    const out = []
    for (const [name, entry] of Object.entries(scan.result.fields || {})) {
      if (name === 'age' && ageIsCalculated) continue
      const uncertain = entry.valid === false || entry.warning || entry.suggestion || entry.candidates
      if (uncertain && !checkedFields[name]) out.push(name)
    }
    return out
  }

  async function onSubmit(e) {
    e.preventDefault()
    setError(null)
    if (!validate()) return
    const unchecked = uncheckedUncertain()
    if (unchecked.length > 0) {
      const okGo = window.confirm(
        `These scanned values are marked uncertain and were not confirmed: ${unchecked.join(', ')}. ` +
        'Submit anyway?'
      )
      if (!okGo) return
    }
    setBusy(true)
    try {
      const payload = {
        ...form,
        age: ageIsCalculated ? calculatedAge : Number(form.age),
        patient: patient.id,
        gestational_week: form.gestational_week === ''
          ? calculatedGestationalWeek
          : Number(form.gestational_week),
        data_source: mode === 'scan' && scan.result ? 'ocr_assisted' : 'manual',
      }
      for (const f of FIELDS) payload[f.name] = Number(payload[f.name])
      payload.hba1c = Number(hbA1cToMmolMol(form.hba1c).toFixed(2))
      payload.fasting_glucose = Number(glucoseToMmolL(form.fasting_glucose).toFixed(2))
      const data = await assessmentService.create(payload)
      setResult(data)
      setForm(initialValues())
      setCheckedFields({})
      // Edit tracking for OCR quality measurement: field names + changed
      // flag only — values never leave the browser.
      if (mode === 'scan' && scan.result) {
        const entries = Object.keys(scan.result.fields || {}).map((name) => ({
          field: name,
          changed: String(form[name] ?? '') !== String(scan.applied?.[name] ?? ''),
        }))
        if (entries.length) ocrService.feedback(entries).catch(() => {})
      }
      resetScan()
      setMode('manual')
    } catch (err) {
      const e2 = apiError(err)
      if (e2.details && typeof e2.details === 'object') {
        setErrors(Object.fromEntries(Object.entries(e2.details).map(([k, v]) => [k, Array.isArray(v) ? v.join(' ') : String(v)])))
      }
      setError(e2)
    } finally {
      setBusy(false)
    }
  }

  if (error && error.code === 'PERMISSION_DENIED') return <ErrorState error={error} />

  return (
    <div className="stack">
      {result ? (
        <PredictionResult
          result={result}
          patientLabel={patientLabel}
          onAnother={() => setResult(null)}
          onViewHistory={onViewHistory}
          onAskAssistant={onAskAssistant}
          onViewAdvisory={onViewAdvisory}
        />
      ) : (
        <div className="stack">
          <div className="mode-toggle" role="tablist" aria-label="Entry mode">
            <button type="button" className={`chip${mode === 'manual' ? ' selected' : ''}`}
                    aria-selected={mode === 'manual'} onClick={() => setMode('manual')}>
              Enter manually
            </button>
            <button type="button" className={`chip${mode === 'scan' ? ' selected' : ''}`}
                    aria-selected={mode === 'scan'} onClick={() => setMode('scan')}>
              Scan report card
            </button>
          </div>

          {mode === 'scan' && !scan.result && (
            <ScanPane scan={scan} onPick={pickScanFile} onExtract={extractScan} onReset={resetScan} />
          )}
          {mode === 'scan' && scan.result && (
            <div className="alert alert-info" role="status">
              Auto-filled from scan. Please verify every value before submitting.
            </div>
          )}

          <div className={mode === 'scan' && scan.result ? 'scan-layout' : ''}>
            <form className="card" onSubmit={onSubmit} noValidate>
              {error && <div className="alert alert-error" role="alert">{error.message}</div>}
              <h2 className="section-title">New assessment — {patientLabel || 'patient'}</h2>
              <div className="grid-2">
                <label className="field">
                  <span>Visit date {scanBadge(scan.result, 'visit_date')}</span>
                  <input type="date" max={new Date().toISOString().slice(0, 10)} value={form.visit_date}
                         onChange={(e) => set('visit_date', e.target.value)} required />
                  {scanWarn(scan.result, 'visit_date', applySuggestion)}
                  {errors.visit_date && <em className="field-error">{errors.visit_date}</em>}
                  {scanCropRow('visit_date', scan.result, checkedFields, setCheckedFields)}
                </label>
                <label className="field">
                  <span>Gestational week {scanBadge(scan.result, 'gestational_week')}</span>
                  <input type="number" min={1} max={45}
                         value={form.gestational_week || calculatedGestationalWeek || ''}
                         onChange={(e) => set('gestational_week', e.target.value)} placeholder="e.g. 24" />
                  <small className="field-hint">
                    {calculatedGestationalWeek != null
                      ? `Estimated from patient registration and visit date: week ${calculatedGestationalWeek}.`
                      : 'Optional; enter the current pregnancy week if known.'}
                  </small>
                  {scanWarn(scan.result, 'gestational_week', applySuggestion)}
                  {errors.gestational_week && <em className="field-error">{errors.gestational_week}</em>}
                  {scanCropRow('gestational_week', scan.result, checkedFields, setCheckedFields)}
                </label>
              </div>

              <h2 className="section-title">Measurements</h2>
              <div className="grid-2">
                {FIELDS.map((f) => {
                  const crop = scan.result?.fields?.[f.name]?.crop_image
                  const fieldValue = f.name === 'age' && ageIsCalculated ? calculatedAge ?? '' : form[f.name]
                  return (
                    <label className="field" key={f.name}>
                      <span>
                        {ageIsCalculated && f.name === 'age' ? 'Age (years, from date of birth)' : f.label}
                        {' '}{!(ageIsCalculated && f.name === 'age') && scanBadge(scan.result, f.name)}
                      </span>
                      <input type="number" inputMode="decimal" min={f.min} max={f.max} step={f.step}
                             value={fieldValue} onChange={(e) => set(f.name, e.target.value)}
                             readOnly={ageIsCalculated && f.name === 'age'} required />
                      {f.hint && <small className="field-hint">{f.hint}</small>}
                      {scanWarn(scan.result, f.name, applySuggestion)}
                      {errors[f.name] && <em className="field-error">{errors[f.name]}</em>}
                      {crop && (
                        <span className="field-crop-row">
                          <img src={crop} alt={`Scanned region for ${f.label}`} className="field-crop" />
                          <label className="small checked-label">
                            <input type="checkbox" checked={!!checkedFields[f.name]}
                                   onChange={(e) => setCheckedFields((s) => ({ ...s, [f.name]: e.target.checked }))} />
                            I checked this
                          </label>
                        </span>
                      )}
                    </label>
                  )
                })}
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
                <small className="field-hint">Included with symptoms and measurements when generating the care advisory.</small>
              </label>

              <div className="form-actions">
                <button className="btn btn-primary" disabled={busy}>{busy ? 'Analyzing…' : 'Submit assessment'}</button>
              </div>
            </form>

            {mode === 'scan' && scan.result && <ScanSidebar scan={scan} onRescan={resetScan} />}
          </div>
        </div>
      )}
    </div>
  )
}

function scanBadge(result, field) {
  const entry = result?.fields?.[field]
  const cls = scanBadgeClass(entry)
  if (!cls) return null
  return <span className={cls}>{entry.valid === false ? 'check' : `${Math.round((entry.confidence || 0) * 100)}%`}</span>
}

function scanCropRow(field, result, checkedFields, setCheckedFields) {
  const crop = result?.fields?.[field]?.crop_image
  if (!crop) return null
  return (
    <span className="field-crop-row">
      <img src={crop} alt={`Scanned region for ${field}`} className="field-crop" />
      <label className="small checked-label">
        <input type="checkbox" checked={!!checkedFields[field]}
               onChange={(e) => setCheckedFields((s) => ({ ...s, [field]: e.target.checked }))} />
        I checked this
      </label>
    </span>
  )
}

function scanWarn(result, field, onApplySuggestion) {
  const entry = result?.fields?.[field]
  if (!entry) return null
  return (
    <>
      {entry.warning && <small className="field-warning">{entry.warning}</small>}
      {entry.suggestion?.value != null && onApplySuggestion && (
        <small className="field-warning">
          Suggestion: <b>{entry.suggestion.value}</b>{' '}
          <button type="button" className="link" onClick={() => onApplySuggestion(field, entry.suggestion.value)}>
            Use {entry.suggestion.value}
          </button>
        </small>
      )}
      {entry.candidates?.length > 0 && (
        <small className="field-warning">
          Candidates: {entry.candidates.map((c) => `${c.value} (${c.source})`).join(' | ')}
        </small>
      )}
    </>
  )
}

function ScanPane({ scan, onPick, onExtract, onReset }) {
  return (
    <div className="card">
      <h2 className="section-title">Scan report card</h2>
      <p className="muted small">
        Take a photo of the printed lab report (or upload a JPG/PNG/PDF, max 5 MB). The values are
        read automatically and placed into the form below — you review and confirm before anything is submitted.
      </p>
      <label className="field">
        <span>Report card photo or file</span>
        <input type="file" accept="image/*,application/pdf" capture="environment"
               onChange={(e) => onPick(e.target.files?.[0])} disabled={scan.busy} />
      </label>
      {scan.preview && scan.file?.type !== 'application/pdf' && (
        <div className="scan-preview"><img src={scan.preview} alt="Report card preview" /></div>
      )}
      {scan.file?.type === 'application/pdf' && (
        <p className="muted small">PDF selected: {scan.file.name}</p>
      )}
      {scan.busy && <Loading label="Reading the report card…" />}
      {scan.error && <ErrorState error={scan.error} onRetry={() => onPick(scan.file)} />}
      {!scan.file && !scan.busy && !scan.error && (
        <EmptyState title="No file selected" hint="Choose or capture a report card photo to pre-fill the assessment." />
      )}
      <div className="form-actions">
        <button type="button" className="btn btn-primary" disabled={!scan.file || scan.busy} onClick={onExtract}>
          {scan.busy ? 'Reading…' : 'Extract values'}
        </button>
        {scan.file && !scan.busy && (
          <button type="button" className="btn btn-secondary" onClick={onReset}>Clear</button>
        )}
      </div>
    </div>
  )
}

function ScanSidebar({ scan, onRescan }) {
  const result = scan.result
  const missing = result?.missing ?? []
  const warnings = result?.warnings ?? []
  return (
    <aside className="scan-sidebar">
      {scan.preview && (
        <div className="card">
          <h2 className="section-title">Scanned image</h2>
          <div className="scan-preview"><img src={scan.preview} alt="Scanned report card" /></div>
        </div>
      )}
      <div className="card">
        <h2 className="section-title">Extraction details</h2>
        <p className="muted small">
          Engine: {result?.engine_info?.engine}
          {result?.engine_info?.stages?.length ? ` (+ ${result.engine_info.stages.join(' + ')})` : ''} ·
          {' '}{result?.engine_info?.duration_ms ?? '—'} ms
        </p>
        <b className="small">Extracted fields (provenance):</b>
        <ul className="rule-list">
          {Object.entries(result?.fields || {}).map(([name, entry]) => (
            <li key={name}>
              <code>{name}</code> {entry.valid === false ? '⚠ verify' : 'ok'} · {entry.source} ·{' '}
              {Math.round((entry.confidence || 0) * 100)}%
              {entry.candidates?.length > 0 && (
                <div className="muted small">
                  candidates: {entry.candidates.map((c) => `${c.value} (${c.source})`).join(' | ')}
                </div>
              )}
              {entry.also_found_by?.length > 0 && (
                <div className="muted small">also found by: {entry.also_found_by.join(', ')}</div>
              )}
            </li>
          ))}
        </ul>
        {missing.length > 0 && (
          <>
            <b className="small">Not found — left blank:</b>
            <p className="muted small">{missing.join(', ')}</p>
          </>
        )}
        {warnings.length > 0 && (
          <>
            <b className="small">Warnings:</b>
            <ul className="rule-list">
              {warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </>
        )}
        <button type="button" className="btn btn-small btn-secondary" onClick={onRescan}>
          Scan a different file
        </button>
      </div>
    </aside>
  )
}

function PredictionResult({ result, patientLabel, onAnother, onViewHistory, onAskAssistant, onViewAdvisory }) {
  const probs = Object.entries(result.probabilities || {})
  return (
    <div className="stack">
      {result.rules?.category === 'EMERGENCY' && (
        <div className="alert alert-emergency" role="alert">
          <strong><IconOctagonAlert size={14} /> EMERGENCY — rule {result.rules.rules_version}</strong>
          <p>{result.rules.message}</p>
        </div>
      )}
      {result.rules?.category === 'HIGH_CONCERN' && (
        <div className="alert alert-warning" role="alert">
          <strong><IconAlertTriangle size={14} /> High concern — rule {result.rules.rules_version}</strong>
          <p>{result.rules.message}</p>
        </div>
      )}

      <div className="card result-card">
        <div className="result-head">
          <div>
            <div className="muted small">{patientLabel} · assessment on {result.assessment.visit_date}</div>
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

      <div className="card">
        <h2 className="section-title">Decision support & references</h2>
        {result.decision_support ? (
          <div className="stack">
            <div>
              <p className="muted small" style={{ marginBottom: 4 }}>
                <b>Model estimate</b> — {result.decision_support.ml.risk_level}, confidence{' '}
                {Math.round(result.decision_support.ml.probability * 100)}% ({result.decision_support.ml.model?.name})
              </p>
              {result.decision_support.ml.top_factors?.length > 0 && (
                <ul className="rule-list">
                  {result.decision_support.ml.top_factors.map((f) => (
                    <li key={f.feature}>
                      {f.label} — {f.direction} the model's estimate (impact {f.impact >= 0 ? '+' : ''}{f.impact});{' '}
                      <span className="muted">{f.note}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <p className="muted small" style={{ marginBottom: 4 }}>
                <b>Rule checks</b> — {result.decision_support.rules.category} (rule set {result.decision_support.rules.rules_version}) ·{' '}
                <span className="muted">{result.decision_support.rules.note}</span>
              </p>
            </div>
            {result.decision_support.reference_warnings?.length > 0 && (
              <p className="muted small">{result.decision_support.reference_warnings.join(' ')}</p>
            )}
            {result.decision_support.references?.length > 0 && (
              <div>
                <p className="muted small" style={{ marginBottom: 4 }}>
                  <b>Guideline references</b> — retrieved from the indexed knowledge base; provided for traceability, not as clinical advice.
                </p>
                <ul className="rule-list">
                  {result.decision_support.references.map((r, i) => (
                    <li key={i}>
                      <code>{r.topic_id}</code> {r.topic_label} — {r.document_title}
                      {r.section ? ` · ${r.section}` : ''} · chunk {r.chunk_index}
                      {r.source_url ? <> · <a href={r.source_url} target="_blank" rel="noreferrer">source</a></> : null}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p className="muted">Decision support details are not available for this assessment.</p>
        )}
      </div>

      <AdvisoryCard assessmentId={result.assessment?.id} category={result.rules?.category} autoGenerate />

      <Disclaimer text={result.disclaimer} />
      <div className="form-actions">
        <button className="btn btn-primary" onClick={onAnother}>Start another assessment</button>
        <button className="btn btn-secondary" onClick={onViewHistory}>View history & trend</button>
        <button className="btn btn-secondary" onClick={onViewAdvisory}>Open care advisory</button>
        <button className="btn btn-secondary" onClick={onAskAssistant}>Ask the assistant</button>
      </div>
    </div>
  )
}