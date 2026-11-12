import { useState } from 'react'
import { AVATAR_COLORS } from '@/lib/constants.js'

export default function ProfilePage({ profile, setProfile }) {
  const [p, setP] = useState(profile)
  const [saved, setSaved] = useState(false)
  return (
    <div className="page">
      <h1 className="page-title">Profile</h1>
      <div className="profile-card">
        {p.picture
          ? <img className="avatar big" src={p.picture} alt="" referrerPolicy="no-referrer" />
          : <span className="avatar big" style={{ background: p.color }}>{(p.name || '?').charAt(0).toUpperCase()}</span>}
        <div><b>{p.name || 'Your name'}</b><small>{p.email || 'No email'} · {p.plan || 'Guest'}</small></div>
      </div>
      <label className="field"><span>Name</span><input className="text-in" value={p.name} maxLength={40} onChange={(e) => setP({ ...p, name: e.target.value })} /></label>
      <label className="field"><span>Email</span><input className="text-in" type="email" value={p.email || ''} onChange={(e) => setP({ ...p, email: e.target.value })} /></label>
      <div className="field"><span>Avatar color</span>
        <div className="swatches">
          {AVATAR_COLORS.map((c) => <button key={c} className={`swatch ${p.color === c ? 'on' : ''}`} style={{ background: c }} aria-label={`Color ${c}`} onClick={() => setP({ ...p, color: c })} />)}
        </div>
      </div>
      <button className="login-btn inline" disabled={!p.name.trim()} onClick={() => { setProfile({ ...p, name: p.name.trim() }); setSaved(true); setTimeout(() => setSaved(false), 1500) }}>
        {saved ? 'Saved' : 'Save profile'}
      </button>
    </div>
  )
}
