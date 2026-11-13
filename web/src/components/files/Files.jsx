import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { GOOGLE_APP, saveToGoogle } from '@/lib/google.js'

// A file FongAI made (PDF, Word, Excel, PowerPoint, React, HTML): a card in the chat and a preview panel on the right.
const KIND_ICON = { pdf: 'doc', docx: 'doc', xlsx: 'sheet', pptx: 'slides', react: 'fileCode', html: 'fileCode' }
const EXT = { pdf: 'PDF', docx: 'DOCX', xlsx: 'XLSX', pptx: 'PPTX', react: 'JSX', html: 'HTML' }

function size(bytes) {
  if (!bytes) return ''
  return bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1048576).toFixed(1)} MB`
}

// Google files made from FongAI's files, remembered so a second click opens the same sheet: { file url: sheet url }
function savedSheets() {
  try { return JSON.parse(localStorage.getItem('gsheets') || '{}') } catch { return {} }
}
function rememberSheet(fileUrl, sheetUrl) {
  try { localStorage.setItem('gsheets', JSON.stringify({ ...savedSheets(), [fileUrl]: sheetUrl })) } catch { /* private window */ }
}

// "Save to Google Sheets / Docs / Slides / Drive" under a file card (asks Google's permission once).
function GoogleButton({ item }) {
  const [link, setLink] = useState(() => savedSheets()[item.url] || null)
  const [state, setState] = useState('')   // '' | 'saving' | error message
  const app = GOOGLE_APP[item.kind]?.name || 'Google Drive'
  async function save() {
    if (link) { window.open(link, '_blank', 'noopener'); return }
    setState('saving')
    try {
      const url = await saveToGoogle(item)
      rememberSheet(item.url, url)
      setLink(url)
      setState('')
      window.open(url, '_blank', 'noopener')
    } catch (e) {
      setState(e.message)
    }
  }
  return (
    <>
      <button className="gsheet-btn" onClick={save} disabled={state === 'saving'}
        title={link ? `Open it in ${app}` : `Create it in ${app} in your Google Drive`}>
        <Icon name={link ? 'external' : (KIND_ICON[item.kind] || 'file')} size={15} />
        {state === 'saving' ? 'Saving to Google…' : link ? `Open in ${app}` : `Save to ${app}`}
      </button>
      {state && state !== 'saving' && <span className="gsheet-err" role="alert">{state}</span>}
    </>
  )
}

export function FileCard({ item, active, onOpen }) {
  return (
    <div className="fcard-wrap">
    <div className={`fcard kind-${item.kind} ${active ? 'active' : ''}`}>
      <button className="fcard-main" onClick={() => onOpen(item)} aria-label={`Preview ${item.name}`}>
        <span className="fcard-icon"><Icon name={KIND_ICON[item.kind] || 'file'} size={20} /></span>
        <span className="fcard-text">
          <span className="fcard-title">{item.title}</span>
          <span className="fcard-sub">{item.group} · {EXT[item.kind] || item.kind.toUpperCase()}{item.size ? ` · ${size(item.size)}` : ''}</span>
        </span>
      </button>
      <a className="msg-action fcard-dl" href={item.url} download={item.name} title="Download" aria-label={`Download ${item.name}`}>
        <Icon name="download" size={17} />
      </a>
    </div>
    <GoogleButton item={item} />
    </div>
  )
}

export function FilePreview({ item, onClose }) {
  const [tab, setTab] = useState('preview')
  const [copied, setCopied] = useState(false)
  const pre = useRef(null)
  // while the model writes, keep the newest line in view
  useEffect(() => { if (item?.streaming && pre.current) pre.current.scrollTop = pre.current.scrollHeight }, [item?.code, item?.streaming])
  if (!item) return null
  const live = item.streaming
  const code = item.code && (tab === 'code' || live)
  const scripted = item.kind === 'react' || item.kind === 'html'
  return (
    <aside className="preview-pane" aria-label={`Preview of ${item.name}`}>
      <header className="preview-head">
        <div className="preview-name">
          <span className="preview-title">{item.title}</span>
          <span className="preview-kind">· {EXT[item.kind] || item.label}</span>
        </div>
        {live && <span className="preview-live" role="status">Writing code…</span>}
        {item.code && !live && (
          <div className="ptabs" role="tablist">
            <button role="tab" aria-selected={tab === 'preview'} className={tab === 'preview' ? 'on' : ''} onClick={() => setTab('preview')}>
              <Icon name="eye" size={14} />Preview
            </button>
            <button role="tab" aria-selected={tab === 'code'} className={tab === 'code' ? 'on' : ''} onClick={() => setTab('code')}>
              <Icon name="code" size={14} />Code
            </button>
          </div>
        )}
        {code && (
          <button className="icon-btn" title="Copy code" aria-label="Copy code"
            onClick={() => navigator.clipboard.writeText(item.code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })}>
            <Icon name={copied ? 'check' : 'copy'} size={17} />
          </button>
        )}
        {!live && <>
          <a className="icon-btn" href={item.url} download={item.name} title="Download" aria-label="Download"><Icon name="download" size={17} /></a>
          <a className="icon-btn" href={item.preview_url} target="_blank" rel="noreferrer" title="Open in new tab" aria-label="Open in new tab">
            <Icon name="external" size={17} />
          </a>
        </>}
        <button className="icon-btn" onClick={onClose} title="Close preview" aria-label="Close preview"><Icon name="x" size={18} /></button>
      </header>
      <div className="preview-body">
        {code
          ? <pre className="preview-code" ref={pre}><code>{item.code}</code></pre>
          : <iframe key={item.preview_url} title={item.name} src={item.preview_url}
              {...(scripted && { sandbox: 'allow-scripts allow-forms allow-modals allow-popups' })} />}
      </div>
    </aside>
  )
}
