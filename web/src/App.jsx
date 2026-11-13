import { useCallback, useEffect, useState } from 'react'
import Sidebar from '@/components/layout/Sidebar.jsx'
import Composer from '@/components/chat/Composer.jsx'
import VoiceMode from '@/components/chat/VoiceMode.jsx'
import Icon from '@/components/ui/Icon.jsx'
import { Lightbox } from '@/components/media/Media.jsx'
import { FilePreview } from '@/components/files/Files.jsx'
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
import CliLoginPage from '@/pages/CliLoginPage.jsx'
import useLocalStorage from '@/hooks/useLocalStorage.js'
import useTheme from '@/hooks/useTheme.js'
import useShortcuts from '@/hooks/useShortcuts.js'
import useChats from '@/hooks/useChats.js'
import { authLogout, authMe, getInfo, listMedia } from '@/api/client.js'
import { DEFAULT_SETTINGS, FALLBACK_MODELS } from '@/lib/constants.js'
import { parsePath, pathFor } from '@/lib/route.js'
import { setGoogleClientId } from '@/lib/google.js'

const isNarrow = () => window.innerWidth <= 800

export default function App() {
  const [storedSettings, setStoredSettings] = useLocalStorage('settings', {})
  const settings = { ...DEFAULT_SETTINGS, ...storedSettings }
  const setSettings = useCallback((patch) => setStoredSettings((s) => ({ ...s, ...patch })), [setStoredSettings])
  const [profile, setProfile] = useLocalStorage('profile', null)   // null = guest; signing in is optional

  const [view, setView] = useState(() => parsePath().view)
  const [voice, setVoice] = useState(false)   // voice mode replaces the message box
  const [sidebarOpen, setSidebarOpen] = useState(() => !isNarrow())
  const [loginOpen, setLoginOpen] = useState(false)
  useEffect(() => {   // a saved session that expired or was signed out elsewhere: back to guest
    if (!profile?.token) return
    authMe(profile.token).then(({ user }) => setProfile((p) => (p ? { ...p, ...user } : p)))
      .catch((e) => { if (/not signed in/i.test(e.message)) setProfile(null) })
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  const [info, setInfo] = useState(null)
  const [docs, setDocs] = useState({ documents: [], passages: 0 })
  const [recent, setRecent] = useState([])
  const [lightbox, setLightbox] = useState(null)
  const [preview, setPreview] = useState(null)   // a made file (PDF, Excel, React, ...) shown in the right panel

  const refreshRecent = useCallback(() => listMedia('image').then((m) => setRecent(m.slice(0, 3))).catch(() => {}), [])
  const chats = useChats({ settings, onMedia: refreshRecent, onFile: setPreview })
  const dark = useTheme(settings.theme)

  // URL routing: open the chat named in the address on load, follow Back / Forward, and keep the address in step
  useEffect(() => {
    const { chatId } = parsePath()
    if (chatId) chats.setCurrentId(chatId)
    const onPop = () => { const r = parsePath(); setView(r.view); chats.setCurrentId(r.chatId); setPreview(null) }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  const chatGone = chats.currentId && !chats.chat   // e.g. /chat/<id> of a deleted chat
  useEffect(() => { if (chatGone && !chats.busy) chats.setCurrentId(null) }, [chatGone, chats.busy])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (chatGone) return
    const path = pathFor(view, chats.currentId)
    if (window.location.pathname !== path) window.history.pushState(null, '', path)
  }, [view, chats.currentId, chatGone])

  useEffect(() => {
    getInfo().then((i) => { setInfo(i); setGoogleClientId(i.google_client_id) }).catch(() => setInfo({ error: true }))
    refreshRecent()
  }, [refreshRecent])

  const go = (next) => { setView(next); if (isNarrow()) setSidebarOpen(false) }
  const newChat = () => { chats.startNew(); setPreview(null); go('home') }
  useShortcuts({ onNewChat: newChat, onSettings: () => setView('settings') })

  const composer = (big) => voice ? (
    <VoiceMode lang={settings.voice_lang} onClose={() => setVoice(false)}
      onSend={(t) => { setView('home'); return chats.send(t, undefined, [], false, true) }} />
  ) : (
    <Composer onVoice={() => setVoice(true)} big={big} busy={chats.busy} autoFocus onSend={(t, imgs, edit) => { setView('home'); chats.send(t, undefined, imgs, edit) }} onStop={chats.stop}
      models={info?.models || FALLBACK_MODELS} model={settings.model} onModel={(m) => setSettings({ model: m })} onDocs={setDocs}
      hd={settings.image_hd} onHd={(v) => setSettings({ image_hd: v })}
      voiceLang={settings.voice_lang} onVoiceLang={(v) => setSettings({ voice_lang: v })} />
  )

  const pages = {
    search: () => <SearchPage chats={chats.chats} onOpen={(id) => { chats.setCurrentId(id); go('home') }} />,
    images: () => <ImagesPage onOpen={setLightbox} onCreated={refreshRecent} hd={settings.image_hd} onHd={(v) => setSettings({ image_hd: v })} />,
    videos: () => <VideosPage onOpen={setLightbox} />,
    docs: () => <DocumentsPage docs={docs} setDocs={setDocs} settings={settings} setSettings={setSettings} />,
    settings: () => <SettingsPage settings={settings} setSettings={setSettings} info={info} onClearChats={chats.clearAll} />,
    usage: () => <UsagePage chats={chats.chats} docs={docs} />,
    profile: () => (profile ? <ProfilePage profile={profile} setProfile={setProfile} /> : null),
    help: () => <HelpPage />,
    cli: () => <CliLoginPage profile={profile} onLogin={() => setLoginOpen(true)} />,
    home: () => (chats.chat?.messages.length
      ? <ChatPage chat={chats.chat} busy={chats.busy && chats.busyId === chats.chat.id} status={chats.status} progress={chats.progress} composer={composer(false)} onOpenImage={setLightbox}
          onEdit={(text, i, imgs) => chats.send(text, i, imgs)} onOpenFile={setPreview} activeFile={preview}
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
        onNew={newChat} onOpen={(id) => { chats.setCurrentId(id); setPreview(null); go('home') }} onDelete={chats.remove}
        onLogin={() => setLoginOpen(true)} onLogout={() => { if (profile?.token) authLogout(profile.token); setProfile(null); if (view === 'profile') setView('home') }} />
      <main className="main">
        {!sidebarOpen && (
          <button className="icon-btn open-side" onClick={() => setSidebarOpen(true)} title="Open sidebar" aria-label="Open sidebar">
            <Icon name="sidebar" />
          </button>
        )}
        {showTopLogin && <button className="top-login" onClick={() => setLoginOpen(true)}><Icon name="login" size={16} />Log in</button>}
        {(pages[view] || pages.home)()}
      </main>
      {view === 'home' && chats.chat?.messages.length > 0 && <FilePreview item={preview} onClose={() => setPreview(null)} />}
      <Lightbox item={lightbox} onClose={() => setLightbox(null)} />
      {loginOpen && (
        <LoginModal googleClientId={info?.google_client_id} dark={dark} onClose={() => setLoginOpen(false)}
          onLogin={(p) => { setProfile(p); setLoginOpen(false) }} />
      )}
    </div>
  )
}
