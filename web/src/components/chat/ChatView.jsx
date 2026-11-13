import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Icon from '@/components/ui/Icon.jsx'
import { MediaView } from '@/components/media/Media.jsx'
import { FileCard } from '@/components/files/Files.jsx'
import GoogleCard from '@/components/google/GoogleCard.jsx'
import { timeAgo } from '@/lib/format.js'

function CopyButton({ text, label = 'Copy answer' }) {
  const [done, setDone] = useState(false)
  return (
    <button className="msg-action" title="Copy" aria-label={label}
      onClick={() => navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) })}>
      <Icon name={done ? 'check' : 'copy'} size={15} />
    </button>
  )
}

function Sources({ items }) {
  const [open, setOpen] = useState(false)
  if (!items?.length) return null
  return (
    <div className="sources">
      <button className="sources-toggle" onClick={() => setOpen(!open)}>
        <Icon name="doc" size={15} /> Used {items.length} passage{items.length > 1 ? 's' : ''} from your documents
        <Icon name="chevron" size={14} className={open ? 'flip' : ''} />
      </button>
      {open && items.map((s, i) => (
        <blockquote key={i}><b>{s.source}</b> · score {s.score}<br />{s.text}</blockquote>
      ))}
    </div>
  )
}

// Your own message: bubble, and on hover the time plus Retry / Edit / Copy. Edit swaps the bubble for a textarea.
function UserMessage({ m, busy, onEdit }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(m.content)
  const start = () => { setDraft(m.content); setEditing(true) }
  const save = () => { const t = draft.trim(); if (!t) return; setEditing(false); onEdit(t, m.images) }

  if (editing) {
    return (
      <div className="user-row editing">
        <div className="user-edit">
          <textarea value={draft} autoFocus rows={Math.min(10, draft.split('\n').length + 1)} aria-label="Edit message"
            onChange={(e) => setDraft(e.target.value)}
            onFocus={(e) => e.target.setSelectionRange(e.target.value.length, e.target.value.length)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setEditing(false)
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); save() }
            }} />
          <div className="user-edit-actions">
            <button className="btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn-solid" onClick={save} disabled={!draft.trim() || busy}>Save</button>
          </div>
        </div>
      </div>
    )
  }
  return (
    <div className="user-row">
      {m.images?.length > 0 && (
        <div className="user-pics">{m.images.map((src, i) => <img key={i} src={src} alt={`Your photo ${i + 1}`} />)}</div>
      )}
      <div className="user-bubble">{m.content}</div>
      <div className="user-actions">
        {m.at && <span className="msg-time">{timeAgo(m.at)}</span>}
        <button className="msg-action" title="Retry" aria-label="Retry this message" disabled={busy} onClick={() => onEdit(m.content, m.images)}>
          <Icon name="retry" size={15} />
        </button>
        <button className="msg-action" title="Edit" aria-label="Edit this message" disabled={busy} onClick={start}>
          <Icon name="rename" size={15} />
        </button>
        <CopyButton text={m.content} label="Copy message" />
      </div>
    </div>
  )
}

// Placeholder while a picture or clip is being made: a dot grid with drifting glow and the percent done.
function Generating({ kind, value }) {
  return (
    <div className="gen" role="status" aria-live="polite">
      <div className="gen-label">Creating {kind}</div>
      <div className="gen-canvas" aria-label={`Creating ${kind}, ${value}% done`}>
        <div className="gen-dots" />
        <div className="gen-dots lit" />
        <span className="gen-pct">{value}%</span>
      </div>
    </div>
  )
}

export default function ChatView({ chat, busy, status, progress, onOpenImage, onEdit, onOpenFile, activeFile }) {
  const end = useRef(null)
  const stick = useRef(true)   // follow new text only while the reader is at the bottom; scrolling up stops it
  const last = chat.messages[chat.messages.length - 1]

  useEffect(() => {
    const box = end.current?.closest('.main')
    if (!box) return
    const onScroll = () => { stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 120 }
    box.addEventListener('scroll', onScroll, { passive: true })
    return () => box.removeEventListener('scroll', onScroll)
  }, [])
  // a new message (yours, or opening a chat): jump to the bottom and follow again
  useEffect(() => { stick.current = true; end.current?.scrollIntoView({ block: 'end' }) }, [chat.id, chat.messages.length])
  // streaming text / status / progress: follow only if the reader hasn't scrolled up
  useEffect(() => { if (stick.current) end.current?.scrollIntoView({ block: 'end' }) },
    [last?.content, last?.media?.length, last?.files?.length, status, progress?.kind])

  return (
    <div className="thread">
      {chat.messages.map((m, i) => m.role === 'user' ? (
        <UserMessage key={i} m={m} busy={busy} onEdit={(text, imgs) => onEdit(text, i, imgs)} />
      ) : (
        <div key={i} className="assistant">
          <Sources items={m.sources} />
          {m.content && <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>}
          {m.media?.map((item) => <MediaView key={item.url} item={item} onOpen={onOpenImage} />)}
          {m.google?.map((g, j) => <GoogleCard key={j} item={g} />)}
          {m.files?.length > 0 && (
            <div className="fcards">{m.files.map((f) => <FileCard key={f.url} item={f} active={activeFile?.url === f.url} onOpen={onOpenFile} />)}</div>
          )}
          {m.error && <div className="msg-error">{m.error}</div>}
          {busy && i === chat.messages.length - 1 && progress ? (
            <Generating kind={progress.kind} value={progress.value} />
          ) : busy && i === chat.messages.length - 1 ? (
            <div className="thinking"><span className="think-mark" aria-hidden="true" />{status || 'Thinking…'}</div>
          ) : m.content && (
            <div className="msg-actions"><CopyButton text={m.content} /></div>
          )}
        </div>
      ))}
      <div ref={end} />
    </div>
  )
}
