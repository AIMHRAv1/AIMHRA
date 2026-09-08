import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { patientService } from '../../services/auth'
import { EmptyState, ErrorState, Loading, RiskBadge } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'

function ageFrom(dob) {
  if (!dob) return null
  const b = new Date(dob)
  const n = new Date()
  let age = n.getFullYear() - b.getFullYear()
  const m = n.getMonth() - b.getMonth()
  if (m < 0 || (m === 0 && n.getDate() < b.getDate())) age -= 1
  return age >= 0 ? age : null
}

function formatDate(value) {
  if (!value) return 'Not recorded'
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function trendLabel(direction, status) {
  if (!direction || direction === 'unknown') return 'No trend yet'
  const labels = {
    increasing: 'Increasing',
    decreasing: 'Decreasing',
    stable: 'Stable',
  }
  return `${direction === 'increasing' ? '▲' : direction === 'decreasing' ? '▼' : '▬'} ${labels[direction] || status || 'Recorded'}`
}

export default function PatientList() {
  const { user } = useAuth()
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
      (isAdmin
      ? [p.patient_code, p.last_assessed_by]
        : [p.patient_code, p.full_name, p.phone, p.email]
      ).some((v) => (v || '').toLowerCase().includes(q)),
    )
    const order = { 'high risk': 0, 'mid risk': 1, 'low risk': 2 }
    return filtered.sort((a, b) => {
      const ra = order[a.current_risk] ?? 3
      const rb = order[b.current_risk] ?? 3
      return ra - rb || new Date(b.created_at) - new Date(a.created_at)
    })
  }, [isAdmin, patients, search])

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!patients) return <div className="page"><Loading /></div>

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Patients</h1>
          <p className="muted">
            {isAdmin
              ? 'Read-only overview of patient codes, latest risk tiers and assessment history.'
              : 'Shared patient records, sorted by latest risk level so higher-priority care is easy to find.'}
          </p>
        </div>
        <div className="quick-actions">
          <input className="search" placeholder={isAdmin ? 'Search patient code / assessor…' : 'Search code / name / phone / email…'} value={search}
                 onChange={(e) => setSearch(e.target.value)} aria-label="Search patients" />
          {!isAdmin && <Link className="btn btn-primary" to="/app/patients/new">＋ Add Patient</Link>}
        </div>
      </header>

      {rows.length === 0 ? (
        <EmptyState
          title={search ? 'No matching patients' : 'No patients yet'}
          hint={search
            ? 'Try a different search term.'
            : isAdmin ? 'Patients registered by healthcare workers will appear here.' : 'Add a patient to start their maternal health record.'}
          action={!isAdmin && !search && <Link className="btn btn-primary" to="/app/patients/new">＋ Add Patient</Link>}
        />
      ) : (
        <div className={`card patient-list-card${isAdmin ? ' patient-list-admin' : ''}`}>
          <div className="patient-list-summary">
            <strong>{rows.length} patient{rows.length === 1 ? '' : 's'}</strong>
            <span className="muted small">Sorted by latest risk level</span>
          </div>
          <div className="table-scroll">
          <table className="data-table patient-table">
            <thead>
              <tr>
                <th>Patient</th>
                {!isAdmin && <><th>Contact details</th><th>Age</th><th>Gestational week</th></>}
                <th>{isAdmin ? 'Latest risk tier' : 'Latest risk level'}</th>
                {!isAdmin && <th>Confidence</th>}
                {!isAdmin && <th>Risk trend</th>}
                <th>Assessment count</th>
                {!isAdmin && <><th>Last assessment</th><th>Open alerts</th></>}
                {isAdmin && <th>Last assessed by</th>}
                {!isAdmin && <th></th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const age = ageFrom(p.date_of_birth)
                return (
                  <tr key={p.id} className={p.current_risk === 'high risk' ? 'row-warn' : ''}>
                    <td className="patient-identity">{isAdmin
                      ? <Link to={`/app/admin/patients/${p.id}`}>{p.patient_code}</Link>
                      : <Link to={`/app/patients/${p.id}?tab=overview`}>
                          <strong>{p.patient_code}</strong>{p.full_name && <span className="muted small"> · {p.full_name}</span>}
                        </Link>}</td>
                    {!isAdmin && <><td className="muted small">
                      {p.phone || '—'}{p.email ? <><br />{p.email}</> : null}
                    </td>
                    <td>{age != null ? age : (p.date_of_birth || '—')}</td>
                    <td>{p.gestational_week_at_registration ?? '—'}</td></>}
                    <td>
                      {p.current_risk
                        ? <RiskBadge level={p.current_risk} />
                        : <span className="muted">Not assessed</span>}
                    </td>
                    {!isAdmin && <td className="numeric-cell">{p.current_confidence != null ? `${Math.round(p.current_confidence * 100)}%` : 'Not available'}</td>}
                    {!isAdmin && <td>
                      <span className={`trend-arrow trend-${p.current_trend_direction || 'unknown'}`}>
                        {trendLabel(p.current_trend_direction, p.current_trend_status)}
                      </span>
                    </td>}
                    <td className="numeric-cell">{p.assessment_count ?? 0}</td>
                    {!isAdmin && <><td className="muted small">{formatDate(p.last_assessment_date)}</td><td>{p.open_alert_count ?? 0}</td></>}
                    {isAdmin && <td>{p.last_assessed_by || 'Not recorded'}</td>}
                    {!isAdmin && <td className="cell-actions">
                      <Link className="btn btn-small btn-secondary" to={`/app/patients/${p.id}?tab=overview`}>Open</Link>
                      <Link className="btn btn-small" to={`/app/patients/${p.id}?tab=assessment`}>Assess</Link>
                    </td>}
                  </tr>
                )
              })}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  )
}