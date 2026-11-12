import Icon from '@/components/ui/Icon.jsx'
import ProfileMenu from '@/components/layout/ProfileMenu.jsx'
import { isMac } from '@/lib/constants.js'

const NAV = [
  { id: 'search', label: 'Search', icon: 'search' },
  { id: 'home', label: 'Home', icon: 'home' },
  { id: 'images', label: 'Images', icon: 'image' },
  { id: 'videos', label: 'Videos', icon: 'video' },
  { id: 'docs', label: 'Documents', icon: 'folder' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
]

export default function Sidebar({ open, onToggle, view, chats, currentId, profile, onLogin, onLogout, onNav, onNew, onOpen, onDelete }) {
  const visible = chats.filter((c) => c.messages.length && !c.archived).sort((a, b) => b.updated - a.updated)
  const pinned = visible.filter((c) => c.pinned)
  const recents = visible.filter((c) => !c.pinned)
  const row = (c) => (
    <div key={c.id} className={`recent ${view === 'home' && c.id === currentId ? 'active' : ''}`}>
      <button className="recent-open" onClick={() => onOpen(c.id)} title={c.title}>{c.title}</button>
      <button className="recent-del" onClick={() => onDelete(c.id)} title="Delete chat" aria-label={`Delete ${c.title}`}>
        <Icon name="trash" size={15} />
      </button>
    </div>
  )
  return (
    <aside className={`sidebar ${open ? '' : 'closed'}`}>
      <div className="side-top">
        <span className="brand">Fong <span className="brand-ai">AI</span></span>
        <button className="icon-btn" onClick={onToggle} title="Close sidebar" aria-label="Close sidebar">
          <Icon name="sidebar" />
        </button>
      </div>
      <nav className="side-nav">
        <button className="side-item new" onClick={onNew}><Icon name="newchat" />New chat<kbd className="side-kbd">{isMac ? '⌘ K' : 'Ctrl K'}</kbd></button>
        {NAV.map((n) => (
          <button key={n.id} className={`side-item ${view === n.id && !(n.id === 'home' && currentId && chats.find((c) => c.id === currentId)?.messages.length) ? 'active' : ''}`}
            onClick={() => onNav(n.id)}>
            <Icon name={n.icon} />{n.label}
          </button>
        ))}
      </nav>
      <div className="side-recents">
        {pinned.length > 0 && <div className="side-label">Pinned</div>}
        {pinned.map(row)}
        {recents.length > 0 && <div className="side-label">Recents</div>}
        {recents.map(row)}
      </div>
      <div className="side-foot">
        {profile ? <ProfileMenu profile={profile} onNav={onNav} onLogout={onLogout} /> : (
          <button className="side-login" onClick={onLogin}>
            <span className="avatar guest"><Icon name="user" size={16} /></span>
            <span><b>Guest</b><small>Log in to save your name</small></span>
            <Icon name="login" size={16} />
          </button>
        )}
      </div>
    </aside>
  )
}
