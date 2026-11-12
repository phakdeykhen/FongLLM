import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'

// Chats live in this browser only, so "share" = native share sheet when available, else copy the transcript.
function transcript(chat) {
  const lines = chat.messages.filter((m) => m.content).map((m) => `${m.role === 'user' ? 'You' : 'Fong AI'}: ${m.content}`)
  return `${chat.title}\n\n${lines.join('\n\n')}`
}

async function shareChat(chat) {
  const text = transcript(chat)
  if (navigator.share) {
    try { await navigator.share({ title: chat.title, text }); return 'Shared' } catch (e) { if (e.name === 'AbortError') return null }
  }
  await navigator.clipboard.writeText(text)
  return 'Copied to clipboard'
}

// Title bar of an open chat: title with a dropdown of actions, plus a Share button on the right.
export default function ChatHeader({ chat, onPin, onRename, onArchive, onDelete }) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [toast, setToast] = useState('')
  const ref = useRef(null)

  const share = async () => {
    setOpen(false)
    try { const msg = await shareChat(chat); if (msg) setToast(msg) } catch { setToast("Couldn't share this chat") }
  }

  const actions = {
    p: () => { setOpen(false); onPin() },
    r: () => { setOpen(false); setEditing(true) },
    s: share,
    a: () => { setOpen(false); onArchive() },
    d: () => { setOpen(false); if (confirm(`Delete "${chat.title}"?`)) onDelete() },
  }

  useEffect(() => {
    if (!open) return
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const key = (e) => {
      if (e.key === 'Escape') return setOpen(false)
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const fn = actions[e.key.toLowerCase()]
      if (fn) { e.preventDefault(); fn() }
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', key)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('keydown', key) }
  })

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 2200)
    return () => clearTimeout(t)
  }, [toast])

  const commit = (value) => {
    const title = value.trim()
    if (title && title !== chat.title) onRename(title)
    setEditing(false)
  }

  return (
    <header className="chat-head">
      <div className="ch-title" ref={ref}>
        {editing ? (
          <input className="ch-rename" defaultValue={chat.title} autoFocus onFocus={(e) => e.target.select()} aria-label="Chat title"
            onBlur={(e) => commit(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') commit(e.target.value); if (e.key === 'Escape') setEditing(false) }} />
        ) : (
          <button className={`ch-btn ${open ? 'open' : ''}`} onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}>
            {chat.pinned && <Icon name="pin" size={14} className="ch-pin" />}
            <span title={chat.title}>{chat.title}</span>
            <span className="ch-chev"><Icon name="chevron" size={15} className={open ? 'flip' : ''} /></span>
          </button>
        )}
        {open && (
          <div className="ch-menu" role="menu">
            <button role="menuitem" className="pm-item" onClick={actions.p}><Icon name="pin" size={17} />{chat.pinned ? 'Unpin' : 'Pin'}<kbd>P</kbd></button>
            <button role="menuitem" className="pm-item" onClick={actions.r}><Icon name="rename" size={17} />Rename<kbd>R</kbd></button>
            <button role="menuitem" className="pm-item" onClick={actions.s}><Icon name="share" size={17} />Share chat<kbd>S</kbd></button>
            <div className="pm-sep" />
            <button role="menuitem" className="pm-item" onClick={actions.a}><Icon name="archive" size={17} />Archive<kbd>A</kbd></button>
            <button role="menuitem" className="pm-item danger-item" onClick={actions.d}><Icon name="trash" size={17} />Delete<kbd>D</kbd></button>
          </div>
        )}
      </div>
      <button className="ch-share" onClick={share}><Icon name="share" size={16} />Share</button>
      {toast && <div className="ch-toast" role="status">{toast}</div>}
    </header>
  )
}
