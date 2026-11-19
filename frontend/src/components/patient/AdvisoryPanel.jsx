import { useCallback, useEffect, useRef, useState } from 'react'
import { advisoryService, assessmentService } from '../../services/auth'
import { apiError } from '../../api/client'
import { CategoryBadge, Disclaimer, EmptyState, ErrorState, Loading, MarkdownLite, RiskBadge } from '../ui'

/**
 * Care advisory for one assessment — same pipeline as the chatbot
 * (rules -> knowledge-base retrieval -> offline generation), rendered in the
 * chatbot's visual language.
 */
export function AdvisoryCard({ assessmentId, category, autoGenerate = false }) {
  const [advisory, setAdvisory] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [showSources, setShowSources] = useState(false)
  const autoTriedRef = useRef(false)

  const load = useCallback(async () => {
    if (!assessmentId) return
    setLoading(true)
    setError(null)
    try {
      const d = await advisoryService.forAssessment(assessmentId)
      setAdvisory(d.advisory ?? null)
    } catch (e) {
      setError(apiError(e))
    } finally {
      setLoading(false)
    }
  }, [assessmentId])

  useEffect(() => {
    setAdvisory(null)
    autoTriedRef.current = false
    load()
  }, [load])

  // When enabled (e.g. right after a new assessment), generate the advice
  // automatically the first time no stored advisory is found.
  useEffect(() => {
    if (!autoGenerate || loading || busy || autoTriedRef.current) return
    if (!advisory) {
      autoTriedRef.current = true
      generate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoGenerate, loading, advisory])

  async function generate() {
    setBusy(true)
    setError(null)
    try {
      const d = await advisoryService.generate(assessmentId)
      setAdvisory(d.advisory)
    } catch (e) {
      setError(apiError(e))
    } finally {
      setBusy(false)
    }
  }

  if (!assessmentId) {
    return (
      <div className="card">
        <h2 className="section-title">Care Advisory</h2>
        <EmptyState title="No assessment selected" hint="Care advice is generated for a completed assessment." />
      </div>
    )
  }
  if (loading) return <div className="card"><Loading label="Checking for saved advice…" /></div>

  const escalated = advisory?.generation_mode === 'escalation'

  return (
    <div className="card">
      <h2 className="section-title">Care Advisory</h2>
      {error && <ErrorState error={error} onRetry={load} />}
      {advisory ? (
        <div className="stack">
          <div className="stack">
            <p className="muted small">
              <b>Model estimate:</b> <RiskBadge level={advisory.risk_level} />
              {' '}<b>Independent rule check:</b> <CategoryBadge category={advisory.rules_category || category || 'NORMAL'} />
              {' '}<b>Combined advisory level:</b> <CategoryBadge category={advisory.advisory_category || advisory.rules_category || 'NORMAL'} />
            </p>
            <p className="muted small">
              The model estimate and rule check are separate results. A rule-check finding does not change the model's classification.
              {' '}Generated {new Date(advisory.created_at).toLocaleString()}.
            </p>
            {advisory.rule_findings?.length > 0 && (
              <ul className="rule-list">
                {advisory.rule_findings.map((finding) => (
                  <li key={finding.id}><code>{finding.id}</code> {finding.description}</li>
                ))}
              </ul>
            )}
          </div>
          <div className={`msg msg-assistant${escalated ? ' msg-escalated' : ''}`}>
            {escalated && <div className="msg-escalation"><strong>Emergency warning</strong> — advice follows the warning below</div>}
            <div className="msg-content advisory-content"><MarkdownLite text={advisory.content} /></div>
            {advisory.sources?.length > 0 && (
              <div className="msg-sources">
                <button type="button" className="link" onClick={() => setShowSources((s) => !s)}>
                  Knowledge-base sources ({advisory.sources.length})
                </button>
                {showSources && (
                  <ul>
                    {advisory.sources.map((s, i) => (
                      <li key={i}>
                        {s.document_title} — chunk {s.chunk_index} · score {typeof s.score === 'number' ? s.score.toFixed(3) : s.score}
                        {s.topics?.length > 0 && <div className="muted small">supports: {s.topics.join('; ')}</div>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
          <Disclaimer text={advisory.disclaimer} />
          <div className="form-actions">
            <button className="btn btn-small btn-secondary" disabled={busy} onClick={generate}>
              {busy ? 'Regenerating…' : 'Regenerate advice'}
            </button>
          </div>
        </div>
      ) : (
        <div className="stack">
          {(busy || (autoGenerate && loading)) && <Loading label="Generating detailed care advice…" />}
          {!busy && !autoGenerate && (
            <EmptyState
              title="No advice generated yet"
              hint="Generate detailed guidance on what to do for this assessment's risk level, warning signs and follow-up."
              action={
                <button className="btn btn-primary" disabled={busy} onClick={generate}>
                  Generate care advice
                </button>
              }
            />
          )}
          <Disclaimer text="Advice is generated offline from the trusted knowledge base and never replaces professional medical assessment." />
        </div>
      )}
    </div>
  )
}

/**
 * Full advisory tab: pick an assessment, see (or generate) its care advice.
 */
export default function AdvisoryPanel({ patientId }) {
  const [assessments, setAssessments] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setError(null)
    setAssessments(null)
    return assessmentService.list({ patient: patientId })
      .then((d) => {
        const list = d.results ?? []
        setAssessments(list)
        setSelectedId((prev) => prev ?? list[0]?.id ?? null)
      })
      .catch((e) => setError(apiError(e)))
  }, [patientId])

  useEffect(() => { load() }, [load])

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!assessments) return <Loading />

  if (assessments.length === 0) {
    return (
      <EmptyState
        title="No assessments yet"
        hint="Complete a risk assessment first — care advice is generated from its results."
      />
    )
  }

  const selected = assessments.find((a) => a.id === selectedId)
  const isLatest = assessments.length > 0 && assessments[0].id === selectedId

  return (
    <div className="stack">
      <div className="chip-row" role="tablist" aria-label="Select assessment">
        {assessments.map((a) => (
          <button
            key={a.id}
            className={`chip${a.id === selectedId ? ' selected' : ''}`}
            onClick={() => setSelectedId(a.id)}
          >
            {a.visit_date}{a.prediction ? ` · ${a.prediction.risk_level}` : ''}
          </button>
        ))}
      </div>
      <AdvisoryCard
        assessmentId={selectedId}
        category={selected?.prediction?.risk_level}
        autoGenerate={isLatest}
      />
    </div>
  )
}
