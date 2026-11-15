import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { adminPatientService } from '../../services/auth'
import { ErrorState, Loading, RiskBadge } from '../../components/ui'
import { RiskTrendChart } from '../../charts'
import MeasurementHistory from '../../components/patient/MeasurementHistory'
import RecommendationsPanel from '../../components/patient/RecommendationsPanel'

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
      {data.assessments.length > 0 && (
        <>
          <div className="card">
            <h2 className="section-title">Risk classification over time</h2>
            <RiskTrendChart series={data.assessments.filter((item) => item.risk_level)} />
            <p className="muted small">
              Latest risk: <b>{data.trend.current || 'Not available'}</b>
              {data.trend.previous && <> · previous: <b>{data.trend.previous}</b> · change <b>{data.trend.change}</b></>}
              {!data.trend.previous && data.trend.current && <> · baseline (no previous prediction)</>}
              {!data.trend.current && <> · no prediction recorded for the latest assessment</>}
            </p>
          </div>
          <MeasurementHistory series={data.assessments} changes={data.measurement_trends} />
        </>
      )}
      <div className="card">
        <h2 className="section-title">Assessment history</h2>
        {data.assessments.length === 0 ? <p className="muted">No assessments recorded.</p> : (
          <table className="data-table">
            <thead><tr><th>Date</th><th>Healthcare worker</th><th>Risk</th></tr></thead>
            <tbody>{data.assessments.map((a) => <tr key={a.id}><td>{a.visit_date}</td><td>{a.assessed_by || 'Unknown'}</td><td>{a.risk_level ? <RiskBadge level={a.risk_level} /> : '—'}</td></tr>)}</tbody>
          </table>
        )}
      </div>
      {data.assessments.filter((item) => Object.values(item.recommendations || {}).some((entries) => entries.length))
        .map((item) => (
          <div key={item.id}>
            <h2 className="section-title">Recommendations from {item.visit_date}</h2>
            <RecommendationsPanel recommendations={item.recommendations} />
          </div>
        ))}
    </div>
  )
}
