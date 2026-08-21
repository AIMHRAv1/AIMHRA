import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { assessmentService, patientService } from '../../services/auth'
import { EmptyState, ErrorState, Loading, RiskBadge } from '../../components/ui'

export default function PatientList() {
  const [patients, setPatients] = useState(null)
  const [trends, setTrends] = useState({})
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    async function load() {
      try {
        const d = await patientService.list()
        const list = d.results ?? []
        setPatients(list)
        // Fetch each patient's trend summary (small N in practice).
        const pairs = await Promise.all(list.map(async (p) => {
          try {
            const t = await assessmentService.trend(p.id)
            return [p.id, t?.trend ?? null]
          } catch { return [p.id, null] }
        }))
        setTrends(Object.fromEntries(pairs))
      } catch (e) { setError(e) }
    }
    load()
  }, [])

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!patients) return <div className="page"><Loading /></div>

  const filtered = patients.filter((p) =>
    [p.patient_code, p.full_name, p.username].some((v) => (v || '').toLowerCase().includes(search.toLowerCase()))
  )

  const filteredSorted = [...filtered].sort((a, b) => {
    const ra = trends[a.id]?.current ?? 'low risk'
    const rb = trends[b.id]?.current ?? 'low risk'
    const order = { 'high risk': 0, 'mid risk': 1, 'low risk': 2 }
    return (order[ra] ?? 3) - (order[rb] ?? 3)
  })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Patients</h1>
          <p className="muted">Sorted by current risk — high risk first.</p>
        </div>
        <input className="search" placeholder="Search code / name / username…" value={search}
               onChange={(e) => setSearch(e.target.value)} aria-label="Search patients" />
      </header>

      {filteredSorted.length === 0 ? (
        <EmptyState title="No patients found" hint={search ? 'Try a different search.' : 'No patients are assigned to you yet.'} />
      ) : (
        <div className="card">
          <table className="data-table">
            <thead><tr><th>Code</th><th>Name</th><th>Current risk</th><th>Trend</th><th>Visits</th></tr></thead>
            <tbody>
              {filteredSorted.map((p) => {
                const t = trends[p.id]
                return (
                  <tr key={p.id}>
                    <td><Link to={`/app/patients/${p.id}`}>{p.patient_code}</Link></td>
                    <td>{p.full_name || p.username}</td>
                    <td>{t?.current ? <RiskBadge level={t.current} /> : <span className="muted">—</span>}</td>
                    <td>
                      {t && t.direction !== 'unknown'
                        ? <span className={`trend-arrow trend-${t.direction}`}>
                            {t.direction === 'increasing' ? '▲' : t.direction === 'decreasing' ? '▼' : '▬'} {t.status}
                          </span>
                        : <span className="muted">—</span>}
                    </td>
                    <td>{t?.visits ?? 0}</td>
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
