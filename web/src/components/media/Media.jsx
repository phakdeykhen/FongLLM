import { formatDate as fmt, timeAgo } from '@/lib/format.js'
import Icon from '@/components/ui/Icon.jsx'

export function MediaCard({ item, onOpen, large }) {
  const video = item.type === 'video'
  return (
    <figure className={`mcard ${large ? 'large' : ''}`}>
      <button className="mthumb" onClick={() => onOpen?.(item)} aria-label={`Open ${video ? 'video' : 'image'}`} title={fmt(item.date)}>
        {video
          ? <video src={item.url} muted preload="metadata" />
          : <img src={item.url} alt={item.prompt || 'Generated image'} loading="lazy" />}
        {video && <span className="mbadge"><Icon name="play" size={13} />{item.seconds ? `${item.seconds}s` : 'Video'}</span>}
        <span className="mcap">
          {item.prompt && <span className="mtitle">{item.prompt}</span>}
          <span className="mdate">{timeAgo(item.date)}</span>
        </span>
      </button>
    </figure>
  )
}

// A generated image/video inside a chat answer.
export function MediaView({ item, onOpen }) {
  return (
    <div className="msg-media">
      {item.type === 'video'
        ? <video src={item.url} controls />
        : <img src={item.url} alt={item.prompt || 'Generated image'} onClick={() => onOpen?.(item)} />}
      {item.prompt && <div className="msg-media-cap">{item.prompt}{item.seconds ? ` · ${item.seconds}s` : ''}</div>}
    </div>
  )
}

export function Lightbox({ item, onClose }) {
  if (!item) return null
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-label="Image preview">
      {item.type === 'video' ? <video src={item.url} controls autoPlay onClick={(e) => e.stopPropagation()} />
        : <img src={item.url} alt={item.prompt || 'Generated image'} />}
      <div className="lightbox-cap">{item.prompt || item.name} · {fmt(item.date)}</div>
    </div>
  )
}
