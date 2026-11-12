import { useEffect, useState } from 'react'
import { listMedia } from '@/api/client.js'

export default function UsagePage({ chats, docs }) {
  const [media, setMedia] = useState(null)
  useEffect(() => { listMedia().then(setMedia).catch(() => setMedia([])) }, [])
  const msgs = chats.reduce((n, c) => n + c.messages.length, 0)
  const asked = chats.reduce((n, c) => n + c.messages.filter((m) => m.role === 'user').length, 0)
  const stats = [
    ['Chats', chats.filter((c) => c.messages.length).length],
    ['Questions asked', asked],
    ['Messages', msgs],
    ['Images created', media ? media.filter((m) => m.type === 'image').length : '…'],
    ['Videos created', media ? media.filter((m) => m.type === 'video').length : '…'],
    ['Documents', docs.documents.length],
  ]
  return (
    <div className="page">
      <h1 className="page-title">Usage</h1>
      <p className="muted">Everything runs on your own computer, so there are no limits or costs.</p>
      <div className="stats">
        {stats.map(([k, v]) => <div key={k} className="stat"><b>{v}</b><span>{k}</span></div>)}
      </div>
    </div>
  )
}
