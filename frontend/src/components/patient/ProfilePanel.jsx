import { useState } from 'react'
import { patientService } from '../../services/auth'
import { apiError } from '../../api/client'
import { bloodGroupOptions } from '../../constants/clinical'

const EMPTY = {
  full_name: '', email: '', phone: '', address: '',
  date_of_birth: '', blood_group: '', gestational_week_at_registration: '',
  estimated_due_date: '', gravidity: '', parity: '',
  medical_history_notes: '', allergies: '',
  emergency_contact_name: '', emergency_contact_phone: '',
  obstetric_history_notes: '', current_medications: '', additional_notes: '',
}

export default function ProfilePanel({ patient, onSaved }) {
  const [form, setForm] = useState(() => ({ ...EMPTY, ...patient }))
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState(null)
  const [error, setError] = useState(null)
  const [errors, setErrors] = useState({})

  function set(k, v) {
    setForm((f) => ({ ...f, [k]: v }))
    setNotice(null)
    setErrors((e) => ({ ...e, [k]: undefined }))
  }

  async function onSubmit(e) {
    e.preventDefault()
    setSaving(true)
    setNotice(null)
    setError(null)
    try {
      const payload = { ...form }
      for (const k of ['date_of_birth', 'estimated_due_date']) if (!payload[k]) payload[k] = null
      for (const k of ['gestational_week_at_registration', 'gravidity', 'parity']) {
        payload[k] = payload[k] === '' || payload[k] == null ? null : Number(payload[k])
      }
      const d = await patientService.update(patient.id, payload)
      setForm({ ...EMPTY, ...d })
      setNotice('Patient information saved.')
      setEditing(false)
      if (onSaved) onSaved(d)
    } catch (err) {
      const e2 = apiError(err)
      setNotice(null)
      setError(e2)
      setErrors(
        e2.details && typeof e2.details === 'object'
          ? Object.fromEntries(Object.entries(e2.details).map(([k, v]) => [k, Array.isArray(v) ? v.join(' ') : String(v)]))
          : {},
      )
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    const display = (value) => value === '' || value == null ? '—' : value
    return (
      <div className="card">
        <div className="page-head">
          <h2 className="section-title">Patient profile — {patient.patient_code}</h2>
          <button type="button" className="btn btn-primary" onClick={() => setEditing(true)}>Edit information</button>
        </div>
        {notice && <div className="alert alert-success">{notice}</div>}
        <h3 className="section-title">Personal information</h3>
        <dl className="kv">
          <div><dt>Full name</dt><dd>{display(patient.full_name)}</dd></div>
          <div><dt>Email</dt><dd>{display(patient.email)}</dd></div>
          <div><dt>Phone</dt><dd>{display(patient.phone)}</dd></div>
          <div><dt>Date of birth</dt><dd>{display(patient.date_of_birth)}</dd></div>
          <div><dt>Blood group</dt><dd>{display(patient.blood_group)}</dd></div>
          <div><dt>Address</dt><dd>{display(patient.address)}</dd></div>
          <div><dt>Gestational week at registration</dt><dd>{display(patient.gestational_week_at_registration)}</dd></div>
          <div><dt>Estimated due date</dt><dd>{display(patient.estimated_due_date)}</dd></div>
          <div><dt>Gravidity</dt><dd>{display(patient.gravidity)}</dd></div>
          <div><dt>Parity</dt><dd>{display(patient.parity)}</dd></div>
          <div><dt>Emergency contact</dt><dd>{display(patient.emergency_contact_name)}</dd></div>
          <div><dt>Emergency contact phone</dt><dd>{display(patient.emergency_contact_phone)}</dd></div>
        </dl>
        <h3 className="section-title">Clinical information</h3>
        <dl className="kv kv-lg">
          <div><dt>Medical history</dt><dd>{display(patient.medical_history_notes)}</dd></div>
          <div><dt>Previous pregnancy / obstetric history</dt><dd>{display(patient.obstetric_history_notes)}</dd></div>
          <div><dt>Allergies</dt><dd>{display(patient.allergies)}</dd></div>
          <div><dt>Current medications</dt><dd>{display(patient.current_medications)}</dd></div>
          <div><dt>Additional clinical notes</dt><dd>{display(patient.additional_notes)}</dd></div>
        </dl>
      </div>
    )
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <div className="page-head">
        <h2 className="section-title">Edit patient profile — {patient.patient_code}</h2>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={saving}
          onClick={() => {
            setForm({ ...EMPTY, ...patient })
            setErrors({})
            setError(null)
            setNotice(null)
            setEditing(false)
          }}
        >
          Cancel
        </button>
      </div>
      {notice && <div className="alert alert-success">{notice}</div>}
      {error && <div className="alert alert-error" role="alert">{error.message}</div>}
      <div className="grid-2">
        <label className="field"><span>Full name</span>
          <input value={form.full_name} onChange={(e) => set('full_name', e.target.value)} required />
          {errors.full_name && <em className="field-error">{errors.full_name}</em>}</label>
        <label className="field"><span>Email</span>
          <input type="email" value={form.email} onChange={(e) => set('email', e.target.value)} /></label>
        <label className="field"><span>Phone</span>
          <input value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder="+977 …" /></label>
        <label className="field"><span>Date of birth</span>
          <input type="date" value={form.date_of_birth ?? ''} onChange={(e) => set('date_of_birth', e.target.value)} /></label>
        <label className="field"><span>Blood group</span>
          <select value={form.blood_group ?? ''} onChange={(e) => set('blood_group', e.target.value)}>
            {bloodGroupOptions(form.blood_group).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {errors.blood_group && <em className="field-error">{errors.blood_group}</em>}</label>
        <label className="field"><span>Gestational week at registration</span>
          <input type="number" min={1} max={45} value={form.gestational_week_at_registration ?? ''} onChange={(e) => set('gestational_week_at_registration', e.target.value)} /></label>
        <label className="field"><span>Estimated due date</span>
          <input type="date" value={form.estimated_due_date ?? ''} onChange={(e) => set('estimated_due_date', e.target.value)} /></label>
        <label className="field"><span>Gravidity (total pregnancies)</span>
          <input type="number" min={0} value={form.gravidity ?? ''} onChange={(e) => set('gravidity', e.target.value)} /></label>
        <label className="field"><span>Parity (births)</span>
          <input type="number" min={0} value={form.parity ?? ''} onChange={(e) => set('parity', e.target.value)} /></label>
        <label className="field"><span>Address</span>
          <input value={form.address} onChange={(e) => set('address', e.target.value)} /></label>
        <label className="field"><span>Emergency contact name</span>
          <input value={form.emergency_contact_name} onChange={(e) => set('emergency_contact_name', e.target.value)} /></label>
        <label className="field"><span>Emergency contact phone</span>
          <input value={form.emergency_contact_phone} onChange={(e) => set('emergency_contact_phone', e.target.value)} /></label>
      </div>
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
        <button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save patient information'}</button>
      </div>
    </form>
  )
}