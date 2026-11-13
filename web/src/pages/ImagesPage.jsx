import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { listMedia, makeImage } from '@/api/client.js'
import { IMAGE_STYLES } from '@/lib/constants.js'
import { formatDate } from '@/lib/format.js'

// Images page: style presets, your images, and a box that creates a new image directly.

export default function ImagesPage({ onOpen, onCreated, hd, onHd }) {
  const [tab, setTab] = useState('styles')
  const [mine, setMine] = useState(null)
  const [style, setStyle] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const input = useRef(null)
  const [elapsed, setElapsed] = useState(0)   // seconds since Create was pressed

  useEffect(() => {
    if (!busy) return
    setElapsed(0)
    const t0 = Date.now()
    const id = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(id)
  }, [busy])

  useEffect(() => { listMedia('image').then(setMine).catch(() => setMine([])) }, [])

  function pick(s) {
    setStyle(s.id === style?.id ? null : s)
    input.current?.focus()
  }

  async function create(e) {
    e.preventDefault()
    const t = text.trim()
    if (!t || busy) return
    setBusy(true); setError('')
    try {
      const item = await makeImage(style ? `${t}, ${style.suffix}` : t, hd)
      item.prompt = t
      setMine((m) => [item, ...(m || [])])
      setTab('mine')
      setText('')
      onCreated?.(item)
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  return (
    <div className="studio">
      <div className="studio-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'styles'} className={tab === 'styles' ? 'on' : ''} onClick={() => setTab('styles')}>Styles</button>
        <button role="tab" aria-selected={tab === 'mine'} className={tab === 'mine' ? 'on' : ''} onClick={() => setTab('mine')}>
          My images{mine ? ` · ${mine.length}` : ''}
        </button>
      </div>

      {tab === 'styles' ? (
        <div className="tiles">
          {IMAGE_STYLES.map((s) => (
            <button key={s.id} className={`tile ${style?.id === s.id ? 'on' : ''}`} onClick={() => pick(s)} aria-pressed={style?.id === s.id}>
              <img src={`/styles/${s.id}.jpg`} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
              <span className="tile-label">{s.label}</span>
              {style?.id === s.id && <span className="tile-check"><Icon name="check" size={14} /></span>}
            </button>
          ))}
        </div>
      ) : (
        <div className="tiles">
          {busy && <div className="tile placeholder"><span className="shimmer" /><span className="tile-label">Creating…</span></div>}
          {mine?.map((m) => (
            <button key={m.url} className="tile" onClick={() => onOpen(m)}>
              <img src={m.url} alt={m.prompt || 'Generated image'} loading="lazy" />
              <span className="tile-label">{m.prompt || formatDate(m.date)}</span>
            </button>
          ))}
          {mine && !mine.length && !busy && <p className="muted">No images yet. Describe one below.</p>}
        </div>
      )}

      <form className="studio-bar" onSubmit={create}>
        {style ? (
          <button type="button" className="style-chip" onClick={() => setStyle(null)} title="Remove style">
            {style.label} <Icon name="x" size={13} />
          </button>
        ) : <Icon name="sparkles" size={18} className="bar-spark" />}
        <input ref={input} value={text} onChange={(e) => setText(e.target.value)} placeholder={style ? `Describe a new ${style.label.toLowerCase()} image` : 'Describe a new image'} aria-label="Describe a new image" />
        {busy && (
          <span className="bar-wait" role="status">
            Creating{hd ? ' in HD' : ''}… {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}
            <small>{hd ? 'HD takes 2–5 min' : 'about 20 s'}</small>
          </span>
        )}
        {error && <span className="bar-error" title={error}>{error}</span>}
        {onHd && (
          <button type="button" className={`hd-btn ${hd ? 'on' : ''}`} onClick={() => onHd(!hd)} aria-pressed={!!hd} disabled={busy}
            title={hd ? 'HD: FLUX 1024px, better but takes minutes. Click for Fast.' : 'Fast: about 20 seconds, 512px. Click for HD.'}>
            <Icon name={hd ? 'sparkles' : 'zap'} size={14} />{hd ? 'HD' : 'Fast'}
          </button>
        )}
        <button className="send" disabled={!text.trim() || busy} aria-label="Create image">
          {busy ? <span className="dot-spin" /> : <Icon name="arrowUp" size={18} />}
        </button>
      </form>
    </div>
  )
}
