import { useEffect, useState } from 'react'
import { kbService } from '../../services/auth'
import { apiError } from '../../api/client'
import { EmptyState, ErrorState, Loading } from '../../components/ui'

export default function AdminKnowledge() {
  const [docs, setDocs] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ title: '', source_url: '', content_text: '' })
  const [file, setFile] = useState(null)
  const [probe, setProbe] = useState('')

  async function reload() {
    const d = await kbService.documents()
    setDocs(d.results ?? d)
  }

  useEffect(() => { reload().catch(setError) }, [])

  async function upload(e) {
    e.preventDefault()
    setNotice(null)
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('title', form.title)
      if (form.source_url) fd.append('source_url', form.source_url)
      if (file) fd.append('file', file)
      else fd.append('content_text', form.content_text)
      const d = await kbService.upload(fd)
      setNotice(`Indexed “${d.title}” — ${d.chunk_count} chunks.`)
      setForm({ title: '', source_url: '', content_text: '' })
      setFile(null)
      await reload()
    } catch (err) { setNotice(apiError(err).message) } finally { setBusy(false) }
  }

  async function remove(id) {
    if (!window.confirm('Delete this document and its indexed chunks?')) return
    try { await kbService.deleteDocument(id); await reload() } catch (e) { setNotice(apiError(e).message) }
  }

  async function reindex() {
    setBusy(true)
    try {
      const d = await kbService.reindex()
      setNotice(`Re-indexed ${d.reindexed} documents.`)
    } catch (e) { setNotice(apiError(e).message) } finally { setBusy(false) }
  }

  async function runProbe(e) {
    e.preventDefault()
    setNotice(null)
    try {
      const d = await kbService.retrieve(probe)
      setNotice(d.retrieved
        ? `Top match: “${d.chunks[0].document_title}” (score ${d.chunks[0].score})`
        : 'No indexed content matched.')
    } catch (err) { setNotice(apiError(err).message) }
  }

  if (error) return <div className="page"><ErrorState error={error} /></div>
  if (!docs) return <div className="page"><Loading /></div>

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Knowledge base (RAG)</h1>
          <p className="muted">Trusted documents the assistant retrieves from. Every answer cites these sources.</p>
        </div>
        <button className="btn btn-secondary" disabled={busy} onClick={reindex}>↻ Re-index all</button>
      </header>

      {notice && <div className="alert alert-info">{notice}</div>}

      <form className="card" onSubmit={upload}>
        <h2 className="section-title">Add document</h2>
        <div className="grid-2">
          <label className="field"><span>Title</span>
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required /></label>
          <label className="field"><span>Source URL (optional provenance)</span>
            <input type="url" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} /></label>
        </div>
        <label className="field"><span>Upload PDF / TXT / MD</span>
          <input type="file" accept=".pdf,.txt,.md" onChange={(e) => setFile(e.target.files[0])} /></label>
        <label className="field"><span>…or paste text content</span>
          <textarea rows={4} value={form.content_text} onChange={(e) => setForm({ ...form, content_text: e.target.value })}
                    placeholder="Paste document text if no file is available" /></label>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Indexing…' : 'Upload & index'}</button>
        </div>
      </form>

      <div className="card">
        <h2 className="section-title">Retrieval probe</h2>
        <form className="assign-form" onSubmit={runProbe}>
          <input className="search" value={probe} onChange={(e) => setProbe(e.target.value)} placeholder="Test a retrieval query…" required />
          <button className="btn btn-secondary">Search</button>
        </form>
      </div>

      <div className="card">
        <h2 className="section-title">Documents</h2>
        {docs.length === 0 ? (
          <EmptyState title="No documents" hint="Upload clinical guidelines or education material to ground the assistant's answers." />
        ) : (
          <table className="data-table">
            <thead><tr><th>Title</th><th>Source</th><th>Chunks</th><th>Indexed</th><th></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td>
                  <td>{d.source_url ? <a href={d.source_url} target="_blank" rel="noreferrer">link</a> : <span className="muted">—</span>}</td>
                  <td>{d.chunk_count}</td>
                  <td>{d.indexed_at ? new Date(d.indexed_at).toLocaleString() : 'not indexed'}</td>
                  <td><button className="btn btn-small btn-danger" onClick={() => remove(d.id)}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
