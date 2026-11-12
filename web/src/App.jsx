import { useCallback, useEffect, useRef, useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import Composer from './components/Composer.jsx'
import ChatView from './components/ChatView.jsx'
import Icon from './components/Icon.jsx'
import { Lightbox, MediaCard } from './components/Media.jsx'
import { DocumentsPage, MediaPage, SearchPage, SettingsPage } from './components/Pages.jsx'
import { getInfo, listMedia, streamChat } from './api.js'

const DEFAULT_SETTINGS = { model: 'mistral', temperature: 0.7, max_new: 512, use_tools: true, top_k: 3 }
const FALLBACK_MODELS = [
  { id: 'mistral', name: 'FongAI 3.4', detail: 'Smart and fast · creates images and videos' },
  { id: 'fongai', name: 'FongAI 3.2', detail: 'Tiny 64M model trained here · mostly Chinese' },
]

function load(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback } catch { return fallback }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* storage full or blocked */ }
}
const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6)

export default function App() {
  const [chats, setChats] = useState(() => load('fongai.chats', []))
  const [settings, setAll] = useState(() => ({ ...DEFAULT_SETTINGS, ...load('fongai.settings', {}) }))
  const [view, setView] = useState('home')
  const [currentId, setCurrentId] = useState(null)   // null = a fresh, unsaved chat
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 800)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [info, setInfo] = useState(null)
  const [docs, setDocs] = useState({ documents: [], passages: 0 })
  const [recent, setRecent] = useState([])
  const [lightbox, setLightbox] = useState(null)
  const abort = useRef(null)

  useEffect(() => save('fongai.chats', chats), [chats])
  useEffect(() => save('fongai.settings', settings), [settings])
  useEffect(() => {
    getInfo().then(setInfo).catch(() => setInfo({ error: true }))
    listMedia('image').then((m) => setRecent(m.slice(0, 3))).catch(() => {})
  }, [])

  const setSettings = useCallback((patch) => setAll((s) => ({ ...s, ...patch })), [])
  const chat = chats.find((c) => c.id === currentId)
  const models = info?.models || FALLBACK_MODELS

  const updateChat = (id, fn) => setChats((cs) => cs.map((c) => (c.id === id ? fn(c) : c)))
  const patchLast = (id, fn) => updateChat(id, (c) => {
    const msgs = c.messages.slice()
    msgs[msgs.length - 1] = fn({ ...msgs[msgs.length - 1] })
    return { ...c, messages: msgs, updated: Date.now() }
  })

  async function send(text) {
    let id = currentId
    const base = chat?.messages || []
    if (!chat) {
      id = newId()
      setChats((cs) => [...cs, { id, title: text.length > 40 ? text.slice(0, 40) + '…' : text, messages: [], updated: Date.now() }])
      setCurrentId(id)
    }
    setView('home')
    const history = base.filter((m) => m.content).map(({ role, content }) => ({ role, content }))
    updateChat(id, (c) => ({
      ...c, updated: Date.now(),
      messages: [...c.messages, { role: 'user', content: text }, { role: 'assistant', content: '', media: [], sources: [] }],
    }))
    setBusy(true)
    setStatus('')
    abort.current = new AbortController()
    let gotMedia = false
    try {
      await streamChat({
        messages: [...history, { role: 'user', content: text }],
        model: settings.model, temperature: settings.temperature, max_new: settings.max_new,
        use_tools: settings.use_tools, top_k: settings.top_k,
      }, (ev) => {
        if (ev.type === 'text') patchLast(id, (m) => ({ ...m, content: m.content + ev.delta }))
        else if (ev.type === 'status') setStatus(ev.text)
        else if (ev.type === 'sources') patchLast(id, (m) => ({ ...m, sources: ev.items }))
        else if (ev.type === 'media') { gotMedia = true; patchLast(id, (m) => ({ ...m, media: [...(m.media || []), ev.item] })) }
        else if (ev.type === 'error') patchLast(id, (m) => ({ ...m, error: ev.text }))
      }, abort.current.signal)
    } catch (e) {
      if (e.name !== 'AbortError') patchLast(id, (m) => ({ ...m, error: `Couldn't reach the FongAI server (${e.message}). Is \`uvicorn server.api:app --port 8000\` running?` }))
    }
    setBusy(false)
    setStatus('')
    if (gotMedia) listMedia('image').then((m) => setRecent(m.slice(0, 3))).catch(() => {})
  }

  function newChat() {
    if (busy) abort.current?.abort()
    setCurrentId(null)
    setView('home')
  }
  function openChat(id) {
    setCurrentId(id)
    setView('home')
    if (window.innerWidth <= 800) setSidebarOpen(false)
  }
  function deleteChat(id) {
    setChats((cs) => cs.filter((c) => c.id !== id))
    if (id === currentId) setCurrentId(null)
  }
  function nav(id) {
    if (id === 'home') setCurrentId(null)
    setView(id)
    if (window.innerWidth <= 800) setSidebarOpen(false)
  }

  const composer = (big) => (
    <Composer big={big} busy={busy} onSend={send} onStop={() => abort.current?.abort()} autoFocus
      models={models} model={settings.model} onModel={(m) => setSettings({ model: m })} onDocs={setDocs} />
  )

  let main
  if (view === 'search') main = <SearchPage chats={chats} onOpen={openChat} />
  else if (view === 'images') main = <MediaPage kind="image" onOpen={setLightbox} />
  else if (view === 'videos') main = <MediaPage kind="video" onOpen={setLightbox} />
  else if (view === 'docs') main = <DocumentsPage docs={docs} setDocs={setDocs} settings={settings} setSettings={setSettings} />
  else if (view === 'settings') main = <SettingsPage settings={settings} setSettings={setSettings} info={info} onClearChats={() => { setChats([]); setCurrentId(null) }} />
  else if (chat?.messages.length) {
    main = (
      <div className="chat-layout">
        <header className="chat-head"><span title={chat.title}>{chat.title}</span></header>
        <ChatView chat={chat} busy={busy} status={status} onOpenImage={setLightbox} />
        <div className="dock">{composer(false)}<p className="dock-note">Fong AI can make mistakes. Check important answers.</p></div>
      </div>
    )
  } else {
    main = (
      <div className="home">
        <video className="hero-logo" src="/logo-mark.mp4" poster="/logo-mark-poster.jpg" autoPlay muted loop playsInline aria-label="Fong AI logo" />
        <h1 className="hero">Coffee and <span className="brand-ai">Fong AI</span> time?</h1>
        <p className="hero-sub">Your friendly language model</p>
        {composer(true)}
        {info?.error && <p className="msg-error center">Can't reach the Fong AI server. Start it with <code>uvicorn server.api:app --port 8000</code></p>}
        {info && !info.error && !info.ollama && settings.model === 'mistral' && (
          <p className="msg-warn center">FongAI 3.4 isn't available right now. Switch to FongAI 3.2, or see Settings to start it.</p>
        )}
        {recent.length > 0 && (
          <section className="recent-media">
            <div className="section-head"><span>Recent images</span><button className="link" onClick={() => setView('images')}>View all</button></div>
            <div className="mgrid">{recent.map((it) => <MediaCard key={it.url} item={it} onOpen={setLightbox} />)}</div>
          </section>
        )}
      </div>
    )
  }

  return (
    <div className="app">
      <Sidebar open={sidebarOpen} onToggle={() => setSidebarOpen(false)} view={view} chats={chats} currentId={currentId}
        device={info?.device} onNav={nav} onNew={newChat} onOpen={openChat} onDelete={deleteChat} />
      <main className="main">
        {!sidebarOpen && (
          <button className="icon-btn open-side" onClick={() => setSidebarOpen(true)} title="Open sidebar" aria-label="Open sidebar">
            <Icon name="sidebar" />
          </button>
        )}
        {main}
      </main>
      <Lightbox item={lightbox} onClose={() => setLightbox(null)} />
    </div>
  )
}
