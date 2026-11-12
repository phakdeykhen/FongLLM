import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { MediaCard } from './Media.jsx'
import { deleteDocument, listDocuments, listMedia, uploadDocuments } from '../api.js'

export function SearchPage({ chats, onOpen }) {
  const [q, setQ] = useState('')
  const needle = q.trim().toLowerCase()
  const found = chats.filter((c) => c.messages.length && (!needle || c.title.toLowerCase().includes(needle) ||
    c.messages.some((m) => m.content.toLowerCase().includes(needle)))).sort((a, b) => b.updated - a.updated)
  return (
    <div className="page">
      <h1 className="page-title">Search</h1>
      <div className="search-box"><Icon name="search" /><input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your chats…" /></div>
      <div className="list">
        {found.map((c) => (
          <button key={c.id} className="list-row" onClick={() => onOpen(c.id)}>
            <span>{c.title}</span><small>{c.messages.length / 2 | 0} messages · {new Date(c.updated).toLocaleDateString()}</small>
          </button>
        ))}
        {!found.length && <p className="muted">{needle ? 'No chats match.' : 'No chats yet. Start one from Home.'}</p>}
      </div>
    </div>
  )
}

export function MediaPage({ kind, onOpen }) {
  const [items, setItems] = useState(null)
  useEffect(() => { listMedia(kind).then(setItems).catch(() => setItems([])) }, [kind])
  return (
    <div className="page wide">
      <h1 className="page-title">{kind === 'image' ? 'Images' : 'Videos'}</h1>
      <p className="muted">
        {items ? `${items.length} ${kind}${items.length === 1 ? '' : 's'}` : 'Loading…'} · create more in a chat with <code>/{kind} your prompt</code>
      </p>
      <div className="mgrid wide">
        {items?.map((it) => <MediaCard key={it.url} item={it} onOpen={onOpen} large />)}
      </div>
    </div>
  )
}

export function DocumentsPage({ docs, setDocs, settings, setSettings }) {
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
        <Icon name="file" size={22} /> {busy ? 'Indexing…' : 'Add .txt or .md files'}
      </button>
      <input ref={file} type="file" multiple hidden accept=".txt,.md" onChange={(e) => { add(e.target.files); e.target.value = '' }} />
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

export function SettingsPage({ settings, setSettings, info, onClearChats }) {
  return (
    <div className="page">
      <h1 className="page-title">Settings</h1>
      {info && !info.ollama && (
        <p className="msg-error">Ollama isn't running or <code>{info.ollama_model}</code> isn't pulled. Run <code>brew services start ollama && ollama pull {info.ollama_model}</code></p>
      )}
      <label className="field check">
        <input type="checkbox" checked={settings.use_tools} onChange={(e) => setSettings({ use_tools: e.target.checked })} />
        <span>Let the model create images and videos when you ask for them</span>
      </label>
      <label className="field">
        <span>Temperature <b>{settings.temperature.toFixed(2)}</b></span>
        <input type="range" min="0" max="1.5" step="0.05" value={settings.temperature} onChange={(e) => setSettings({ temperature: +e.target.value })} />
      </label>
      <label className="field">
        <span>Max answer tokens <b>{settings.max_new}</b></span>
        <input type="range" min="64" max="2048" step="64" value={settings.max_new} onChange={(e) => setSettings({ max_new: +e.target.value })} />
      </label>
      <p className="muted">Commands: <code>/image prompt</code> (about 5 s) · <code>/video prompt</code> (minutes). Khmer is translated automatically. Device: {info?.device || '…'}</p>
      <button className="danger" onClick={onClearChats}><Icon name="trash" size={16} /> Delete all chats</button>
    </div>
  )
}
