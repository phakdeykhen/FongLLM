import { useEffect, useRef, useState } from 'react'
import { makeTitle, streamChat } from '@/api/client.js'
import { chatTitle, newId } from '@/lib/format.js'
import { SERVER_CMD } from '@/lib/constants.js'
import useLocalStorage from './useLocalStorage.js'

// Chats (saved in the browser) plus sending a message and streaming the answer into it.
export default function useChats({ settings, onMedia, onFile }) {
  const [chats, setChats] = useLocalStorage('chats', [])
  const [currentId, setCurrentId] = useState(null)   // null = a fresh, unsaved chat
  const [busy, setBusy] = useState(false)
  const [busyId, setBusyId] = useState(null)   // the chat the answer is streaming into (other chats aren't busy)
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
  // `edit`: images[0] is a generated picture to redraw with the changes in `text` ("add a person next to the car").
  // `voice`: voice mode: ask for a short spoken answer. Returns the reply text when it's done.
  async function send(text, upto, images = [], edit = false, voice = false) {
    if (busy) return ''
    let reply = ''
    let id = currentId
    const cut = (msgs) => (upto == null ? msgs : msgs.slice(0, upto))
    const base = cut(chat?.messages || [])
    const firstTurn = base.length === 0
    if (!chat) {
      id = newId()
      setChats((cs) => [...cs, { id, title: chatTitle(text), messages: [], updated: Date.now() }])
      setCurrentId(id)
    }
    // the newest earlier photo goes along too, so "Yes, make the poster" can still use it (older ones stay home)
    const lastPhoto = base.findLast((m) => m.images?.length)
    const history = base.filter((m) => m.content || m === lastPhoto).map((m) => ({
      role: m.role, content: m.content || '', ...(m === lastPhoto && { images: m.images }),
    }))
    updateChat(id, (c) => ({
      ...c, updated: Date.now(),
      messages: [...cut(c.messages), { role: 'user', content: text, at: Date.now(), ...(images.length && { images }) }, { role: 'assistant', content: '', media: [], files: [], sources: [] }],
    }))
    setBusy(true)
    setBusyId(id)
    setStatus('')
    setProgress(null)
    abort.current = new AbortController()
    let gotMedia = false
    try {
      await streamChat({
        messages: [...history, { role: 'user', content: text, ...(images.length && { images }), ...(edit && { edit: true }) }],
        model: settings.model, temperature: settings.temperature, max_new: settings.max_new,
        use_tools: settings.use_tools, image_hd: settings.image_hd, top_k: settings.top_k, voice,
      }, (ev) => {
        if (ev.type === 'text') { reply += ev.delta; patchLast(id, (m) => ({ ...m, content: m.content + ev.delta })) }
        else if (ev.type === 'status') setStatus(ev.text)
        else if (ev.type === 'progress') setProgress({ kind: ev.kind, value: ev.value })
        else if (ev.type === 'sources') patchLast(id, (m) => ({ ...m, sources: ev.items }))
        else if (ev.type === 'media') { gotMedia = true; setProgress(null); patchLast(id, (m) => ({ ...m, media: [...(m.media || []), ev.item] })) }
        else if (ev.type === 'file') { patchLast(id, (m) => ({ ...m, files: [...(m.files || []), ev.item] })); onFile?.(ev.item) }
        else if (ev.type === 'google') patchLast(id, (m) => ({ ...m, google: [...(m.google || []), ev.item] }))
        else if (ev.type === 'error') { setProgress(null); patchLast(id, (m) => ({ ...m, error: ev.text })) }
      }, abort.current.signal)
    } catch (e) {
      if (e.name !== 'AbortError') patchLast(id, (m) => ({ ...m, error: `Couldn't reach the Fong AI server (${e.message}). Is \`${SERVER_CMD}\` running?` }))
    }
    setBusy(false)
    setBusyId(null)
    setStatus('')
    setProgress(null)
    if (gotMedia) onMedia?.()
    if (firstTurn) nameChat(id, text, reply)
    return reply
  }

  // A short title from the model ("Tesla Car Game In Python") instead of the first words typed. Never over a rename.
  function nameChat(id, text, reply) {
    makeTitle(text, reply).then((t) => {
      if (t) setChats((cs) => cs.map((c) => (c.id === id && !c.titled ? { ...c, title: t, titled: true } : c)))
    }).catch(() => {})
  }

  // Old chats still named after their first words get a proper title the first time they're opened.
  useEffect(() => {
    if (!chat || chat.titled || busy) return
    const first = chat.messages.find((m) => m.role === 'user')
    if (!first) return
    if (chat.title !== chatTitle(first.content)) {   // renamed by the person: keep it
      setChats((cs) => cs.map((c) => (c.id === chat.id ? { ...c, titled: true } : c)))
      return
    }
    nameChat(chat.id, first.content, chat.messages.find((m) => m.role === 'assistant')?.content || '')
  }, [chat?.id])   // eslint-disable-line react-hooks/exhaustive-deps

  const stop = () => abort.current?.abort()
  const startNew = () => { if (busy) stop(); setCurrentId(null) }
  const remove = (id) => { setChats((cs) => cs.filter((c) => c.id !== id)); if (id === currentId) setCurrentId(null) }
  const patch = (id, fields) => updateChat(id, (c) => ({ ...c, ...fields }))
  const togglePin = (id) => updateChat(id, (c) => ({ ...c, pinned: !c.pinned }))
  const rename = (id, title) => patch(id, { title, titled: true })
  const archive = (id) => { patch(id, { archived: true, pinned: false }); if (id === currentId) setCurrentId(null) }
  const clearAll = () => { setChats([]); setCurrentId(null) }

  return { chats, chat, currentId, setCurrentId, busy, busyId, status, progress, send, stop, startNew, remove, clearAll, togglePin, rename, archive }
}
