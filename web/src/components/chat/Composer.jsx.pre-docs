import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { transcribe, uploadDocuments } from '@/api/client.js'
import { startRecording } from '@/lib/recorder.js'

const AUDIO = /\.(wav|flac|mp3|ogg|m4a)$/i
const DOC = /\.(txt|md)$/i
const IMAGE = /\.(png|jpe?g|webp|gif|heic|bmp)$/i

// Shrink a photo to at most 1024px JPEG: plenty for the vision model, and small enough to keep in saved chats.
function shrink(f) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const k = Math.min(1, 1024 / Math.max(img.width, img.height))
      const c = document.createElement('canvas')
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k)
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height)
      URL.revokeObjectURL(img.src)
      resolve(c.toDataURL('image/jpeg', 0.85))
    }
    img.onerror = () => reject(new Error(`Couldn't open ${f.name}`))
    img.src = URL.createObjectURL(f)
  })
}

export default function Composer({ big, busy, onSend, onStop, models, model, onModel, onDocs, autoFocus, hd, onHd, voiceLang = 'auto', onVoiceLang, onVoice }) {
  const [text, setText] = useState('')
  const [note, setNote] = useState('')
  const [recording, setRecording] = useState(null) // stop() function while recording
  const [menu, setMenu] = useState(false)
  const [pics, setPics] = useState([]) // attached photos (data URLs) for the next message
  const [editing, setEditing] = useState(false) // pics[0] is a generated image to redraw with the user's changes
  const ta = useRef(null)
  const file = useRef(null)

  useEffect(() => { if (autoFocus) ta.current?.focus() }, [autoFocus])
  useEffect(() => { // "Edit" on a generated image: attach it and ask what to change
    async function onEditImage(e) {
      try {
        const blob = await (await fetch(e.detail)).blob()
        setPics([await shrink(blob)])
        setEditing(true)
        setNote('')
        ta.current?.focus()
      } catch {
        setNote("Couldn't load that image for editing.")
      }
    }
    window.addEventListener('fong:edit-image', onEditImage)
    return () => window.removeEventListener('fong:edit-image', onEditImage)
  }, [])
  useEffect(() => { // grow with the text, like Claude's box
    const el = ta.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 260) + 'px'
  }, [text])
  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(false)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menu])

  function send() {
    const t = text.trim() || (pics.length && !editing ? 'What is in this photo?' : '')
    if (!t || busy) return
    onSend(t, pics, editing && pics.length > 0)
    setText('')
    setPics([])
    setEditing(false)
    setNote('')
  }

  async function addFiles(files) {
    const docs = [...files].filter((f) => DOC.test(f.name))
    const audio = [...files].find((f) => AUDIO.test(f.name))
    const images = [...files].filter((f) => f.type.startsWith('image/') || IMAGE.test(f.name))
    try {
      if (images.length) {
        const urls = await Promise.all(images.slice(0, 4).map(shrink))
        setPics((old) => [...old, ...urls].slice(0, 4))
        ta.current?.focus()
      }
      if (docs.length) {
        setNote(`Indexing ${docs.map((d) => d.name).join(', ')}…`)
        const r = await uploadDocuments(docs)
        onDocs?.(r)
        setNote(`${docs.length} document${docs.length > 1 ? 's' : ''} added · answers will use them`)
      }
      if (audio) {
        setNote(`Transcribing ${audio.name}…`)
        const t = await transcribe(audio, audio.name, voiceLang)
        setText((old) => (old ? old + ' ' : '') + t)
        setNote('')
      }
      if (!docs.length && !audio && !images.length) setNote('Attach photos, .txt or .md documents, or an audio file.')
    } catch (e) {
      setNote(e.message)
    }
  }

  async function toggleMic() {
    if (recording) {
      const stop = recording
      setRecording(null)
      setNote(voiceLang === 'km' ? 'កំពុងស្តាប់… Transcribing Khmer…' : 'Transcribing with Whisper…')
      try {
        const t = await transcribe(await stop(), 'voice.wav', voiceLang)
        setText((old) => (old ? old + ' ' : '') + t)
        setNote('')
        ta.current?.focus()
      } catch (e) {
        setNote(e.message)
      }
      return
    }
    try {
      setRecording(() => null)
      const stop = await startRecording()
      setRecording(() => stop)
      setNote('Listening… click the mic again to stop')
    } catch {
      setNote('Microphone access was blocked. Allow it in the browser address bar and try again.')
    }
  }

  const current = models.find((m) => m.id === model) || models[0]
  return (
    <div className={`composer ${big ? 'big' : ''}`}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files) }}>
      {pics.length > 0 && (
        <div className="composer-pics">
          {pics.map((p, i) => (
            <div key={i} className="composer-pic">
              <img src={p} alt={`Attached photo ${i + 1}`} />
              <button aria-label="Remove photo" title="Remove"
                onClick={() => { setPics(pics.filter((_, j) => j !== i)); if (i === 0) setEditing(false) }}>
                <Icon name="x" size={12} />
              </button>
            </div>
          ))}
          {editing && <span className="composer-note">Editing this image: say what to change or add</span>}
        </div>
      )}
      <textarea ref={ta} rows={1} value={text}
        placeholder={editing ? 'e.g. add a person standing next to the car, make it sunset…' : big ? 'How can I help you today?' : 'Reply to Fong AI…'}
        onChange={(e) => setText(e.target.value)}
        onPaste={(e) => { if (e.clipboardData.files.length) { e.preventDefault(); addFiles(e.clipboardData.files) } }}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }} />
      <div className="composer-row">
        <button className="icon-btn" title="Attach photos, documents or audio" aria-label="Attach files" onClick={() => file.current.click()}>
          <Icon name="plus" size={20} />
        </button>
        <input ref={file} type="file" multiple hidden accept="image/*,.txt,.md,.wav,.flac,.mp3,.ogg,.m4a"
          onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
        {note && <span className="composer-note">{note}</span>}
        <div className="grow" />
        {onHd && (
          <button className={`hd-btn ${hd ? 'on' : ''}`} onClick={() => onHd(!hd)} aria-pressed={!!hd}
            title={hd ? 'HD images: FLUX 1024px, better but takes minutes. Click for Fast.' : 'Fast images: about 5 seconds, 512px. Click for HD (better, takes minutes).'}>
            <Icon name={hd ? 'sparkles' : 'zap'} size={14} />{hd ? 'HD' : 'Fast'}
          </button>
        )}
        {current && (
          <div className="model-pick" onClick={(e) => e.stopPropagation()}>
            <button className="model-btn" onClick={() => setMenu(!menu)} aria-haspopup="listbox" aria-expanded={menu}>
              {current.name} <Icon name="chevron" size={14} />
            </button>
            {menu && (
              <div className="model-menu" role="listbox">
                {models.map((m) => (
                  <button key={m.id} role="option" aria-selected={m.id === model} className="model-opt"
                    onClick={() => { onModel(m.id); setMenu(false) }}>
                    <span><b>{m.name}</b><small>{m.detail}</small></span>
                    {m.id === model && <Icon name="check" size={16} />}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {onVoiceLang && (
          <button className={`hd-btn ${voiceLang === 'km' ? 'on' : ''}`} onClick={() => onVoiceLang(voiceLang === 'km' ? 'auto' : 'km')}
            aria-pressed={voiceLang === 'km'}
            title={voiceLang === 'km' ? 'Voice: Khmer. Click to switch to other languages.' : 'Voice: English and other languages. Click for Khmer.'}>
            {voiceLang === 'km' ? 'ខ្មែរ' : 'EN'}
          </button>
        )}
        <button className={`icon-btn ${recording ? 'rec' : ''}`} title={recording ? 'Stop recording' : 'Speak your question'}
          aria-label="Voice input" onClick={toggleMic}>
          <Icon name="mic" size={19} />
        </button>
        {onVoice && !busy && !text.trim() && !pics.length ? (
          <button className="send" onClick={onVoice} title="Voice mode: talk with Fong AI" aria-label="Start voice mode">
            <Icon name="voice" size={18} />
          </button>
        ) : busy ? (
          <button className="send" onClick={onStop} title="Stop" aria-label="Stop"><Icon name="stop" size={16} /></button>
        ) : (
          <button className="send" onClick={send} disabled={!text.trim() && !pics.length} title="Send" aria-label="Send"><Icon name="arrowUp" size={18} /></button>
        )}
      </div>
    </div>
  )
}
