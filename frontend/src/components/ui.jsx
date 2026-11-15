/** Shared UI primitives: risk badge, states, stat cards.
 * Risk levels always pair color with a text label + icon (never color-only). */
import {
  IconAlertTriangle, IconCheck, IconInfo, IconOctagonAlert,
} from './icons'

const RISK_STYLES = {
  'low risk': { cls: 'risk-low', Icon: IconCheck, label: 'LOW RISK' },
  'mid risk': { cls: 'risk-mid', Icon: IconAlertTriangle, label: 'MID RISK' },
  'high risk': { cls: 'risk-high', Icon: IconAlertTriangle, label: 'HIGH RISK' },
}

const CATEGORY_STYLES = {
  NORMAL: { cls: 'risk-low', Icon: IconCheck, label: 'Normal' },
  ATTENTION: { cls: 'risk-mid', Icon: IconAlertTriangle, label: 'Attention' },
  HIGH_CONCERN: { cls: 'risk-high', Icon: IconAlertTriangle, label: 'High concern' },
  EMERGENCY: { cls: 'risk-emergency', Icon: IconOctagonAlert, label: 'EMERGENCY' },
}

export function RiskBadge({ level, size = 'md' }) {
  const s = RISK_STYLES[level] || { cls: 'risk-unknown', Icon: IconAlertTriangle, label: (level || 'unknown').toUpperCase() }
  return (
    <span className={`risk-badge ${s.cls} risk-badge-${size}`}>
      <s.Icon size={12} /> {s.label}
    </span>
  )
}

export function CategoryBadge({ category }) {
  const s = CATEGORY_STYLES[category] || { cls: 'risk-unknown', Icon: IconAlertTriangle, label: category }
  return (
    <span className={`risk-badge ${s.cls}`}>
      <s.Icon size={12} /> {s.label}
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
      <strong><IconAlertTriangle size={13} /> {code || 'Error'}</strong>
      <p>{message}</p>
      {onRetry && <button className="btn btn-secondary" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function EmptyState({ title, hint, action }) {
  return (
    <div className="state state-empty">
      <div className="empty-icon" aria-hidden="true">
        <IconInfo size={20} />
      </div>
      <strong>{title}</strong>
      {hint && <p>{hint}</p>}
      {action}
    </div>
  )
}

export function Disclaimer({ text }) {
  return (
    <p className="disclaimer">
      <IconInfo size={12} /> {text || 'This system provides AI-generated estimates for educational support. It is not a medical diagnosis and does not replace professional care.'}
    </p>
  )
}

/** Minimal markdown rendering for AI answers: **bold**, headings written as
 * **bold** lines, "* " bullets and numbered steps. No HTML is ever injected —
 * text is rendered as plain React nodes. */
export function MarkdownLite({ text }) {
  const lines = String(text || '').split('\n')
  const inline = (s, keyPrefix) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith('**') && part.endsWith('**')
        ? <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>
        : part,
    )
  return (
    <div className="md-lite">
      {lines.map((raw, i) => {
        const line = raw.trimEnd()
        const bullet = line.match(/^\s*[*•]\s+(.*)$/)
        const numbered = line.match(/^\s*(\d+)[.)]\s+(.*)$/)
        if (bullet) return <p key={i} className="md-li">• {inline(bullet[1], `b${i}`)}</p>
        if (numbered) return <p key={i} className="md-li">{numbered[1]}. {inline(numbered[2], `n${i}`)}</p>
        if (!line.trim()) return <p key={i} className="md-spacer" />
        return <p key={i}>{inline(line, `l${i}`)}</p>
      })}
    </div>
  )
}
