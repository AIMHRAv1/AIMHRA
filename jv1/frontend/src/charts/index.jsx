/** Recharts-based visualizations shared across dashboards. */
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
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
        <YAxis domain={[-0.2, 2.2]} ticks={[0, 1, 2]} tickFormatter={(v) => ({ 0: 'Low', 1: 'Mid', 2: 'High' }[v] ?? '')} tick={{ fontSize: 12 }} />
        <Tooltip
          formatter={(value, _name, entry) => [entry?.payload?.label, 'Risk category']}
          labelFormatter={(_l, entries) => entries?.[0]?.payload?.date ?? _l}
        />
        <Line type="stepAfter" dataKey="level" stroke="#1f6f8b" strokeWidth={2.5} dot={{ r: 4 }} isAnimationActive={false} />
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
