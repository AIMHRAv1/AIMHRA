const GROUPS = [
  ['routine_monitoring', 'Routine monitoring'],
  ['further_assessment', 'Further assessment'],
  ['medical_consultation', 'Medical consultation'],
  ['urgent_medical_attention', 'Urgent medical attention'],
]

export default function RecommendationsPanel({ recommendations }) {
  const grouped = recommendations || {}
  const items = GROUPS.flatMap(([key, label]) =>
    (grouped[key] || []).map((recommendation) => ({ ...recommendation, groupLabel: label })),
  )

  return (
    <div className="card">
      <h2 className="section-title">Rule-based recommendations</h2>
      {items.length === 0 ? (
        <p className="muted">No rule-based recommendations were generated for this assessment.</p>
      ) : (
        <div className="stack">
          {items.map((recommendation) => (
            <section key={`${recommendation.groupLabel}-${recommendation.triggering_rule_ids?.join('-')}`}>
              <h3>{recommendation.groupLabel}: {recommendation.title}</h3>
              <p>{recommendation.explanation}</p>
              <p><b>Priority:</b> {recommendation.priority}</p>
              <p><b>Triggered by:</b> {(recommendation.triggering_rule_ids || [recommendation.triggering_rule_id]).join(', ')}</p>
              <p><b>Suggested next action:</b> {recommendation.suggested_next_action}</p>
              <p className="muted small">
                <b>Supporting source:</b> {recommendation.supporting_source || 'No verified clinical source documented in the project.'}
              </p>
            </section>
          ))}
        </div>
      )}
      <p className="muted small">These rule-based prompts are not diagnoses or treatment instructions. Seek professional assessment as indicated.</p>
    </div>
  )
}
