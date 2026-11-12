const fmt = (iso) => new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

export function MediaCard({ item, onOpen, large }) {
  return (
    <figure className={`mcard ${large ? 'large' : ''}`}>
      <button className="mthumb" onClick={() => onOpen?.(item)} aria-label="Open">
        {item.type === 'video'
          ? <video src={item.url} muted preload="metadata" />
          : <img src={item.url} alt={item.prompt || 'Generated image'} loading="lazy" />}
      </button>
      <figcaption>
        <span className="mtitle">{item.prompt || (item.type === 'video' ? 'Video' : 'Image')}</span>
        <span className="mdate">{fmt(item.date)}</span>
      </figcaption>
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
