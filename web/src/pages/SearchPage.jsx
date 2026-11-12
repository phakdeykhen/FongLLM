import { useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'

export default function SearchPage({ chats, onOpen }) {
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
