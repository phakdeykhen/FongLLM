import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'

import { isMac } from '@/lib/constants.js'

// Bottom-of-sidebar profile button with a Claude-style popover menu.
export default function ProfileMenu({ profile, onNav, onLogout }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', esc)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('keydown', esc) }
  }, [open])

  const go = (view) => { setOpen(false); onNav(view) }
  const initial = (profile.name || '?').trim().charAt(0).toUpperCase()

  return (
    <div className="profile" ref={ref}>
      {open && (
        <div className="profile-menu" role="menu">
          <div className="pm-head">{profile.email || profile.name}</div>
          <button role="menuitem" className="pm-item" onClick={() => go('settings')}>
            <Icon name="settings" size={17} />Settings<kbd>{isMac ? '⇧⌘,' : 'Ctrl+Shift+,'}</kbd>
          </button>
          <button role="menuitem" className="pm-item" onClick={() => go('usage')}><Icon name="usage" size={17} />Usage</button>
          <button role="menuitem" className="pm-item" onClick={() => go('profile')}><Icon name="user" size={17} />Edit profile</button>
          <button role="menuitem" className="pm-item" onClick={() => go('help')}><Icon name="help" size={17} />Get help</button>
          <div className="pm-sep" />
          <button role="menuitem" className="pm-item" onClick={() => go('docs')}><Icon name="folder" size={17} />Documents</button>
          <button role="menuitem" className="pm-item" onClick={() => go('images')}><Icon name="image" size={17} />My images</button>
          <div className="pm-sep" />
          <button role="menuitem" className="pm-item" onClick={() => { setOpen(false); onLogout() }}><Icon name="logout" size={17} />Log out</button>
        </div>
      )}
      <button className={`profile-btn ${open ? 'open' : ''}`} onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}>
        {profile.picture
          ? <img className="avatar" src={profile.picture} alt="" referrerPolicy="no-referrer" />
          : <span className="avatar" style={{ background: profile.color }}>{initial}</span>}
        <span className="profile-name">{profile.name}</span>
        <span className="profile-plan">· {profile.plan || 'Guest'}</span>
        <Icon name="chevron" size={14} className={open ? 'flip' : ''} />
      </button>
    </div>
  )
}
