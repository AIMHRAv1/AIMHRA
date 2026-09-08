import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { adminPatientService } from '../../services/auth'
import { ErrorState, Loading, RiskBadge } from '../../components/ui'

export default function PatientHistory() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { adminPatientService.history(id).then(setData).catch(setError) }, [id])
  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!data) return <div className="page"><Loading /></div>
  return (
    <div className="page">
      <div className="muted small"><Link to="/app/patients">← Patients</Link></div>
      <h1>{data.patient.patient_code}</h1>
      <p className="muted">{data.patient.assessment_count} assessments</p>
      <div className="card">
        <h2 className="section-title">Assessment history</h2>
        {data.assessments.length === 0 ? <p className="muted">No assessments recorded.</p> : (
          <table className="data-table">
            <thead><tr><th>Date</th><th>Healthcare worker</th><th>Risk</th></tr></thead>
            <tbody>{data.assessments.map((a) => <tr key={a.id}><td>{a.visit_date}</td><td>{a.assessed_by || 'Unknown'}</td><td>{a.risk_level ? <RiskBadge level={a.risk_level} /> : '—'}</td></tr>)}</tbody>
          </table>
        )}
      </div>
    </div>
  )
}
