import { useEffect, useState } from 'react'
import { modelService } from '../../services/auth'
import { apiError } from '../../api/client'
import { ConfusionMatrix, FeatureImportanceChart, MetricBars } from '../../charts'
import { ErrorState, Loading, StatCard } from '../../components/ui'

export default function AdminModels() {
  const [compare, setCompare] = useState(null)
  const [versions, setVersions] = useState(null)
  const [importance, setImportance] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busyId, setBusyId] = useState(null)

  function reload() {
    return Promise.all([modelService.compare(), modelService.list(), modelService.featureImportance().catch(() => null)])
      .then(([c, v, f]) => { setCompare(c); setVersions(v.results ?? v); setImportance(f) })
  }

  useEffect(() => { reload().catch(setError) }, [])

  async function activate(id) {
    setBusyId(id)
    setNotice(null)
    try {
      await modelService.activate(id)
      setNotice('Model activated as production.')
      await reload()
    } catch (e) { setNotice(apiError(e).message) } finally { setBusyId(null) }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!compare || !versions) return <div className="page"><Loading /></div>

  const production = compare.production

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Model management</h1>
          <p className="muted">Random Forest vs XGBoost, evaluated on the held-out test split.</p>
        </div>
      </header>

      {notice && <div className="alert alert-info">{notice}</div>}

      <div className="stat-grid">
        <StatCard label="Production model" value={production ? production.model : 'None'} sub={production ? production.version : 'Train a model first'} tone={production ? 'good' : 'danger'} />
        <StatCard label="Selection criterion" value={compare.criterion} sub="high-risk recall prioritized; accuracy is never the sole basis" />
        <StatCard label="Registered versions" value={versions.length} />
      </div>

      <div className="card">
        <h2 className="section-title">Test-split comparison</h2>
        <MetricBars models={compare.models} />
        <table className="data-table">
          <thead><tr><th>Model</th><th>Version</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>ROC-AUC</th><th>High-risk recall</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {compare.models.map((m) => (
              <tr key={m.id} className={m.status === 'PRODUCTION' ? 'row-good' : ''}>
                <td>{m.model}</td><td>{m.version}</td>
                <td>{(m.accuracy * 100).toFixed(1)}%</td>
                <td>{m.precision != null ? (m.precision * 100).toFixed(1) + '%' : '—'}</td>
                <td>{m.recall != null ? (m.recall * 100).toFixed(1) + '%' : '—'}</td>
                <td>{(m.f1 * 100).toFixed(1)}%</td>
                <td>{m.roc_auc != null ? (m.roc_auc * 100).toFixed(1) + '%' : '—'}</td>
                <td><b>{(m.high_risk_recall * 100).toFixed(1)}%</b></td>
                <td>{m.status}</td>
                <td>
                  {m.status !== 'PRODUCTION' && (
                    <button className="btn btn-small" disabled={busyId === m.id} onClick={() => activate(m.id)}>
                      {busyId === m.id ? '…' : 'Activate'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">High-risk recall is the primary criterion: missing a genuinely high-risk pregnancy is the costliest error.</p>
      </div>

      <div className="grid-2-cards">
        {compare.models.filter((m) => m.confusion_matrix).map((m) => (
          <div className="card" key={m.id}>
            <h2 className="section-title">Confusion matrix — {m.model} (test)</h2>
            <ConfusionMatrix matrix={m.confusion_matrix} />
          </div>
        ))}
        {importance && (
          <div className="card">
            <h2 className="section-title">Global feature importance — production</h2>
            <FeatureImportanceChart importance={importance.importance} />
            <p className="muted small">{importance.model?.name} {importance.model?.version}</p>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="section-title">Version history</h2>
        <table className="data-table">
          <thead><tr><th>Name</th><th>Version</th><th>Trained</th><th>Dataset md5</th><th>Status</th></tr></thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id}>
                <td>{v.name}</td><td>{v.version}</td>
                <td>{new Date(v.trained_at).toLocaleString()}</td>
                <td><code className="small">{v.dataset_version?.slice(0, 12)}…</code></td>
                <td>{v.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
