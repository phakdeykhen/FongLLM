import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { deleteDocument, listDocuments, uploadDocuments } from '@/api/client.js'

export default function DocumentsPage({ docs, setDocs, settings, setSettings }) {
  const file = useRef(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { listDocuments().then(setDocs).catch(() => {}) }, [setDocs])
  async function add(files) {
    setErr(''); setBusy(true)
    try { setDocs(await uploadDocuments(files)) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <div className="page">
      <h1 className="page-title">Documents</h1>
      <p className="muted">Answers use these files as context. You can also drop files on the message box.</p>
      <button className="drop" onClick={() => file.current.click()}
        onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); add(e.dataTransfer.files) }}>
        <Icon name="file" size={22} /> {busy ? 'Indexing…' : 'Add Word, Excel, PowerPoint, PDF or text files'}
      </button>
      <input ref={file} type="file" multiple hidden accept=".txt,.md,.csv,.json,.html,.docx,.xlsx,.xlsm,.pptx,.pdf" onChange={(e) => { add(e.target.files); e.target.value = '' }} />
      {err && <p className="msg-error">{err}</p>}
      <div className="list">
        {docs.documents.map((d) => (
          <div key={d.name} className="list-row static">
            <span><Icon name="doc" size={16} /> {d.name}</span>
            <small>{d.chars.toLocaleString()} characters</small>
            <button className="icon-btn" title="Remove" aria-label={`Remove ${d.name}`} onClick={async () => setDocs(await deleteDocument(d.name))}>
              <Icon name="trash" size={16} />
            </button>
          </div>
        ))}
      </div>
      <p className="muted">{docs.passages ? `${docs.passages} passages indexed` : 'No documents: plain chat mode'}</p>
      <label className="field">
        <span>Passages to use per question <b>{settings.top_k}</b></span>
        <input type="range" min="1" max="8" value={settings.top_k} onChange={(e) => setSettings({ top_k: +e.target.value })} />
      </label>
    </div>
  )
}
