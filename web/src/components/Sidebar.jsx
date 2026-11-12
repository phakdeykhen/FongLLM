import Icon from './Icon.jsx'

const NAV = [
  { id: 'search', label: 'Search', icon: 'search' },
  { id: 'home', label: 'Home', icon: 'home' },
  { id: 'images', label: 'Images', icon: 'image' },
  { id: 'videos', label: 'Videos', icon: 'video' },
  { id: 'docs', label: 'Documents', icon: 'folder' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
]

export default function Sidebar({ open, onToggle, view, chats, currentId, device, onNav, onNew, onOpen, onDelete }) {
  const recents = chats.filter((c) => c.messages.length).sort((a, b) => b.updated - a.updated)
  return (
    <aside className={`sidebar ${open ? '' : 'closed'}`}>
      <div className="side-top">
        <span className="brand">FongAI</span>
        <button className="icon-btn" onClick={onToggle} title="Close sidebar" aria-label="Close sidebar">
          <Icon name="sidebar" />
        </button>
      </div>
      <nav className="side-nav">
        <button className="side-item new" onClick={onNew}><Icon name="plus" />New chat</button>
        {NAV.map((n) => (
          <button key={n.id} className={`side-item ${view === n.id && !(n.id === 'home' && currentId && chats.find((c) => c.id === currentId)?.messages.length) ? 'active' : ''}`}
            onClick={() => onNav(n.id)}>
            <Icon name={n.icon} />{n.label}
          </button>
        ))}
      </nav>
      {recents.length > 0 && <div className="side-label">Recents</div>}
      <div className="side-recents">
        {recents.map((c) => (
          <div key={c.id} className={`recent ${view === 'home' && c.id === currentId ? 'active' : ''}`}>
            <button className="recent-open" onClick={() => onOpen(c.id)} title={c.title}>{c.title}</button>
            <button className="recent-del" onClick={() => onDelete(c.id)} title="Delete chat" aria-label={`Delete ${c.title}`}>
              <Icon name="trash" size={15} />
            </button>
          </div>
        ))}
      </div>
      <div className="side-foot">FongAI · {device || '…'}</div>
    </aside>
  )
}
