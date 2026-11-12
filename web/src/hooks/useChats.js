import { useRef, useState } from 'react'
import { streamChat } from '@/api/client.js'
import { chatTitle, newId } from '@/lib/format.js'
import { SERVER_CMD } from '@/lib/constants.js'
import useLocalStorage from './useLocalStorage.js'

// Chats (saved in the browser) plus sending a message and streaming the answer into it.
export default function useChats({ settings, onMedia }) {
  const [chats, setChats] = useLocalStorage('chats', [])
  const [currentId, setCurrentId] = useState(null)   // null = a fresh, unsaved chat
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [progress, setProgress] = useState(null)   // { kind: 'image' | 'video', value: 0-100 } while one is being made
  const abort = useRef(null)

  const chat = chats.find((c) => c.id === currentId)
  const updateChat = (id, fn) => setChats((cs) => cs.map((c) => (c.id === id ? fn(c) : c)))
  const patchLast = (id, fn) => updateChat(id, (c) => {
    const msgs = c.messages.slice()
    msgs[msgs.length - 1] = fn({ ...msgs[msgs.length - 1] })
    return { ...c, messages: msgs, updated: Date.now() }
  })

  // `upto` (edit / retry): drop the message at that index and everything after it, then send `text` in its place.
  // `images`: photo data URLs attached to this message (sent to the vision model, kept with the message).
  async function send(text, upto, images = []) {
    if (busy) return
    let id = currentId
    const cut = (msgs) => (upto == null ? msgs : msgs.slice(0, upto))
    const base = cut(chat?.messages || [])
    if (!chat) {
      id = newId()
      setChats((cs) => [...cs, { id, title: chatTitle(text), messages: [], updated: Date.now() }])
      setCurrentId(id)
    }
    const history = base.filter((m) => m.content).map(({ role, content }) => ({ role, content }))
    updateChat(id, (c) => ({
      ...c, updated: Date.now(),
      messages: [...cut(c.messages), { role: 'user', content: text, at: Date.now(), ...(images.length && { images }) }, { role: 'assistant', content: '', media: [], sources: [] }],
    }))
    setBusy(true)
    setStatus('')
    setProgress(null)
    abort.current = new AbortController()
    let gotMedia = false
    try {
      await streamChat({
        messages: [...history, { role: 'user', content: text, ...(images.length && { images }) }],
        model: settings.model, temperature: settings.temperature, max_new: settings.max_new,
        use_tools: settings.use_tools, top_k: settings.top_k,
      }, (ev) => {
        if (ev.type === 'text') patchLast(id, (m) => ({ ...m, content: m.content + ev.delta }))
        else if (ev.type === 'status') setStatus(ev.text)
        else if (ev.type === 'progress') setProgress({ kind: ev.kind, value: ev.value })
        else if (ev.type === 'sources') patchLast(id, (m) => ({ ...m, sources: ev.items }))
        else if (ev.type === 'media') { gotMedia = true; setProgress(null); patchLast(id, (m) => ({ ...m, media: [...(m.media || []), ev.item] })) }
        else if (ev.type === 'error') { setProgress(null); patchLast(id, (m) => ({ ...m, error: ev.text })) }
      }, abort.current.signal)
    } catch (e) {
      if (e.name !== 'AbortError') patchLast(id, (m) => ({ ...m, error: `Couldn't reach the Fong AI server (${e.message}). Is \`${SERVER_CMD}\` running?` }))
    }
    setBusy(false)
    setStatus('')
    setProgress(null)
    if (gotMedia) onMedia?.()
  }

  const stop = () => abort.current?.abort()
  const startNew = () => { if (busy) stop(); setCurrentId(null) }
  const remove = (id) => { setChats((cs) => cs.filter((c) => c.id !== id)); if (id === currentId) setCurrentId(null) }
  const patch = (id, fields) => updateChat(id, (c) => ({ ...c, ...fields }))
  const togglePin = (id) => updateChat(id, (c) => ({ ...c, pinned: !c.pinned }))
  const rename = (id, title) => patch(id, { title })
  const archive = (id) => { patch(id, { archived: true, pinned: false }); if (id === currentId) setCurrentId(null) }
  const clearAll = () => { setChats([]); setCurrentId(null) }

  return { chats, chat, currentId, setCurrentId, busy, status, progress, send, stop, startNew, remove, clearAll, togglePin, rename, archive }
}
