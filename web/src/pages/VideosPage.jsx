import { useEffect, useState } from 'react'
import { MediaCard } from '@/components/media/Media.jsx'
import { listMedia } from '@/api/client.js'

export default function VideosPage({ onOpen, kind = 'video' }) {
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
