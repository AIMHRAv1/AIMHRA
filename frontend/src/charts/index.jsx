/** Recharts-based visualizations shared across dashboards. */
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

export const RISK_COLORS = { 'low risk': '#2e7d5b', 'mid risk': '#d99518', 'high risk': '#c0392b' }
const RISK_VALUE = { 'low risk': 0, 'mid risk': 1, 'high risk': 2 }

/** Risk-category progression across stored visits. */
export function RiskTrendChart({ series }) {
  const data = (series || []).map((s, i) => ({
    name: s.gestational_week != null ? `Wk ${s.gestational_week}` : `Visit ${i + 1}`,
    date: s.visit_date,
    level: RISK_VALUE[s.risk_level] ?? 0,
    label: s.risk_level,
  }))
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e3e8ec" />
        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
        <YAxis domain={[-0.5, 2.5]} ticks={[0, 1, 2]} tickFormatter={(v) => ({ 0: 'Low', 1: 'Mid', 2: 'High' }[v] ?? '')} tick={{ fontSize: 12 }} />
        <ReferenceArea y1={-0.5} y2={0.5} fill={RISK_COLORS['low risk']} fillOpacity={0.08} />
        <ReferenceArea y1={0.5} y2={1.5} fill={RISK_COLORS['mid risk']} fillOpacity={0.08} />
        <ReferenceArea y1={1.5} y2={2.5} fill={RISK_COLORS['high risk']} fillOpacity={0.08} />
        <ReferenceLine y={0} stroke={RISK_COLORS['low risk']} strokeDasharray="4 4" strokeOpacity={0.45} />
        <ReferenceLine y={1} stroke={RISK_COLORS['mid risk']} strokeDasharray="4 4" strokeOpacity={0.45} />
        <ReferenceLine y={2} stroke={RISK_COLORS['high risk']} strokeDasharray="4 4" strokeOpacity={0.45} />
        <Tooltip
          formatter={(value, _name, entry) => [entry?.payload?.label, 'Risk category']}
          labelFormatter={(_l, entries) => entries?.[0]?.payload?.date ?? _l}
        />
        <Line type="monotone" dataKey="level" stroke="#1f6f8b" strokeWidth={2.5} dot={{ r: 5, fill: '#1f6f8b', stroke: '#fff', strokeWidth: 2 }} activeDot={{ r: 7 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

/** A single clinical measurement over the patient's stored assessment visits. */
export function MeasurementTrendChart({ visits, feature, label, unit }) {
  const data = (visits || []).map((visit) => ({
    date: visit.visit_date,
    value: visit[feature],
  }))
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e3e8ec" />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} />
        <YAxis width={48} tick={{ fontSize: 10 }} />
        <Tooltip formatter={(value) => [`${value} ${unit}`, label]} />
        <Line
          type="monotone"
          dataKey="value"
          name={label}
          stroke="#1f6f8b"
          strokeWidth={2}
          dot={{ r: 3 }}
          connectNulls
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

/** Low/Mid/High distribution (counts). */
export function RiskDistributionChart({ counts }) {
  const data = Object.entries(counts || {}).map(([name, value]) => ({ name, value }))
  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={2}>
          {data.map((d) => <Cell key={d.name} fill={RISK_COLORS[d.name] || '#888'} />)}
        </Pie>
        <Tooltip />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  )
}

/** SHAP-style horizontal bars: positive = increasing risk contribution. */
export function ShapBars({ features }) {
  const data = (features || []).map((f) => ({ name: f.label || f.feature, impact: f.impact }))
  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 36)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e3e8ec" />
        <XAxis type="number" tick={{ fontSize: 11 }} />
        <YAxis type="category" dataKey="name" width={190} tick={{ fontSize: 11 }} />
        <Tooltip formatter={(v) => [v.toFixed(3), 'Impact on prediction']} />
        <ReferenceLine x={0} stroke="#8b98a5" />
        <Bar dataKey="impact" isAnimationActive={false}>
          {data.map((d, i) => <Cell key={i} fill={d.impact >= 0 ? '#c0392b' : '#2e7d5b'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Global feature importance (production model). */
export function FeatureImportanceChart({ importance }) {
  const data = (importance || []).map((f) => ({ name: f.feature, value: f.importance }))
  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 36)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e3e8ec" />
        <XAxis type="number" tick={{ fontSize: 11 }} />
        <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 11 }} />
        <Tooltip />
        <Bar dataKey="value" fill="#1f6f8b" isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Confusion matrix heat table. */
export function ConfusionMatrix({ matrix }) {
  if (!matrix?.matrix) return null
  const { labels, matrix: m } = matrix
  const max = Math.max(...m.flat())
  const short = (l) => l.replace(' risk', '').toUpperCase()
  return (
    <table className="confusion-matrix">
      <thead>
        <tr>
          <th>Actual ↓ / Predicted →</th>
          {labels.map((l) => <th key={l}>{short(l)}</th>)}
        </tr>
      </thead>
      <tbody>
        {m.map((row, i) => (
          <tr key={labels[i]}>
            <th>{short(labels[i])}</th>
            {row.map((v, j) => (
              <td key={j} style={{ background: `rgba(31, 111, 139, ${max ? v / max * 0.75 : 0})` }}>{v}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Metric comparison bars for RF vs XGB. */
export function MetricBars({ models }) {
  const metrics = ['accuracy', 'precision', 'recall', 'f1', 'roc_auc', 'high_risk_recall']
  const labels = { accuracy: 'Accuracy', precision: 'Precision', recall: 'Recall', f1: 'F1', roc_auc: 'ROC-AUC', high_risk_recall: 'High-risk recall' }
  const data = metrics.map((m) => {
    const row = { metric: labels[m] }
    models.forEach((mod) => { row[mod.model] = mod[m] ?? 0 })
    return row
  })
  const colors = { RandomForest: '#5b8c5a', XGBoost: '#1f6f8b' }
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e3e8ec" />
        <XAxis dataKey="metric" tick={{ fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={60} />
        <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
        <Tooltip />
        <Legend />
        {models.map((mod) => (
          <Bar key={mod.model} dataKey={mod.model} fill={colors[mod.model] || '#888'} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
