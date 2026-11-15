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
          <p className="muted">Decision Tree, Random Forest and XGBoost are compared on validation data. The test set is reported only for the selected production model.</p>
        </div>
      </header>

      {notice && <div className="alert alert-info">{notice}</div>}

      <div className="stat-grid">
        <StatCard label="Production model" value={production ? production.model : 'None'} sub={production ? production.version : 'Train a model first'} tone={production ? 'good' : 'danger'} />
        <StatCard label="Selection criterion" value={compare.criterion} sub="high-risk recall prioritized; accuracy is never the sole basis" />
        <StatCard label="Registered versions" value={versions.length} />
      </div>

      <div className="card">
        <h2 className="section-title">Validation-split comparison</h2>
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
        <p className="muted small">Validation results select the model; high-risk recall is prioritized. The test set is not used for model selection.</p>
      </div>

      <div className="grid-2-cards">
        {compare.models.filter((m) => m.confusion_matrix).map((m) => (
          <div className="card" key={m.id}>
            <h2 className="section-title">Confusion matrix — {m.model} (validation)</h2>
            <ConfusionMatrix matrix={m.confusion_matrix} />
          </div>
        ))}
        {production && compare.models.find((m) => m.id === production.id)?.test_metrics && (
          <div className="card">
            <h2 className="section-title">Final test results — {production.model}</h2>
            {(() => {
              const metrics = compare.models.find((m) => m.id === production.id).test_metrics
              return (
                <>
                  <p>
                    Accuracy {(metrics.accuracy * 100).toFixed(1)}% ·
                    Precision {(metrics.precision_macro * 100).toFixed(1)}% ·
                    Recall {(metrics.recall_macro * 100).toFixed(1)}% ·
                    F1 {(metrics.f1_macro * 100).toFixed(1)}% ·
                    High-risk recall {(metrics.high_risk_recall * 100).toFixed(1)}% ·
                    ROC-AUC {metrics.roc_auc_ovr_macro != null ? (metrics.roc_auc_ovr_macro * 100).toFixed(1) + '%' : '—'}
                  </p>
                  {metrics.confusion_matrix && <ConfusionMatrix matrix={metrics.confusion_matrix} />}
                  {metrics.per_class && (
                    <table className="data-table">
                      <thead><tr><th>Class</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead>
                      <tbody>
                        {Object.entries(metrics.per_class).map(([label, row]) => (
                          <tr key={label}>
                            <td>{label}</td>
                            <td>{(row.precision * 100).toFixed(1)}%</td>
                            <td>{(row.recall * 100).toFixed(1)}%</td>
                            <td>{(row.f1 * 100).toFixed(1)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  <p className="muted small">Final held-out test metrics are reported for the selected model only.</p>
                </>
              )
            })()}
          </div>
        )}
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
