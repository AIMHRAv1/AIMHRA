/** Shared UI primitives: risk badge, states, stat cards.
 * Risk levels always pair color with a text label + icon (never color-only). */

const RISK_STYLES = {
  'low risk': { cls: 'risk-low', icon: '✓', label: 'LOW RISK' },
  'mid risk': { cls: 'risk-mid', icon: '!', label: 'MID RISK' },
  'high risk': { cls: 'risk-high', icon: '⚠', label: 'HIGH RISK' },
}

const CATEGORY_STYLES = {
  NORMAL: { cls: 'risk-low', icon: '✓', label: 'Normal' },
  ATTENTION: { cls: 'risk-mid', icon: '!', label: 'Attention' },
  HIGH_CONCERN: { cls: 'risk-high', icon: '⚠', label: 'High concern' },
  EMERGENCY: { cls: 'risk-emergency', icon: '⛔', label: 'EMERGENCY' },
}

export function RiskBadge({ level, size = 'md' }) {
  const s = RISK_STYLES[level] || { cls: 'risk-unknown', icon: '?', label: (level || 'unknown').toUpperCase() }
  return (
    <span className={`risk-badge ${s.cls} risk-badge-${size}`}>
      <span aria-hidden="true">{s.icon}</span> {s.label}
    </span>
  )
}

export function CategoryBadge({ category }) {
  const s = CATEGORY_STYLES[category] || { cls: 'risk-unknown', icon: '?', label: category }
  return (
    <span className={`risk-badge ${s.cls}`}>
      <span aria-hidden="true">{s.icon}</span> {s.label}
    </span>
  )
}

export function StatCard({ label, value, sub, tone }) {
  return (
    <div className={`stat-card ${tone ? `stat-${tone}` : ''}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export function Loading({ label = 'Loading…' }) {
  return (
    <div className="state state-loading" role="status">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  const message = error?.message || String(error || 'Something went wrong.')
  const code = error?.code
  return (
    <div className="state state-error" role="alert">
      <strong>⚠ {code || 'Error'}</strong>
      <p>{message}</p>
      {onRetry && <button className="btn btn-secondary" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function EmptyState({ title, hint, action }) {
  return (
    <div className="state state-empty">
      <div className="empty-icon" aria-hidden="true">◎</div>
      <strong>{title}</strong>
      {hint && <p>{hint}</p>}
      {action}
    </div>
  )
}

export function Disclaimer({ text }) {
  return <p className="disclaimer">ℹ {text || 'This system provides AI-generated estimates for educational support. It is not a medical diagnosis and does not replace professional care.'}</p>
}
