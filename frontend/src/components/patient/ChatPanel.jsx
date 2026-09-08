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
  const [error, setError] = useState(null)
  const [showSources, setShowSources] = useState({})
  const bottomRef = useRef(null)

  const refreshSessions = useCallback(async () => {
    const d = await chatService.sessions(patientId)
    const list = d.sessions ?? []
    setSessions(list)
    return list
  }, [patientId])

  useEffect(() => {
    setError(null)
    setSessions([])
    setActiveId(null)
    setMessages([])
    refreshSessions()
      .then((list) => {
        if (list[0]) openSession(list[0].id)
      })
      .catch(setError)
  }, [patientId, refreshSessions])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function newSession() {
    try {
      const d = await chatService.createSession(patientId, '')
      const session = d.session
      setSessions((s) => [session, ...s])
      setActiveId(session.id)
      setMessages([])
    } catch (e) { setError(apiError(e)) }
  }

  async function openSession(id) {
    setActiveId(id)
    setError(null)
    try {
      const d = await chatService.session(id)
      setMessages(d.messages ?? [])
    } catch (e) { setError(apiError(e)) }
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
    if (!text || busy || !activeId) return
    setInput('')
    setBusy(true)
    setMessages((m) => [...m, { role: 'USER', content: text, created_at: new Date().toISOString() }])
    try {
      const d = await chatService.send(activeId, text)
      setMessages((m) => [...m, d.reply])
      refreshSessions().catch(() => {})
    } catch (err) {
      const e2 = apiError(err)
      setMessages((m) => [...m, { role: 'ASSISTANT', content: `Sorry — ${e2.message}`, sources: [], generation_mode: 'error' }])
    } finally {
      setBusy(false)
    }
  }

  if (error && !activeId && sessions.length === 0) return <ErrorState error={error} />

  return (
    <div className="chat-layout">
      <aside className="chat-sessions">
        <button className="btn btn-secondary btn-block" onClick={newSession} style={{ marginBottom: 8 }}>＋ New conversation</button>
        {sessions.length === 0 && <p className="muted small">No conversations for this patient yet.</p>}
        {sessions.map((s) => (
          <div key={s.id} className="chat-session-row">
            <button className={`chat-session${s.id === activeId ? ' active' : ''}`} onClick={() => openSession(s.id)}>
              {s.title || 'Conversation'}
            </button>
            <button className="link small" onClick={() => removeSession(s.id)} title="Delete conversation">✕</button>
          </div>
        ))}
      </aside>

      <div className="chat-main card">
        {messages.length === 0 ? (
          <EmptyState title="Ask AIMHRA about this patient" hint="Educational maternal-health information with trusted retrieval. Emergency warnings always take priority." />
        ) : (
          <div className="chat-stream">
            {messages.map((m, i) => (
              <div key={i} className={`msg msg-${m.role.toLowerCase()}`}>
                {m.escalation?.escalate && (
                  <div className="msg-escalation"><CategoryBadge category={m.escalation.category} /> Rule-based escalation — seek care now</div>
                )}
                <div className="msg-content">{m.content}</div>
                {m.sources?.length > 0 && (
                  <div className="msg-sources">
                    <button className="link" onClick={() => setShowSources((s) => ({ ...s, [i]: !s[i] }))}>
                      📚 Knowledge-base sources ({m.sources.length}) {showSources[i] ? '▾' : '▸'}
                    </button>
                    {showSources[i] && (
                      <ul>
                        {m.sources.map((src, j) => (
                          <li key={j}>
                            <b>{src.document_title}</b> · chunk {src.chunk_index} · score {src.score}
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
            {busy && <div className="msg msg-assistant"><span className="typing">•••</span></div>}
            <div ref={bottomRef} />
          </div>
        )}
        <form className="chat-input" onSubmit={send}>
          <textarea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e) } }}
            placeholder="Type your question… (Enter to send)"
            maxLength={4000}
          />
          <button className="btn btn-primary" disabled={busy || !input.trim() || !activeId}>Send</button>
        </form>
      </div>
      <Disclaimer text="This assistant provides general educational information — not diagnosis or treatment. For emergencies, seek immediate medical care." />
    </div>
  )
}