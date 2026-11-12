import { useCallback, useEffect, useState } from 'react'
import Sidebar from '@/components/layout/Sidebar.jsx'
import Composer from '@/components/chat/Composer.jsx'
import Icon from '@/components/ui/Icon.jsx'
import { Lightbox } from '@/components/media/Media.jsx'
import LoginModal from '@/components/auth/LoginModal.jsx'
import HomePage from '@/pages/HomePage.jsx'
import ChatPage from '@/pages/ChatPage.jsx'
import SearchPage from '@/pages/SearchPage.jsx'
import ImagesPage from '@/pages/ImagesPage.jsx'
import VideosPage from '@/pages/VideosPage.jsx'
import DocumentsPage from '@/pages/DocumentsPage.jsx'
import SettingsPage from '@/pages/SettingsPage.jsx'
import ProfilePage from '@/pages/ProfilePage.jsx'
import UsagePage from '@/pages/UsagePage.jsx'
import HelpPage from '@/pages/HelpPage.jsx'
import useLocalStorage from '@/hooks/useLocalStorage.js'
import useTheme from '@/hooks/useTheme.js'
import useShortcuts from '@/hooks/useShortcuts.js'
import useChats from '@/hooks/useChats.js'
import { getInfo, listMedia } from '@/api/client.js'
import { DEFAULT_SETTINGS, FALLBACK_MODELS } from '@/lib/constants.js'

const isNarrow = () => window.innerWidth <= 800

export default function App() {
  const [storedSettings, setStoredSettings] = useLocalStorage('settings', {})
  const settings = { ...DEFAULT_SETTINGS, ...storedSettings }
  const setSettings = useCallback((patch) => setStoredSettings((s) => ({ ...s, ...patch })), [setStoredSettings])
  const [profile, setProfile] = useLocalStorage('profile', null)   // null = guest; signing in is optional

  const [view, setView] = useState('home')
  const [sidebarOpen, setSidebarOpen] = useState(() => !isNarrow())
  const [loginOpen, setLoginOpen] = useState(false)
  const [info, setInfo] = useState(null)
  const [docs, setDocs] = useState({ documents: [], passages: 0 })
  const [recent, setRecent] = useState([])
  const [lightbox, setLightbox] = useState(null)

  const refreshRecent = useCallback(() => listMedia('image').then((m) => setRecent(m.slice(0, 3))).catch(() => {}), [])
  const chats = useChats({ settings, onMedia: refreshRecent })
  const dark = useTheme(settings.theme)

  useEffect(() => {
    getInfo().then(setInfo).catch(() => setInfo({ error: true }))
    refreshRecent()
  }, [refreshRecent])

  const go = (next) => { setView(next); if (isNarrow()) setSidebarOpen(false) }
  const newChat = () => { chats.startNew(); go('home') }
  useShortcuts({ onNewChat: newChat, onSettings: () => setView('settings') })

  const composer = (big) => (
    <Composer big={big} busy={chats.busy} autoFocus onSend={(t) => { setView('home'); chats.send(t) }} onStop={chats.stop}
      models={info?.models || FALLBACK_MODELS} model={settings.model} onModel={(m) => setSettings({ model: m })} onDocs={setDocs} />
  )

  const pages = {
    search: () => <SearchPage chats={chats.chats} onOpen={(id) => { chats.setCurrentId(id); go('home') }} />,
    images: () => <ImagesPage onOpen={setLightbox} onCreated={refreshRecent} />,
    videos: () => <VideosPage onOpen={setLightbox} />,
    docs: () => <DocumentsPage docs={docs} setDocs={setDocs} settings={settings} setSettings={setSettings} />,
    settings: () => <SettingsPage settings={settings} setSettings={setSettings} info={info} onClearChats={chats.clearAll} />,
    usage: () => <UsagePage chats={chats.chats} docs={docs} />,
    profile: () => (profile ? <ProfilePage profile={profile} setProfile={setProfile} /> : null),
    help: () => <HelpPage />,
    home: () => (chats.chat?.messages.length
      ? <ChatPage chat={chats.chat} busy={chats.busy} status={chats.status} composer={composer(false)} onOpenImage={setLightbox}
          actions={{
            onPin: () => chats.togglePin(chats.currentId), onRename: (t) => chats.rename(chats.currentId, t),
            onArchive: () => chats.archive(chats.currentId), onDelete: () => chats.remove(chats.currentId),
          }} />
      : <HomePage composer={composer(true)} info={info} model={settings.model} recent={recent}
          onViewImages={() => setView('images')} onOpenImage={setLightbox} />),
  }
  const showTopLogin = !profile && view === 'home' && !chats.chat?.messages.length

  return (
    <div className="app">
      <Sidebar open={sidebarOpen} onToggle={() => setSidebarOpen(false)} view={view}
        chats={chats.chats} currentId={chats.currentId} profile={profile}
        onNav={(v) => { if (v === 'home') chats.setCurrentId(null); go(v) }}
        onNew={newChat} onOpen={(id) => { chats.setCurrentId(id); go('home') }} onDelete={chats.remove}
        onLogin={() => setLoginOpen(true)} onLogout={() => { setProfile(null); if (view === 'profile') setView('home') }} />
      <main className="main">
        {!sidebarOpen && (
          <button className="icon-btn open-side" onClick={() => setSidebarOpen(true)} title="Open sidebar" aria-label="Open sidebar">
            <Icon name="sidebar" />
          </button>
        )}
        {showTopLogin && <button className="top-login" onClick={() => setLoginOpen(true)}><Icon name="login" size={16} />Log in</button>}
        {(pages[view] || pages.home)()}
      </main>
      <Lightbox item={lightbox} onClose={() => setLightbox(null)} />
      {loginOpen && (
        <LoginModal googleClientId={info?.google_client_id} dark={dark} onClose={() => setLoginOpen(false)}
          onLogin={(p) => { setProfile(p); setLoginOpen(false) }} />
      )}
    </div>
  )
}
