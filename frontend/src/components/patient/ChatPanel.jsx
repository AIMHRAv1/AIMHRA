import { useCallback, useEffect, useRef, useState } from 'react'
import { chatService } from '../../services/auth'
import { apiError } from '../../api/client'
import { CategoryBadge, Disclaimer, EmptyState, ErrorState, Loading } from '../ui'

export default function ChatPanel({ patientId }) {
  const [sessions, setSessions] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [sessionLoading, setSessionLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showSources, setShowSources] = useState({})
  const bottomRef = useRef(null)
  const sendInFlight = useRef(false)

  const refreshSessions = useCallback(async () => {
    const d = await chatService.sessions(patientId)
    const list = d.sessions ?? []
    setSessions(list)
    return list
  }, [patientId])

  async function retrySessions() {
    setError(null)
    setSessionLoading(true)
    try {
      const list = await refreshSessions()
      if (list[0]) await openSession(list[0].id)
    } catch (e) {
      setError(apiError(e))
    } finally {
      setSessionLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    setError(null)
    setSessions([])
    setActiveId(null)
    setMessages([])
    setSessionLoading(true)
    refreshSessions()
      .then(async (list) => {
        if (cancelled || !list[0]) return
        setActiveId(list[0].id)
        const d = await chatService.session(list[0].id)
        if (!cancelled) setMessages(d.messages ?? [])
      })
      .catch((e) => {
        if (!cancelled) setError(apiError(e))
      })
      .finally(() => {
        if (!cancelled) setSessionLoading(false)
      })
    return () => { cancelled = true }
  }, [patientId, refreshSessions])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function newSession() {
    if (sessionLoading || busy) return
    setSessionLoading(true)
    setError(null)
    try {
      const d = await chatService.createSession(patientId, '')
      const session = d.session
      setSessions((s) => [session, ...s])
      setActiveId(session.id)
      setMessages([])
    } catch (e) {
      setError(apiError(e))
    } finally {
      setSessionLoading(false)
    }
  }

  async function openSession(id) {
    setSessionLoading(true)
    setActiveId(id)
    setError(null)
    try {
      const d = await chatService.session(id)
      setMessages(d.messages ?? [])
    } catch (e) {
      setError(apiError(e))
    } finally {
      setSessionLoading(false)
    }
  }

  async function removeSession(id) {
    if (!window.confirm('Delete this conversation?')) return
    try {
      await chatService.deleteSession(id)
      setSessions((s) => s.filter((x) => x.id !== id))
      if (activeId === id) {
        const next = sessions.find((x) => x.id !== id)
        if (next) openSession(next.id)
        else { setActiveId(null); setMessages([]) }
      }
    } catch (e) { setError(apiError(e)) }
  }

  async function send(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || busy || sessionLoading || sendInFlight.current) return
    sendInFlight.current = true
    setBusy(true)
    setError(null)
    try {
      let sessionId = activeId
      if (!sessionId) {
        const created = await chatService.createSession(patientId, '')
        const session = created.session
        sessionId = session.id
        setSessions((current) => [session, ...current])
        setActiveId(sessionId)
      }

      setInput('')
      setMessages((current) => [
        ...current,
        { role: 'USER', content: text, created_at: new Date().toISOString() },
      ])
      const d = await chatService.send(sessionId, text)
      setMessages((m) => [...m, d.reply])
      refreshSessions().catch((refreshError) => setError(apiError(refreshError)))
    } catch (err) {
      setError(apiError(err))
    } finally {
      sendInFlight.current = false
      setBusy(false)
    }
  }

  if (error && !activeId && sessions.length === 0) {
    return <ErrorState error={error} onRetry={retrySessions} />
  }

  return (
    <div className="chat-layout">
      <aside className="chat-sessions">
        <button className="btn btn-secondary btn-block" onClick={newSession} disabled={busy || sessionLoading} style={{ marginBottom: 8 }}>＋ New conversation</button>
        {sessions.length === 0 && <p className="muted small">No conversations for this patient yet.</p>}
        {sessions.map((s) => (
          <div key={s.id} className="chat-session-row">
            <button className={`chat-session${s.id === activeId ? ' active' : ''}`} onClick={() => openSession(s.id)} disabled={busy || sessionLoading}>
              {s.title || 'Conversation'}
            </button>
            <button className="link small" onClick={() => removeSession(s.id)} disabled={busy || sessionLoading} title="Delete conversation">✕</button>
          </div>
        ))}
      </aside>

      <div className="chat-main card">
        {messages.length === 0 ? (
          sessionLoading
            ? <Loading label="Loading conversation…" />
            : <>
                <EmptyState title="Ask AIMHRA about this patient" hint="Educational maternal-health information with trusted retrieval. Emergency warnings always take priority." />
                {busy && <div className="msg-mode muted small" role="status">Sending your message…</div>}
              </>
        ) : (
          <div className="chat-stream">
            {messages.map((m, i) => (
              <div key={i} className={`msg msg-${m.role.toLowerCase()}`}>
                {m.escalation?.escalate && (
                  <div className="msg-escalation"><CategoryBadge category={m.escalation.category} /> Rule-based escalation — seek care now</div>
                )}
                <div className="msg-content">{m.content}</div>
                {m.role === 'ASSISTANT' && m.knowledge_status === 'retrieved_guidelines' && (
                  <p className="msg-mode muted small">Guideline information was retrieved; citations are listed below.</p>
                )}
                {m.role === 'ASSISTANT' && m.knowledge_status === 'no_relevant_guidelines_retrieved' && m.generation_mode !== 'escalation' && (
                  <p className="msg-mode muted small">No relevant guideline was retrieved; this is general educational information.</p>
                )}
                {m.sources?.length > 0 && (
                  <div className="msg-sources">
                    <button className="link" onClick={() => setShowSources((s) => ({ ...s, [i]: !s[i] }))}>
                      📚 Knowledge-base sources ({m.sources.length}) {showSources[i] ? '▾' : '▸'}
                    </button>
                    {showSources[i] && (
                      <ul>
                        {m.sources.map((src, j) => (
                          <li key={j}>
                            <b>[{src.citation_id}] {src.document_title}</b>
                            {src.issuing_organization && <> · {src.issuing_organization}</>}
                            {src.section && <> · {src.section}</>}
                            {src.page_number != null && <> · p. {src.page_number}</>}
                            {src.source_url && <> · <a href={src.source_url} target="_blank" rel="noreferrer">source</a></>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                {m.role === 'ASSISTANT' && m.generation_mode && m.generation_mode !== 'escalation' && (
                  <div className="msg-mode muted small">mode: {m.generation_mode}</div>
                )}
              </div>
            ))}
            {busy && <div className="msg msg-assistant" role="status" aria-label="Assistant is responding"><span className="typing">•••</span></div>}
            <div ref={bottomRef} />
          </div>
        )}
        {error && <ErrorState error={error} />}
        <form className="chat-input" onSubmit={send}>
          <textarea
            rows={2}
            value={input}
            onChange={(e) => { setInput(e.target.value); setError(null) }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit() } }}
            placeholder="Type your question… (Enter to send)"
            maxLength={4000}
            disabled={busy || sessionLoading}
          />
          <button className="btn btn-primary" disabled={busy || sessionLoading || !input.trim()}>Send</button>
        </form>
      </div>
      <Disclaimer text="This assistant provides general educational information — not diagnosis or treatment. For emergencies, seek immediate medical care." />
    </div>
  )
}