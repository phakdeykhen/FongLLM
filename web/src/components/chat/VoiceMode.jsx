import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { speakKhmer, transcribe } from '@/api/client.js'
import { startRecording } from '@/lib/recorder.js'

const KHMER = /[ក-៿]/
const CHINESE = /[一-鿿]/
const QUIET_MS = 1200   // this much silence after you spoke = you're done
const MAX_MS = 30000    // one turn is at most 30 s

// What to read aloud: plain words, no markdown or code. A Khmer reply comes as "English ... 🇰🇭 Khmer": say the Khmer.
export function spokenText(reply) {
  const t = reply.includes('🇰🇭') ? reply.split('🇰🇭').pop() : reply
  return t.replace(/```[\s\S]*?```/g, ' ').replace(/`([^`]*)`/g, '$1').replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s*(#+|[-*+]|\d+\.|>)\s+/gm, '').replace(/[*_~|#>]/g, '').replace(/-{3,}/g, ' ')
    .replace(/\s+/g, ' ').trim()
}

// Hands-free conversation: listen -> hear you stop -> transcribe -> FongAI answers -> read it aloud -> listen again.
// onSend(text) sends the message into the chat and resolves with the reply text.
export default function VoiceMode({ lang, onSend, onClose }) {
  const [phase, setPhase] = useState('starting') // starting | listening | hearing | thinking | speaking | muted
  const [level, setLevel] = useState(0)
  const [note, setNote] = useState('')
  const send = useRef(onSend)
  send.current = onSend   // always the latest: the chat changes after the first message
  const langRef = useRef(lang)
  langRef.current = lang
  const session = useRef(null)   // { alive, cancelListen, endSpeech }

  async function listen(s) {
    if (!s.alive) return
    setPhase('listening')
    setNote('')
    let floor = null, started = 0, lastLoud = 0
    const quiet = []
    const t0 = performance.now()
    let starting
    const result = await new Promise((resolve) => {
      s.cancelListen = () => resolve('cancel')
      starting = startRecording((rms) => {
        const now = performance.now()
        setLevel(rms)
        if (now - t0 < 500) { quiet.push(rms); return }   // the first half second tells us how loud the room is
        if (floor === null) floor = quiet.length ? quiet.reduce((a, b) => a + b) / quiet.length : 0.005
        if (rms > Math.max(0.02, floor * 3)) {
          lastLoud = now
          if (!started) { started = now; setPhase('hearing') }
        }
        if (started && (now - lastLoud > QUIET_MS || now - started > MAX_MS)) resolve('spoke')
      })
      starting.catch(resolve)
    })
    s.cancelListen = null
    setLevel(0)
    const stop = await starting.catch(() => null)   // also releases the mic when muted in the first instant
    const wav = stop ? await stop() : null
    if (result instanceof Error) {
      setNote('Microphone access was blocked. Allow it in the browser address bar.')
      setPhase('muted')
      return
    }
    if (result !== 'spoke' || !s.alive) return
    if (lastLoud - started < 250) return listen(s)   // a click or a cough, not words
    setPhase('thinking')
    let text = ''
    try {
      text = (await transcribe(wav, 'voice.wav', langRef.current)).trim()
    } catch (e) {
      setNote(e.message)
    }
    if (!s.alive) return
    if (!text) return listen(s)
    const reply = await send.current(text)
    if (!s.alive) return
    await say(s, reply || '')
    listen(s)
  }

  async function say(s, reply) {
    const text = spokenText(reply)
    if (!text || !s.alive) return
    setPhase('speaking')
    await new Promise((done) => {
      s.endSpeech = done
      if (KHMER.test(text)) {   // the browser has no Khmer voice: the server makes one
        speakKhmer(text).then((blob) => {
          const audio = new Audio(URL.createObjectURL(blob))
          s.endSpeech = () => { audio.pause(); URL.revokeObjectURL(audio.src); done() }
          audio.onended = s.endSpeech
          audio.onerror = s.endSpeech
          audio.play().catch(s.endSpeech)
        }, () => { setNote("Couldn't speak Khmer. Is the server running?"); done() })
      } else {
        const u = new SpeechSynthesisUtterance(text)
        u.lang = CHINESE.test(text) ? 'zh-CN' : 'en-US'
        s.endSpeech = () => { speechSynthesis.cancel(); done() }
        u.onend = done
        u.onerror = done
        speechSynthesis.speak(u)
      }
    })
    s.endSpeech = null
  }

  useEffect(() => {
    const s = { alive: true }
    session.current = s
    listen(s)
    return () => { s.alive = false; s.cancelListen?.(); s.endSpeech?.() }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  function toggleMic() {
    const s = session.current
    if (phase === 'muted') { listen(s); return }
    if (phase === 'listening' || phase === 'hearing') { s.cancelListen?.(); setPhase('muted') }
  }

  function tapOrb() {   // interrupt FongAI while it talks
    if (phase === 'speaking') session.current.endSpeech?.()
    else if (phase === 'muted') listen(session.current)
  }

  const km = lang === 'km'
  const label = {
    starting: 'Starting…',
    listening: km ? 'កំពុងស្តាប់… Listening' : 'Listening…',
    hearing: km ? 'កំពុងស្តាប់…' : 'Listening…',
    thinking: km ? 'កំពុងគិត… Thinking' : 'Thinking…',
    speaking: 'Speaking · tap the orb to interrupt',
    muted: 'Mic is off · tap the orb to talk',
  }[phase]
  const listening = phase === 'listening' || phase === 'hearing'

  return (
    <div className="voice" role="region" aria-label="Voice mode">
      <button className={`orb ${phase}`} style={{ '--lvl': Math.min(1, level * 14) }} onClick={tapOrb}
        aria-label={phase === 'speaking' ? 'Interrupt' : 'Voice mode'} />
      <div className="voice-status" aria-live="polite">{note || label}</div>
      <div className="voice-bar">
        <span className="voice-lang">{km ? 'ខ្មែរ' : 'EN'}</span>
        <div className="grow" />
        <button className={`icon-btn ${phase === 'muted' ? 'rec' : ''}`} onClick={toggleMic}
          disabled={!listening && phase !== 'muted'}
          title={phase === 'muted' ? 'Turn the mic on' : 'Turn the mic off'} aria-label="Mute microphone">
          <Icon name={phase === 'muted' ? 'micOff' : 'mic'} size={19} />
        </button>
        <button className="send voice-end" onClick={onClose} title="End voice mode" aria-label="End voice mode">
          <Icon name="x" size={18} />
        </button>
      </div>
    </div>
  )
}
