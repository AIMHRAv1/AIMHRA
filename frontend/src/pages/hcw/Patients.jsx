import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { patientService } from '../../services/auth'
import { EmptyState, ErrorState, Loading, RiskBadge } from '../../components/ui'
import { ageFromDateOfBirth, currentGestationalWeek } from '../../utils/patientDates'
import WorkerAvatar from '../../components/WorkerAvatar'

export default function PatientList() {
  const { user } = useAuth()
  // Administrators see codes and clinical analytics only — the API redacts
  // patient-identifying fields for them, so the identity columns are hidden.
  const isAdmin = user?.role === 'ADMIN'
  const [patients, setPatients] = useState(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    const timer = window.setTimeout(async () => {
      try {
        setError(null)
        const firstPage = await patientService.list({ search: search.trim(), page_size: 100 })
        const pages = firstPage.pages ?? 1
        const remainingPages = await Promise.all(
          Array.from({ length: Math.max(0, pages - 1) }, (_, index) =>
            patientService.list({ search: search.trim(), page_size: 100, page: index + 2 }),
          ),
        )
        if (active) {
          setPatients([
            ...(firstPage.results ?? []),
            ...remainingPages.flatMap((page) => page.results ?? []),
          ])
        }
      } catch (loadError) {
        if (active) setError(loadError)
      }
    }, search ? 250 : 0)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [search])

  const rows = useMemo(() => {
    if (!patients) return []
    const filtered = patients.slice()
    const order = { 'high risk': 0, 'mid risk': 1, 'low risk': 2 }
    return filtered.sort((a, b) => {
      if (!isAdmin) {
        return (b.last_assessment_date || '').localeCompare(a.last_assessment_date || '')
          || new Date(b.created_at) - new Date(a.created_at)
      }
      const ra = order[a.current_risk] ?? 3
      const rb = order[b.current_risk] ?? 3
      return ra - rb || new Date(b.created_at) - new Date(a.created_at)
    })
  }, [patients, isAdmin])

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!patients) return <div className="page"><Loading /></div>

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Patients</h1>
          <p className="muted">
            {isAdmin
              ? 'Administrator view — patient information is not accessible. Patient IDs and clinical summaries only.'
              : 'Patients you created or were assigned, sorted by current risk — high risk first.'}
          </p>
        </div>
        <div className="quick-actions">
          <input className="search" placeholder={isAdmin ? 'Search by code…' : 'Search code / name / phone / email…'} value={search}
                 onChange={(e) => setSearch(e.target.value)} aria-label="Search patients" />
          {!isAdmin && <Link className="btn btn-primary" to="/app/patients/new">+ Add Patient</Link>}
        </div>
      </header>

      <p className="muted small patient-count" aria-live="polite">
        {rows.length} {rows.length === 1 ? 'patient' : 'patients'}{search.trim() ? ' found' : ''}
      </p>
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
        <div>
          <div className="card table-scroll">
            <table className={`data-table${isAdmin ? '' : ' patient-list-table'}`}>
              <thead>
                <tr>
                  <th>{isAdmin ? 'Patient ID' : 'Code'}</th>
                  {!isAdmin && <th>Name</th>}
                  {!isAdmin && <th>Contact</th>}
                  {!isAdmin && <th>Age / DOB</th>}
                  {!isAdmin && <th>Gestational week</th>}
                  {isAdmin && <th>Latest risk tier</th>}
                  {isAdmin && <th>Trend</th>}
                  <th>{isAdmin ? 'Assessment count' : 'Assessments'}</th>
                  {isAdmin
                    ? <th>Last assessed by</th>
                    : <><th>Last visit</th><th>Last assessed by</th></>}
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const age = ageFromDateOfBirth(p.date_of_birth)
                  const gestationalWeek = currentGestationalWeek(
                    p.gestational_week_at_registration,
                    p.created_at,
                  )
                  return (
                    <tr key={p.id} className={p.current_risk === 'high risk' ? 'row-warn' : ''}>
                      <td>
                        <Link className="worker-cell" to={`/app/patients/${p.id}?tab=overview`}>
                          {!isAdmin && <WorkerAvatar src={p.photo_url} name={p.full_name || 'Patient'} size={30} />}
                          {p.patient_code}
                        </Link>
                      </td>
                      {!isAdmin && <td>{p.full_name || '—'}</td>}
                      {!isAdmin && (
                        <td className="muted small patient-list-contact" title={[p.phone, p.email].filter(Boolean).join(' · ')}>
                          {[p.phone, p.email].filter(Boolean).join(' · ') || '—'}
                        </td>
                      )}
                      {!isAdmin && <td>{age != null ? age : (p.date_of_birth || '—')}</td>}
                      {!isAdmin && <td>{gestationalWeek != null ? `${gestationalWeek} wk` : '—'}</td>}
                      {isAdmin && (
                        <td>
                          {p.current_risk
                            ? <RiskBadge level={p.current_risk} />
                            : <span className="muted">—</span>}
                        </td>
                      )}
                      {isAdmin && (
                        <td>
                          {p.current_trend_direction && p.current_trend_direction !== 'unknown'
                            ? <span className={`trend-arrow trend-${p.current_trend_direction}`}>
                                {p.current_trend_direction === 'increasing' ? '▲' : p.current_trend_direction === 'decreasing' ? '▼' : '▬'} {p.current_trend_status}
                              </span>
                            : <span className="muted">—</span>}
                        </td>
                      )}
                      <td>{p.assessment_count ?? 0}</td>
                      {isAdmin
                        ? <td><span className="worker-cell"><WorkerAvatar src={p.last_assessed_by_photo_url} name={p.last_assessed_by} size={28} />{p.last_assessed_by || '—'}</span></td>
                        : <><td className="muted small">{p.last_assessment_date || '—'}</td><td><span className="worker-cell"><WorkerAvatar src={p.last_assessed_by_photo_url} name={p.last_assessed_by} size={28} />{p.last_assessed_by || '—'}</span></td></>}
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
        </div>
      )}
    </div>
  )
}