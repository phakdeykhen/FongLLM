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
function fileName(item) {
  return item.name || item.url.split('/').pop()
}

export function DownloadButton({ item, className = 'msg-action', size = 15 }) {
  return (
    <a className={className} href={item.url} download={fileName(item)} title="Download" aria-label="Download"
      onClick={(e) => e.stopPropagation()}>
      <Icon name="download" size={size} />
    </a>
  )
}

export function MediaView({ item, onOpen }) {
  return (
    <div className="msg-media">
      {item.type === 'video'
        ? <video src={item.url} controls />
        : <img src={item.url} alt={item.prompt || 'Generated image'} onClick={() => onOpen?.(item)} />}
      <div className="msg-media-cap">
        <span>{item.prompt}{item.seconds ? ` · ${item.seconds}s` : ''}</span>
        <DownloadButton item={item} />
      </div>
    </div>
  )
}

export function Lightbox({ item, onClose }) {
  if (!item) return null
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-label="Image preview">
      {item.type === 'video' ? <video src={item.url} controls autoPlay onClick={(e) => e.stopPropagation()} />
        : <img src={item.url} alt={item.prompt || 'Generated image'} />}
      <div className="lightbox-cap" onClick={(e) => e.stopPropagation()}>
        <span>{item.prompt || item.name} · {fmt(item.date)}</span>
        <a className="lightbox-dl" href={item.url} download={fileName(item)}><Icon name="download" size={16} />Download</a>
        <button className="lightbox-dl" onClick={onClose}><Icon name="x" size={16} />Close</button>
      </div>
    </div>
  )
}
