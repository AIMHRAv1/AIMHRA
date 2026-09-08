import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiError } from '../../api/client'
import { assessmentService, patientService } from '../../services/auth'
import { pendingAssessments, queueAssessment, syncQueuedAssessments } from '../../services/offlineQueue'

const FIELDS = [
  ['age', 'Age', 14, 55, 1], ['body_temperature', 'Temperature (F)', 95, 106, 0.1],
  ['heart_rate', 'Heart rate', 40, 200, 1], ['systolic_bp', 'Systolic BP', 70, 250, 1],
  ['diastolic_bp', 'Diastolic BP', 40, 150, 1], ['bmi', 'BMI', 12, 60, 0.1],
  ['hba1c', 'HbA1c', 20, 60, 0.1], ['fasting_glucose', 'Fasting glucose', 2, 20, 0.1],
]
const initial = () => ({ visit_date: new Date().toISOString().slice(0, 10), gestational_week: '', symptoms: ['none'], notes: '', ...Object.fromEntries(FIELDS.map(([name]) => [name, ''])) })

export default function Assessment() {
  const [params] = useSearchParams()
  const [patients, setPatients] = useState([])
  const [patient, setPatient] = useState(params.get('patient') || '')
  const [form, setForm] = useState(initial)
  const [result, setResult] = useState(null)
  const [pending, setPending] = useState(0)
  const [error, setError] = useState(null)

  async function refreshQueue() {
    if (!navigator.onLine) { setPending((await pendingAssessments()).length); return }
    const synced = await syncQueuedAssessments((payload) => assessmentService.create(payload))
    setPending(synced.remaining)
  }
  useEffect(() => { patientService.list().then((d) => setPatients(d.results || [])); refreshQueue() }, [])
  useEffect(() => {
    const sync = () => refreshQueue()
    window.addEventListener('online', sync)
    return () => window.removeEventListener('online', sync)
  }, [])
  function set(name, value) { setForm((current) => ({ ...current, [name]: value })) }
  async function onSubmit(event) {
    event.preventDefault(); setError(null); setResult(null)
    const payload = { ...form, patient: Number(patient), gestational_week: form.gestational_week ? Number(form.gestational_week) : null }
    for (const [name] of FIELDS) payload[name] = Number(payload[name])
    try {
      if (!navigator.onLine) throw { code: 'NETWORK_ERROR' }
      setResult(await assessmentService.create(payload))
      setForm(initial())
    } catch (err) {
      const normalized = apiError(err)
      if (normalized.code === 'NETWORK_ERROR' || !navigator.onLine) {
        await queueAssessment(payload); setPending((count) => count + 1); setResult({ pending: true }); setForm(initial())
      } else setError(normalized)
    }
  }
  return <div className="page">
    <header className="page-head"><div><h1>New assessment</h1><p className="muted">{navigator.onLine ? 'Online' : 'Offline'} · {pending} pending sync</p></div></header>
    {error && <div className="alert alert-error">{error.message}</div>}
    {result?.pending && <div className="alert alert-info">Pending sync - prediction not yet available.</div>}
    {result && !result.pending && <div className="card"><h2>Prediction: {result.risk_level}</h2><p>{Math.round(result.probability * 100)}% confidence</p></div>}
    <form className="card" onSubmit={onSubmit}>
      <label className="field"><span>Patient</span><select value={patient} onChange={(e) => setPatient(e.target.value)} required><option value="">Select patient</option>{patients.map((p) => <option key={p.id} value={p.id}>{p.patient_code} - {p.full_name || 'Unnamed'}</option>)}</select></label>
      <div className="grid-2"><label className="field"><span>Visit date</span><input type="date" value={form.visit_date} onChange={(e) => set('visit_date', e.target.value)} required /></label><label className="field"><span>Gestational week</span><input type="number" min="1" max="45" value={form.gestational_week} onChange={(e) => set('gestational_week', e.target.value)} /></label></div>
      <div className="grid-2">{FIELDS.map(([name, label, min, max, step]) => <label className="field" key={name}><span>{label}</span><input type="number" min={min} max={max} step={step} value={form[name]} onChange={(e) => set(name, e.target.value)} required /></label>)}</div>
      <label className="field"><span>Notes</span><textarea value={form.notes} onChange={(e) => set('notes', e.target.value)} /></label>
      <button className="btn btn-primary" disabled={!patient}>Submit assessment</button>
    </form>
  </div>
}
