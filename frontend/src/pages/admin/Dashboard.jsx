import { useEffect, useState } from 'react'
import { adminService, modelService } from '../../services/auth'
import { RiskDistributionChart } from '../../charts'
import { ErrorState, Loading, StatCard } from '../../components/ui'

export default function AdminDashboard() {
  const [stats, setStats] = useState(null)
  const [diag, setDiag] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([adminService.stats(), modelService.diagnostics()])
      .then(([s, d]) => { setStats(s); setDiag(d) })
      .catch(setError)
  }, [])

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!stats) return <div className="page"><Loading /></div>

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>System overview</h1>
          <p className="muted">Users, assessments, model status and knowledge base.</p>
        </div>
      </header>

      <div className="stat-grid">
        <StatCard label="Staff users" value={stats.users?.total ?? 0}
                  sub={`${stats.users?.by_role?.HEALTHCARE_WORKER ?? 0} healthcare workers · ${stats.users?.by_role?.ADMIN ?? 0} admins`} />
        <StatCard label="Assessments" value={stats.assessments} sub={`${stats.predictions} predictions`} />
        <StatCard label="Open alerts" value={stats.alerts?.open ?? 0} tone={stats.alerts?.open ? 'warn' : undefined} />
        <StatCard label="Production model"
                  value={diag?.available ? `${diag.production.name}` : 'None'}
                  sub={diag?.available ? `${diag.production.version} · ${new Date(diag.production.trained_at).toLocaleDateString()}` : (diag?.reason || 'Not trained')}
                  tone={diag?.available ? 'good' : 'danger'} />
      </div>

      <div className="grid-2-cards">
        <div className="card">
          <h2 className="section-title">Risk distribution (all predictions)</h2>
          <RiskDistributionChart counts={stats.risk_distribution} />
        </div>
        <div className="card">
          <h2 className="section-title">Platform activity</h2>
          <dl className="kv kv-lg">
            <div><dt>Patients registered</dt><dd>{stats.patients}</dd></div>
            <div><dt>Chat sessions</dt><dd>{stats.chat_sessions}</dd></div>
            <div><dt>Knowledge documents</dt><dd>{stats.knowledge_documents}</dd></div>
            <div><dt>Reports generated</dt><dd>{stats.reports}</dd></div>
            <div><dt>Model versions</dt><dd>{stats.models?.total}</dd></div>
          </dl>
        </div>
      </div>
    </div>
  )
}
