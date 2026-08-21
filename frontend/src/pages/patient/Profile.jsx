import { useEffect, useState } from 'react'
import { patientService } from '../../services/auth'
import { apiError } from '../../api/client'
import { ErrorState, Loading } from '../../components/ui'

export default function Profile() {
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState(null)

  useEffect(() => {
    patientService.myProfile().then((d) => setProfile(d)).catch(setError)
  }, [])

  function set(k, v) { setProfile({ ...profile, [k]: v }) }

  async function onSubmit(e) {
    e.preventDefault()
    setSaving(true)
    setNotice(null)
    try {
      const d = await patientService.updateMyProfile(profile)
      setProfile(d)
      setNotice('Profile saved.')
    } catch (err) { setNotice(apiError(err).message) } finally { setSaving(false) }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!profile) return <div className="page"><Loading /></div>

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>My maternal profile</h1>
          <p className="muted">Patient code <code>{profile.patient_code}</code> — this code identifies you to healthcare staff.</p>
        </div>
      </header>
      {notice && <div className="alert alert-info">{notice}</div>}
      <form className="card" onSubmit={onSubmit}>
        <div className="grid-2">
          <label className="field"><span>Date of birth</span>
            <input type="date" value={profile.date_of_birth ?? ''} onChange={(e) => set('date_of_birth', e.target.value)} /></label>
          <label className="field"><span>Blood group</span>
            <input value={profile.blood_group} onChange={(e) => set('blood_group', e.target.value)} placeholder="e.g. O+" /></label>
          <label className="field"><span>Gestational week at registration</span>
            <input type="number" min={1} max={45} value={profile.gestational_week_at_registration ?? ''} onChange={(e) => set('gestational_week_at_registration', e.target.value)} /></label>
          <label className="field"><span>Estimated due date</span>
            <input type="date" value={profile.estimated_due_date ?? ''} onChange={(e) => set('estimated_due_date', e.target.value)} /></label>
          <label className="field"><span>Gravidity (total pregnancies)</span>
            <input type="number" min={0} value={profile.gravidity ?? ''} onChange={(e) => set('gravidity', e.target.value)} /></label>
          <label className="field"><span>Parity (births)</span>
            <input type="number" min={0} value={profile.parity ?? ''} onChange={(e) => set('parity', e.target.value)} /></label>
        </div>
        <label className="field"><span>Medical history notes</span>
          <textarea rows={3} value={profile.medical_history_notes} onChange={(e) => set('medical_history_notes', e.target.value)} /></label>
        <label className="field"><span>Allergies</span>
          <textarea rows={2} value={profile.allergies} onChange={(e) => set('allergies', e.target.value)} /></label>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>
        </div>
      </form>
    </div>
  )
}
