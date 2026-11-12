import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { googleLogin } from '@/api/client.js'

import { AVATAR_COLORS as COLORS } from '@/lib/constants.js'

function loadGoogleScript() {
  if (window.google?.accounts?.id) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.onload = resolve
    s.onerror = () => reject(new Error('Couldn\'t load Google sign-in. Check your internet connection.'))
    document.head.appendChild(s)
  })
}

const GoogleG = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
    <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
    <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
  </svg>
)

// Optional sign-in window (Kimi-style): logo artwork on the left, Google or guest on the right.
export default function LoginModal({ googleClientId, dark, onLogin, onClose }) {
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const gbtn = useRef(null)

  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  useEffect(() => {
    if (!googleClientId) return
    let alive = true
    loadGoogleScript().then(() => {
      if (!alive || !gbtn.current) return
      window.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: async ({ credential }) => {
          setBusy(true); setError('')
          try {
            const p = await googleLogin(credential)
            onLogin({ ...p, plan: 'Google', color: COLORS[0], since: Date.now() })
          } catch (e) { setError(e.message) }
          setBusy(false)
        },
      })
      window.google.accounts.id.renderButton(gbtn.current, {
        theme: dark ? 'filled_black' : 'outline', size: 'large', shape: 'pill', text: 'continue_with', width: 320, logo_alignment: 'center',
      })
    }).catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [googleClientId, dark, onLogin])

  function guest(e) {
    e.preventDefault()
    const n = name.trim()
    if (!n) return
    onLogin({ name: n, email: '', plan: 'Guest', color: COLORS[n.length % COLORS.length], since: Date.now() })
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="login-modal" role="dialog" aria-modal="true" aria-label="Log in to Fong AI">
        <div className="login-art"><img src="/login-art.jpg" alt="Fong AI · your friendly language model" /></div>
        <div className="login-pane">
          <button className="icon-btn login-close" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
          <h2 className="login-word">Fong <span className="brand-ai">AI</span></h2>
          <p className="login-lead">Log in to keep your name and picture on your chats. It's optional.</p>

          {googleClientId ? (
            <div className="gbtn-wrap"><div ref={gbtn} /></div>
          ) : (
            <button className="oauth-btn" disabled title="Google sign-in isn't set up on this server">
              <GoogleG /> Continue with Google
            </button>
          )}
          {!googleClientId && <p className="login-hint">To turn on Google sign-in, start the server with <code>GOOGLE_CLIENT_ID</code> set.</p>}
          {busy && <p className="login-hint">Signing you in…</p>}
          {error && <p className="msg-error">{error}</p>}

          <div className="or"><span>OR</span></div>

          <form className="guest-form" onSubmit={guest}>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" maxLength={40} aria-label="Your name" />
            <button className="login-btn" disabled={!name.trim()}>Continue as guest</button>
          </form>
          <button className="link skip" onClick={onClose}>Skip for now</button>
          <p className="login-note">Your chats are saved in this browser. Google only tells Fong AI your name, email and picture.</p>
        </div>
      </div>
    </div>
  )
}
