import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { assessmentService } from '../../services/auth'
import { RiskTrendChart } from '../../charts'
import { CategoryBadge, Disclaimer, EmptyState, ErrorState, Loading, RiskBadge, StatCard } from '../../components/ui'

export default function PatientDashboard() {
  const [trend, setTrend] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [t, a] = await Promise.all([
          assessmentService.trend(),
          assessmentService.alerts({ status: 'OPEN' }),
        ])
        setTrend(t)
        setAlerts((a?.results ?? a?.alerts ?? []).slice(0, 4))
      } catch (e) {
        setError(e)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) return <div className="page"><Loading /></div>
  if (error) return <div className="page"><ErrorState error={error} /></div>

  const t = trend?.trend
  const series = trend?.series ?? []
  const latest = series[series.length - 1]

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Your health dashboard</h1>
          <p className="muted">Current risk, trends across your visits and active alerts.</p>
        </div>
        <div className="quick-actions">
          <Link className="btn btn-primary" to="/app/assessment">＋ New assessment</Link>
          <Link className="btn btn-secondary" to="/app/chat">💬 Ask AIMHRA</Link>
        </div>
      </header>

      <div className="stat-grid">
        <StatCard
          label="Current risk"
          value={latest ? <RiskBadge level={latest.risk_level} size="lg" /> : '—'}
          sub={latest ? `Confidence ${Math.round(latest.probability * 100)}% · ${latest.visit_date}` : 'No assessments yet'}
          tone={latest?.risk_level === 'high risk' ? 'danger' : undefined}
        />
        <StatCard
          label="Risk direction"
          value={t?.status === 'no_data' ? '—' : t.status.charAt(0).toUpperCase() + t.status.slice(1)}
          sub={t?.previous ? `Previous: ${t.previous}` : 'Single visit so far'}
          tone={t?.status === 'increasing' ? 'danger' : t?.status === 'improving' ? 'good' : undefined}
        />
        <StatCard label="Visits recorded" value={t?.visits ?? 0} sub="Longitudinal tracking" />
        <StatCard label="Open alerts" value={alerts.length} sub="Rule-based warnings" tone={alerts.length ? 'warn' : undefined} />
      </div>

      {alerts.length > 0 && (
        <div className="card">
          <h2 className="section-title">Active alerts</h2>
          <ul className="alert-list">
            {alerts.map((a) => (
              <li key={a.id} className={`alert-item cat-${a.category}`}>
                <CategoryBadge category={a.category} />
                <span>{a.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <h2 className="section-title">Risk trend across visits</h2>
        {series.length > 0
          ? <RiskTrendChart series={series} />
          : <EmptyState title="No visits yet" hint="Complete your first assessment to start tracking your risk trend."
                        action={<Link className="btn btn-primary" to="/app/assessment">Start first assessment</Link>} />}
        {series.length > 0 && (
          <p className="muted small">Trends describe stored assessments only — the system does not predict future risk.</p>
        )}
      </div>

      <Disclaimer />
    </div>
  )
}
