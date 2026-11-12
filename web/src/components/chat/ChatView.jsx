import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Icon from '@/components/ui/Icon.jsx'
import { MediaView } from '@/components/media/Media.jsx'

function CopyButton({ text }) {
  const [done, setDone] = useState(false)
  return (
    <button className="msg-action" title="Copy" aria-label="Copy answer"
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

export default function ChatView({ chat, busy, status, onOpenImage }) {
  const end = useRef(null)
  const last = chat.messages[chat.messages.length - 1]
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [chat.messages.length, last?.content, status])

  return (
    <div className="thread">
      {chat.messages.map((m, i) => m.role === 'user' ? (
        <div key={i} className="user-row"><div className="user-bubble">{m.content}</div></div>
      ) : (
        <div key={i} className="assistant">
          <Sources items={m.sources} />
          {m.content && <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>}
          {m.media?.map((item) => <MediaView key={item.url} item={item} onOpen={onOpenImage} />)}
          {m.error && <div className="msg-error">{m.error}</div>}
          {busy && i === chat.messages.length - 1 ? (
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
