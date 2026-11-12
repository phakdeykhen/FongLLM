import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { transcribe, uploadDocuments } from '@/api/client.js'
import { startRecording } from '@/lib/recorder.js'

const AUDIO = /\.(wav|flac|mp3|ogg|m4a)$/i
const DOC = /\.(txt|md)$/i

export default function Composer({ big, busy, onSend, onStop, models, model, onModel, onDocs, autoFocus }) {
  const [text, setText] = useState('')
  const [note, setNote] = useState('')
  const [recording, setRecording] = useState(null) // stop() function while recording
  const [menu, setMenu] = useState(false)
  const ta = useRef(null)
  const file = useRef(null)

  useEffect(() => { if (autoFocus) ta.current?.focus() }, [autoFocus])
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
    const t = text.trim()
    if (!t || busy) return
    onSend(t)
    setText('')
    setNote('')
  }

  async function addFiles(files) {
    const docs = [...files].filter((f) => DOC.test(f.name))
    const audio = [...files].find((f) => AUDIO.test(f.name))
    try {
      if (docs.length) {
        setNote(`Indexing ${docs.map((d) => d.name).join(', ')}…`)
        const r = await uploadDocuments(docs)
        onDocs?.(r)
        setNote(`${docs.length} document${docs.length > 1 ? 's' : ''} added · answers will use them`)
      }
      if (audio) {
        setNote(`Transcribing ${audio.name}…`)
        const t = await transcribe(audio, audio.name)
        setText((old) => (old ? old + ' ' : '') + t)
        setNote('')
      }
      if (!docs.length && !audio) setNote('Attach .txt or .md documents, or an audio file.')
    } catch (e) {
      setNote(e.message)
    }
  }

  async function toggleMic() {
    if (recording) {
      const stop = recording
      setRecording(null)
      setNote('Transcribing with Whisper…')
      try {
        const t = await transcribe(await stop())
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
      <textarea ref={ta} rows={1} value={text} placeholder={big ? 'How can I help you today?' : 'Reply to Fong AI…'}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }} />
      <div className="composer-row">
        <button className="icon-btn" title="Attach documents or audio" aria-label="Attach files" onClick={() => file.current.click()}>
          <Icon name="plus" size={20} />
        </button>
        <input ref={file} type="file" multiple hidden accept=".txt,.md,.wav,.flac,.mp3,.ogg,.m4a"
          onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
        {note && <span className="composer-note">{note}</span>}
        <div className="grow" />
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
        <button className={`icon-btn ${recording ? 'rec' : ''}`} title={recording ? 'Stop recording' : 'Speak your question'}
          aria-label="Voice input" onClick={toggleMic}>
          <Icon name="mic" size={19} />
        </button>
        {busy ? (
          <button className="send" onClick={onStop} title="Stop" aria-label="Stop"><Icon name="stop" size={16} /></button>
        ) : (
          <button className="send" onClick={send} disabled={!text.trim()} title="Send" aria-label="Send"><Icon name="arrowUp" size={18} /></button>
        )}
      </div>
    </div>
  )
}
