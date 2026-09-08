import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { assessmentService, patientService, reportService } from '../../services/auth'
import { apiError } from '../../api/client'
import { RiskTrendChart, ShapBars } from '../../charts'
import { CategoryBadge, Disclaimer, EmptyState, ErrorState, Loading, RiskBadge, StatCard } from '../../components/ui'
import AssessmentPanel from '../../components/patient/AssessmentPanel'
import HistoryPanel from '../../components/patient/HistoryPanel'
import ChatPanel from '../../components/patient/ChatPanel'
import ProfilePanel from '../../components/patient/ProfilePanel'
import AlertsPanel from '../../components/patient/AlertsPanel'
import ReportsPanel from '../../components/patient/ReportsPanel'
import { downloadReport } from '../../utils/reportDownload'

const ALL_TABS = [
  { key: 'overview', label: 'Overview', icon: '▦' },
  { key: 'info', label: 'Patient Information', icon: '👤' },
  { key: 'assessment', label: 'New Assessment', icon: '＋' },
  { key: 'history', label: 'History & Trend', icon: '📈' },
  { key: 'alerts', label: 'Alerts', icon: '🔔' },
  { key: 'chat', label: 'AI Assistant', icon: '💬' },
  { key: 'reports', label: 'Reports', icon: '📄' },
]

function computeAge(dateOfBirth) {
  if (!dateOfBirth) return null
  const dob = new Date(dateOfBirth)
  const now = new Date()
  let age = now.getFullYear() - dob.getFullYear()
  const m = now.getMonth() - dob.getMonth()
  if (m < 0 || (m === 0 && now.getDate() < dob.getDate())) age -= 1
  return age >= 0 ? age : null
}

export default function PatientDetail() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'ADMIN'
  const tabs = isAdmin ? ALL_TABS.filter((t) => ['overview', 'assessment'].includes(t.key)) : ALL_TABS
  const { id: idParam } = useParams()
  const id = Number(idParam)
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = tabs.some((t) => t.key === searchParams.get('tab')) ? searchParams.get('tab') : 'overview'

  const [patient, setPatient] = useState(null)
  const [trend, setTrend] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [assessments, setAssessments] = useState([])
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    setPatient(null)
    setSelected(null)
    try {
      const [p, t, a, h] = await Promise.all([
        patientService.detail(id),
        assessmentService.trend(id),
        assessmentService.alerts({ patient: id }),
        assessmentService.list({ patient: id }),
      ])
      setPatient(p)
      setTrend(t)
      setAlerts((a.results ?? []).filter((x) => x.patient === id))
      const list = h.results ?? []
      setAssessments(list)
      if (list[0]) setSelected(list[0])
    } catch (e) {
      setError(apiError(e))
    }
  }, [id])

  useEffect(() => { load() }, [load])

  const setTab = useCallback((key) => {
    setSearchParams({ tab: key }, { replace: true })
  }, [setSearchParams])

  const handlePatientSaved = useCallback((updated) => {
    setPatient((prev) => ({ ...prev, ...updated }))
  }, [])

  const age = useMemo(() => computeAge(patient?.date_of_birth), [patient])

  async function generateReport(assessmentId) {
    setBusy(true)
    try {
      const d = await reportService.generate(assessmentId)
      await downloadReport(d.report.id)
    } catch (e) {
      setError(apiError(e))
    } finally {
      setBusy(false)
    }
  }

  if (error) return (
    <div className="page">
      <ErrorState error={error} onRetry={load} />
      <Link className="btn btn-secondary" to="/app/patients">← All patients</Link>
    </div>
  )
  if (!patient) return <div className="page"><Loading /></div>
  if (isAdmin) {
    return <AdminPatientView patient={patient} tab={tab} tabs={tabs} setTab={setTab} />
  }

  const series = trend?.series ?? []
  const t = trend?.trend
  const latest = series[series.length - 1]
  const currentRisk = patient.current_risk || latest?.risk_level
  const currentConfidence = patient.current_confidence ?? latest?.probability

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="muted small"><Link to="/app/patients">← All patients</Link></div>
          <h1>{patient.patient_code}</h1>
          <p className="muted">
            {patient.full_name || 'Unnamed patient'}
            {age != null && <span> · Age {age}</span>}
            {patient.gestational_week_at_registration != null && <span> · Gest. wk {patient.gestational_week_at_registration}</span>}
            {patient.blood_group && <span> · {patient.blood_group}</span>}
          </p>
          <p className="muted small">
            Created {new Date(patient.created_at).toLocaleDateString()}
            {patient.updated_at && <span> · updated {new Date(patient.updated_at).toLocaleDateString()}</span>}
            {!patient.is_active && <span className="alert-error" style={{ padding: '2px 8px', borderRadius: 6, marginLeft: 8 }}>ARCHIVED</span>}
          </p>
        </div>
        <div className="quick-actions">
          {currentRisk ? (
            <span className="muted small">
              Current risk <RiskBadge level={currentRisk} size="lg" />
              {currentConfidence != null && <span className="muted"> · confidence {Math.round(currentConfidence * 100)}%</span>}
            </span>
          ) : <span className="muted small">No assessment yet</span>}
          <button className="btn btn-primary" onClick={() => setTab('assessment')}>＋ New Assessment</button>
          <button className="btn btn-secondary" onClick={() => setTab('info')}>Edit Patient</button>
        </div>
      </header>

      <nav className="tabs" aria-label="Patient workspace">
        {tabs.map((t) => (
          <button key={t.key} className={`tab${tab === t.key ? ' active' : ''}`} onClick={() => setTab(t.key)}>
            <span aria-hidden="true">{t.icon}</span> {t.label}
          </button>
        ))}
      </nav>

      <div className="tab-panel">
        {tab === 'overview' && (
          <OverviewTab
            patient={patient}
            trend={trend}
            alerts={alerts}
            assessments={assessments}
            selected={selected}
            setSelected={setSelected}
            onNewAssessment={() => setTab('assessment')}
            onViewHistory={() => setTab('history')}
            onGenerateReport={generateReport}
            busy={busy}
          />
        )}
        {tab === 'info' && <ProfilePanel patient={patient} onSaved={handlePatientSaved} />}
        {tab === 'assessment' && (
          <AssessmentPanel
            patient={patient}
            onViewHistory={() => setTab('history')}
            onAskAssistant={() => setTab('chat')}
          />
        )}
        {tab === 'history' && <HistoryPanel patientId={id} />}
        {tab === 'alerts' && <AlertsPanel patientId={id} showStatus="ALL" />}
        {tab === 'chat' && <ChatPanel patientId={id} />}
        {tab === 'reports' && <ReportsPanel patientId={id} />}
      </div>
    </div>
  )
}

function AdminPatientView({ patient, tab, tabs, setTab }) {
 return (
   <div className="page">
     <header className="page-head">
       <div>
         <div className="muted small"><Link to="/app/patients">← All patients</Link></div>
         <h1>{patient.patient_code}</h1>
         <p className="muted">Administrator patient view</p>
       </div>
       <div className="quick-actions">
         <span className="muted small">Risk tier </span>
         {patient.current_risk ? <RiskBadge level={patient.current_risk} size="lg" /> : <span className="muted">—</span>}
         <button className="btn btn-primary" onClick={() => setTab('assessment')}>＋ Assess</button>
       </div>
     </header>
     <nav className="tabs" aria-label="Patient workspace">
       {tabs.map((t) => (
         <button key={t.key} className={`tab${tab === t.key ? ' active' : ''}`} onClick={() => setTab(t.key)}>
           <span aria-hidden="true">{t.icon}</span> {t.label}
         </button>
       ))}
     </nav>
     <div className="tab-panel">
       {tab === 'overview' && (
         <div className="stat-grid">
           <StatCard label="Patient code" value={patient.patient_code} />
           <StatCard label="Assigned healthcare worker" value={patient.assigned_healthcare_worker || 'Unassigned'} />
           <StatCard label="Risk tier" value={patient.current_risk ? <RiskBadge level={patient.current_risk} /> : '—'} />
           <StatCard label="Assessments" value={patient.assessment_count ?? 0} />
         </div>
       )}
       {tab === 'assessment' && (
         <AssessmentPanel patient={patient} onViewHistory={() => setTab('overview')} onAskAssistant={() => setTab('overview')} />
       )}
     </div>
   </div>
 )
}

function OverviewTab({
  patient, trend, alerts, assessments, selected, setSelected,
  onNewAssessment, onViewHistory, onGenerateReport, busy,
}) {
  const series = trend?.series ?? []
  const t = trend?.trend
  const latest = series[series.length - 1]
  const openAlerts = (alerts || []).filter((a) => a.status === 'OPEN' || a.status === 'ACKNOWLEDGED')
  const emergency = (alerts || []).filter((a) => a.category === 'EMERGENCY')

  return (
    <div className="stack">
      <div className="stat-grid">
        <StatCard
          label="Current risk"
          value={latest ? <RiskBadge level={latest.risk_level} size="lg" /> : '—'}
          sub={latest ? `${Math.round(latest.probability * 100)}% confidence · ${latest.visit_date}` : 'No assessments yet'}
          tone={latest?.risk_level === 'high risk' ? 'danger' : undefined}
        />
        <StatCard
          label="Risk direction"
          value={!t || t.status === 'no_data' ? '—' : t.status.charAt(0).toUpperCase() + t.status.slice(1)}
          sub={t?.previous ? `Previous: ${t.previous}` : 'Single visit so far'}
          tone={t?.status === 'increasing' ? 'danger' : t?.status === 'improving' ? 'good' : undefined}
        />
        <StatCard label="Visits recorded" value={t?.visits ?? 0} sub="Stored assessments" />
        <StatCard label="Open alerts" value={openAlerts.length} sub="Rule-based warnings" tone={openAlerts.length ? 'warn' : undefined} />
      </div>

      {emergency.length > 0 && (
        <div className="alert alert-emergency" role="alert">
          <strong>⛔ {emergency.length} emergency alert{emergency.length > 1 ? 's' : ''}</strong>
          <p>{emergency[0].message}</p>
        </div>
      )}

      {alertOpenStrip(alerts)}

      <div className="card">
        <h2 className="section-title">Risk trend across visits</h2>
        {series.length > 0 ? (
          <>
            <RiskTrendChart series={series} />
            {t && t.previous && (
              <p>Previous <RiskBadge level={t.previous} /> → Current <RiskBadge level={t.current} /> ({t.status})</p>
            )}
            <p className="muted small">Trends describe stored assessments only — the system does not predict future risk.</p>
          </>
        ) : (
          <EmptyState
            title="No assessments yet"
            hint="Perform the first maternal health risk assessment to start tracking."
            action={<button className="btn btn-primary" onClick={onNewAssessment}>＋ New Assessment</button>}
          />
        )}
      </div>

      <div className="card">
        <h2 className="section-title">Latest assessment & explanation</h2>
        {assessments.length === 0 ? (
          <EmptyState title="No assessment recorded" hint="Use New Assessment to run the full ML + SHAP + rule-engine pipeline." />
        ) : (
          <>
            <div className="chip-row">
              {assessments.map((a) => (
                <button key={a.id} className={`chip${selected?.id === a.id ? ' active' : ''}`}
                        onClick={() => setSelected(a)}>
                  {a.visit_date} {a.prediction && `· ${a.prediction.risk_level.replace(' risk', '')}`}
                </button>
              ))}
            </div>
            {selected?.prediction ? (
              <div className="detail-grid">
                <div>
                  <RiskBadge level={selected.prediction.risk_level} size="lg" />
                  <p className="muted small">
                    Assessed by {selected.assessed_by || 'Unknown'} · Confidence {Math.round(selected.prediction.probability * 100)}% · model {selected.prediction.model.name} {selected.prediction.model.version}
                  </p>
                  <dl className="kv">
                    <div><dt>Visit date</dt><dd>{selected.visit_date}</dd></div>
                    <div><dt>Gestational week</dt><dd>{selected.gestational_week ?? '—'}</dd></div>
                    <div><dt>Age</dt><dd>{selected.age}</dd></div>
                    <div><dt>BP</dt><dd>{selected.systolic_bp}/{selected.diastolic_bp} mm Hg</dd></div>
                    <div><dt>Heart rate</dt><dd>{selected.heart_rate} bpm</dd></div>
                    <div><dt>Temperature</dt><dd>{selected.body_temperature} °F</dd></div>
                    <div><dt>BMI</dt><dd>{selected.bmi}</dd></div>
                    <div><dt>Symptoms</dt><dd>{selected.symptoms?.length ? selected.symptoms.join(', ') : 'none'}</dd></div>
                  </dl>
                  <button className="btn btn-small btn-secondary" disabled={busy}
                          onClick={() => onGenerateReport(selected.id)}>Generate &amp; download PDF report</button>
                  <button className="btn btn-small" onClick={onViewHistory}>View history &amp; trend</button>
                </div>
                <div>
                  <h3 className="section-title">SHAP explanation</h3>
                  <p className="muted small">Assessment performed by {selected.assessed_by || 'Unknown'}</p>
                  <ShapBars features={selected.prediction.explanation?.features} />
                  <Disclaimer text={selected.prediction.explanation?.disclaimer} />
                </div>
              </div>
            ) : <p className="muted">No prediction stored for this assessment.</p>}
          </>
        )}
      </div>

      <Disclaimer />
    </div>
  )
}

function alertOpenStrip(alerts) {
  const open = (alerts || []).filter((a) => a.status === 'OPEN' || a.status === 'ACKNOWLEDGED')
  if (open.length === 0) return null
  return (
    <div className="card">
      <h2 className="section-title">Active alerts</h2>
      <ul className="alert-list">
        {open.slice(0, 4).map((a) => (
          <li key={a.id} className={`alert-item cat-${a.category}`}>
            <CategoryBadge category={a.category} />
            <span>{a.message}</span>
            <span className="muted small">{new Date(a.created_at).toLocaleString()} · {a.status}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}