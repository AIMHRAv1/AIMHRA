import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { patientService } from '../../services/auth'
import { apiError } from '../../api/client'
import { bloodGroupOptions } from '../../constants/clinical'

const initial = {
  full_name: '', email: '', phone: '', address: '',
  date_of_birth: '', blood_group: '', gestational_week_at_registration: '',
  estimated_due_date: '', gravidity: '', parity: '',
  medical_history_notes: '', allergies: '',
  emergency_contact_name: '', emergency_contact_phone: '',
  obstetric_history_notes: '', current_medications: '', additional_notes: '',
}

export default function PatientNew() {
  const navigate = useNavigate()
  const [form, setForm] = useState(initial)
  const [errors, setErrors] = useState({})
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  function set(k, v) {
    setForm((f) => ({ ...f, [k]: v }))
    setErrors((e) => ({ ...e, [k]: undefined }))
  }

  async function onSubmit(e) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const payload = { ...form }
      if (!payload.full_name.trim()) {
        setErrors((e) => ({ ...e, full_name: 'Patient name is required.' }))
        setBusy(false)
        return
      }
      for (const k of ['date_of_birth', 'estimated_due_date']) if (!payload[k]) payload[k] = null
      for (const k of ['gestational_week_at_registration', 'gravidity', 'parity']) {
        payload[k] = payload[k] === '' || payload[k] == null ? null : Number(payload[k])
      }
      const created = await patientService.create(payload)
      navigate(`/app/patients/${created.id}?tab=overview`, { replace: true })
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

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="muted small"><Link to="/app/patients">← All patients</Link></div>
          <h1>Add patient</h1>
          <p className="muted">Create a new standalone patient record. The patient never needs a login account.</p>
        </div>
      </header>

      {error && <div className="alert alert-error" role="alert">{error.message}</div>}

      <form className="card" onSubmit={onSubmit} noValidate>
        <h2 className="section-title">Patient information</h2>
        <div className="grid-2">
          <label className="field">
            <span>Full name</span>
            <input value={form.full_name} onChange={(e) => set('full_name', e.target.value)} required />
            {errors.full_name && <em className="field-error">{errors.full_name}</em>}
          </label>
          <label className="field">
            <span>Email</span>
            <input type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
            {errors.email && <em className="field-error">{errors.email}</em>}
          </label>
          <label className="field">
            <span>Phone</span>
            <input value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder="+977 …" />
          </label>
          <label className="field">
            <span>Address</span>
            <input value={form.address} onChange={(e) => set('address', e.target.value)} />
          </label>
          <label className="field">
            <span>Date of birth</span>
            <input type="date" value={form.date_of_birth} onChange={(e) => set('date_of_birth', e.target.value)} />
          </label>
          <label className="field">
            <span>Blood group</span>
            <select value={form.blood_group} onChange={(e) => set('blood_group', e.target.value)}>
              {bloodGroupOptions(form.blood_group).map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            {errors.blood_group && <em className="field-error">{errors.blood_group}</em>}
          </label>
          <label className="field">
            <span>Gestational week at registration</span>
            <input type="number" min={1} max={45} value={form.gestational_week_at_registration} onChange={(e) => set('gestational_week_at_registration', e.target.value)} />
          </label>
          <label className="field">
            <span>Estimated due date</span>
            <input type="date" value={form.estimated_due_date} onChange={(e) => set('estimated_due_date', e.target.value)} />
          </label>
          <label className="field">
            <span>Gravidity (total pregnancies)</span>
            <input type="number" min={0} value={form.gravidity} onChange={(e) => set('gravidity', e.target.value)} />
          </label>
          <label className="field">
            <span>Parity (births)</span>
            <input type="number" min={0} value={form.parity} onChange={(e) => set('parity', e.target.value)} />
          </label>
          <label className="field">
            <span>Emergency contact name</span>
            <input value={form.emergency_contact_name} onChange={(e) => set('emergency_contact_name', e.target.value)} />
          </label>
          <label className="field">
            <span>Emergency contact phone</span>
            <input value={form.emergency_contact_phone} onChange={(e) => set('emergency_contact_phone', e.target.value)} />
          </label>
        </div>

        <h2 className="section-title">Clinical information</h2>
        <label className="field"><span>Medical history notes</span>
          <textarea rows={3} value={form.medical_history_notes} onChange={(e) => set('medical_history_notes', e.target.value)} /></label>
        <label className="field"><span>Previous pregnancy / obstetric history notes</span>
          <textarea rows={3} value={form.obstetric_history_notes} onChange={(e) => set('obstetric_history_notes', e.target.value)} /></label>
        <label className="field"><span>Allergies</span>
          <textarea rows={2} value={form.allergies} onChange={(e) => set('allergies', e.target.value)} /></label>
        <label className="field"><span>Current medications</span>
          <textarea rows={2} value={form.current_medications} onChange={(e) => set('current_medications', e.target.value)} /></label>
        <label className="field"><span>Additional clinical notes</span>
          <textarea rows={2} value={form.additional_notes} onChange={(e) => set('additional_notes', e.target.value)} /></label>

        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save patient'}</button>
          <Link className="btn btn-secondary" to="/app/patients">Cancel</Link>
        </div>
      </form>
    </div>
  )
}