import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { patientService } from '../../services/auth'
import { EmptyState, ErrorState, Loading, RiskBadge } from '../../components/ui'

function ageFrom(dob) {
  if (!dob) return null
  const b = new Date(dob)
  const n = new Date()
  let age = n.getFullYear() - b.getFullYear()
  const m = n.getMonth() - b.getMonth()
  if (m < 0 || (m === 0 && n.getDate() < b.getDate())) age -= 1
  return age >= 0 ? age : null
}

export default function PatientList() {
  const { user } = useAuth()
  // Administrators see codes and clinical analytics only — the API redacts
  // patient-identifying fields for them, so the identity columns are hidden.
  const isAdmin = user?.role === 'ADMIN'
  const [patients, setPatients] = useState(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    patientService.list()
      .then((d) => setPatients(d.results ?? []))
      .catch(setError)
  }, [])

  const rows = useMemo(() => {
    if (!patients) return []
    const q = search.trim().toLowerCase()
    const filtered = !q ? patients.slice() : patients.filter((p) =>
      [p.patient_code, p.full_name, p.phone, p.email].some((v) => (v || '').toLowerCase().includes(q)),
    )
    const order = { 'high risk': 0, 'mid risk': 1, 'low risk': 2 }
    return filtered.sort((a, b) => {
      const ra = order[a.current_risk] ?? 3
      const rb = order[b.current_risk] ?? 3
      return ra - rb || new Date(b.created_at) - new Date(a.created_at)
    })
  }, [patients, search])

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!patients) return <div className="page"><Loading /></div>

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Patients</h1>
          <p className="muted">
            {isAdmin
              ? 'Administrator view — patient information is not accessible. Codes and clinical analytics only.'
              : 'Patients you created or were assigned, sorted by current risk — high risk first.'}
          </p>
        </div>
        <div className="quick-actions">
          <input className="search" placeholder={isAdmin ? 'Search by code…' : 'Search code / name / phone / email…'} value={search}
                 onChange={(e) => setSearch(e.target.value)} aria-label="Search patients" />
          {!isAdmin && <Link className="btn btn-primary" to="/app/patients/new">+ Add Patient</Link>}
        </div>
      </header>

      {rows.length === 0 ? (
        <EmptyState
          title={search ? 'No matching patients' : 'No patients yet'}
          hint={search
            ? 'Try a different search term.'
            : isAdmin
              ? 'Patient records appear here once healthcare workers create them.'
              : 'Add a patient to start their maternal health record.'}
          action={!search && !isAdmin && <Link className="btn btn-primary" to="/app/patients/new">+ Add Patient</Link>}
        />
      ) : (
        <div className="card">
          <table className="data-table">
            <thead>
              <tr>
                <th>Code</th>
                {!isAdmin && <th>Name</th>}
                {!isAdmin && <th>Contact</th>}
                {!isAdmin && <th>Age / DOB</th>}
                {!isAdmin && <th>Gest. wk</th>}
                <th>Current risk</th>
                <th>Trend</th>
                <th>Assessments</th>
                <th>Last visit</th>
                <th>Open alerts</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const age = ageFrom(p.date_of_birth)
                return (
                  <tr key={p.id} className={p.current_risk === 'high risk' ? 'row-warn' : ''}>
                    <td><Link to={`/app/patients/${p.id}?tab=overview`}>{p.patient_code}</Link></td>
                    {!isAdmin && <td>{p.full_name || '—'}</td>}
                    {!isAdmin && (
                      <td className="muted small">
                        {p.phone || '—'}{p.email ? <><br />{p.email}</> : null}
                      </td>
                    )}
                    {!isAdmin && <td>{age != null ? age : (p.date_of_birth || '—')}</td>}
                    {!isAdmin && <td>{p.gestational_week_at_registration ?? '—'}</td>}
                    <td>
                      {p.current_risk
                        ? <RiskBadge level={p.current_risk} />
                        : <span className="muted">—</span>}
                      {p.current_confidence != null && (
                        <span className="muted small"> {Math.round(p.current_confidence * 100)}%</span>
                      )}
                    </td>
                    <td>
                      {p.current_trend_direction && p.current_trend_direction !== 'unknown'
                        ? <span className={`trend-arrow trend-${p.current_trend_direction}`}>
                            {p.current_trend_direction === 'increasing' ? '▲' : p.current_trend_direction === 'decreasing' ? '▼' : '▬'} {p.current_trend_status}
                          </span>
                        : <span className="muted">—</span>}
                    </td>
                    <td>{p.assessment_count ?? 0}</td>
                    <td className="muted small">{p.last_assessment_date || '—'}</td>
                    <td>{p.open_alert_count ?? 0}</td>
                    <td className="cell-actions">
                      <Link className="btn btn-small btn-secondary"
                            to={`/app/patients/${p.id}?tab=${isAdmin ? 'history' : 'overview'}`}>
                        {isAdmin ? 'History' : 'Open'}
                      </Link>
                      {!isAdmin && <Link className="btn btn-small" to={`/app/patients/${p.id}?tab=assessment`}>Assess</Link>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}