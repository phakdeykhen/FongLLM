import { useEffect, useRef, useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { googleLogin, phoneSend, phoneVerify, signIn, signUp } from '@/api/client.js'
import { loadGoogleScript } from '@/lib/google.js'

import { AVATAR_COLORS as COLORS } from '@/lib/constants.js'


const GoogleG = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
    <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
    <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
  </svg>
)

// Sign-in methods shown in the window. Phone (SMS) and email are on hold: Google only for now.
const SHOW_PHONE = false
const SHOW_EMAIL = false

const COUNTRIES = [['+855', 'Cambodia'], ['+66', 'Thailand'], ['+84', 'Vietnam'], ['+856', 'Laos'], ['+86', 'China'], ['+65', 'Singapore'],
  ['+60', 'Malaysia'], ['+62', 'Indonesia'], ['+63', 'Philippines'], ['+81', 'Japan'], ['+82', 'Korea'], ['+886', 'Taiwan'],
  ['+852', 'Hong Kong'], ['+61', 'Australia'], ['+44', 'United Kingdom'], ['+1', 'US / Canada']]

// Sign-in window: artwork on the left; phone number + SMS code, Google, email and password, or guest on the right.
// onLogin(profile): the account from the server + its session token (or a guest name, no token).
export default function LoginModal({ googleClientId, dark, onLogin, onClose }) {
  const [mode, setMode] = useState(SHOW_PHONE ? 'phone' : SHOW_EMAIL ? 'signin' : 'google')   // 'google' | 'phone' | 'signin' | 'signup' | 'guest'
  const [form, setForm] = useState({ name: '', email: '', password: '', cc: '+855', phone: '', code: '' })
  const [agree, setAgree] = useState(false)
  const [wait, setWait] = useState(0)          // seconds before "Send code" works again
  const [testCode, setTestCode] = useState('') // test mode (no SMS service yet): the code is shown here
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const gbtn = useRef(null)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const account = ({ user, token }) => onLogin({ ...user, token,
    plan: { google: 'Google', phone: 'Phone', email: 'Account' }[user.provider] || 'Account',
    color: COLORS[(user.name || '').length % COLORS.length], since: (user.created || Date.now() / 1000) * 1000 })
  const fullPhone = `${form.cc} ${form.phone}`

  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  useEffect(() => {   // "Send code" countdown
    if (wait <= 0) return
    const t = setTimeout(() => setWait(wait - 1), 1000)
    return () => clearTimeout(t)
  }, [wait])

  useEffect(() => {
    if (!googleClientId || mode === 'guest') return
    let alive = true
    loadGoogleScript().then(() => {
      if (!alive || !gbtn.current) return
      window.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: async ({ credential }) => {
          setBusy(true); setError('')
          try { account(await googleLogin(credential)) } catch (e) { setError(e.message) }
          setBusy(false)
        },
      })
      window.google.accounts.id.renderButton(gbtn.current, {
        theme: dark ? 'filled_black' : 'outline', size: 'large', shape: 'pill', text: 'continue_with', width: 320, logo_alignment: 'center',
      })
    }).catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [googleClientId, dark, mode])   // eslint-disable-line react-hooks/exhaustive-deps

  async function sendCode() {
    setError(''); setTestCode('')
    try {
      const r = await phoneSend(fullPhone)
      setWait(60)
      if (r.test_code) setTestCode(r.test_code)
    } catch (e) { setError(e.message) }
  }

  async function submit(e) {
    e.preventDefault()
    if (!agree) { setError('Please agree to the Terms of Service and Privacy Policy first.'); return }
    setBusy(true); setError('')
    try {
      if (mode === 'phone') account(await phoneVerify(fullPhone, form.code))
      else account(mode === 'signup' ? await signUp(form.name, form.email, form.password) : await signIn(form.email, form.password))
    } catch (err) { setError(err.message) }
    setBusy(false)
  }

  function guest(e) {
    e.preventDefault()
    const n = form.name.trim()
    if (n) onLogin({ name: n, email: '', plan: 'Guest', color: COLORS[n.length % COLORS.length], since: Date.now() })
  }

  const go = (m) => { setMode(m); setError('') }
  const signup = mode === 'signup'
  const ready = mode === 'phone' ? form.phone.replace(/\D/g, '').length >= 6 && form.code.replace(/\D/g, '').length === 6
    : signup ? form.name.trim() && form.email.trim() && form.password.length >= 8 : form.email.trim() && form.password
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="login-modal" role="dialog" aria-modal="true" aria-label="Log in to Fong AI">
        <div className="login-art"><img src="/login-art.jpg" alt="Fong AI · your friendly language model" /></div>
        <div className="login-pane">
          <button className="icon-btn login-close" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
          <h2 className="login-word">Fong <span className="brand-ai">AI</span></h2>

          {mode === 'guest' ? (
            <>
              <p className="login-lead">Use Fong AI without an account. Your chats stay in this browser.</p>
              <form className="guest-form" onSubmit={guest}>
                <input id="guest-name" value={form.name} onChange={set('name')} placeholder="Your name" maxLength={40} aria-label="Your name" autoFocus />
                <button className="login-btn" disabled={!form.name.trim()}>Continue as guest</button>
              </form>
              <button className="link skip" onClick={() => go(SHOW_PHONE ? 'phone' : SHOW_EMAIL ? 'signin' : 'google')}>Back to log in</button>
            </>
          ) : (
            <>
              {mode === 'google' && <p className="login-lead">Sign in with your Google account to keep your name and picture on your chats.</p>}
              {mode !== 'google' && <>
              <form className="auth-form" onSubmit={submit}>
                {mode === 'phone' ? (
                  <>
                    <div className="auth-field phone-field">
                      <select id="auth-cc" value={form.cc} onChange={set('cc')} aria-label="Country code">
                        {COUNTRIES.map(([cc, name]) => <option key={cc} value={cc}>{cc} {name}</option>)}
                      </select>
                      <input id="auth-phone" type="tel" inputMode="tel" value={form.phone} onChange={set('phone')} placeholder="Phone number"
                        aria-label="Phone number" autoComplete="tel-national" />
                    </div>
                    <div className="auth-field code-field">
                      <input id="auth-code" inputMode="numeric" maxLength={6} value={form.code} onChange={set('code')} placeholder="Verification code"
                        aria-label="Verification code" autoComplete="one-time-code" />
                      <button type="button" className="send-code" onClick={sendCode} disabled={wait > 0 || form.phone.replace(/\D/g, '').length < 6}>
                        {wait > 0 ? `Resend in ${wait}s` : 'Send code'}
                      </button>
                    </div>
                    {testCode && <p className="login-hint test-code">Test mode (no SMS service set up yet): your code is <b>{testCode}</b></p>}
                  </>
                ) : (
                  <>
                    <div className="auth-tabs" role="tablist">
                      <button type="button" role="tab" aria-selected={!signup} className={!signup ? 'on' : ''} onClick={() => go('signin')}>Sign in</button>
                      <button type="button" role="tab" aria-selected={signup} className={signup ? 'on' : ''} onClick={() => go('signup')}>Sign up</button>
                    </div>
                    {signup && <input id="auth-name" className="auth-field" value={form.name} onChange={set('name')} placeholder="Your name" maxLength={40} aria-label="Your name" autoComplete="name" />}
                    <input id="auth-email" className="auth-field" type="email" value={form.email} onChange={set('email')} placeholder="Email" aria-label="Email" autoComplete="email" />
                    <input id="auth-password" className="auth-field" type="password" value={form.password} onChange={set('password')}
                      placeholder={signup ? 'Password (at least 8 characters)' : 'Password'} aria-label="Password" autoComplete={signup ? 'new-password' : 'current-password'} />
                  </>
                )}
                <button className="login-btn" disabled={!ready || busy}>{busy ? 'One moment…' : signup ? 'Create account' : 'Log in'}</button>
              </form>
              <div className="or"><span>OR</span></div>
              </>}
              {error && <p className="msg-error" role="alert">{error}</p>}
              {googleClientId ? (
                <div className="gbtn-wrap"><div ref={gbtn} /></div>
              ) : (
                <button className="oauth-btn" disabled title="Google sign-in isn't set up on this server"><GoogleG /> Continue with Google</button>
              )}
              <div className="auth-links">
                {mode === 'phone' && SHOW_EMAIL && <><button className="link" onClick={() => go('signin')}>Use email instead</button><span aria-hidden="true">·</span></>}
                {(mode === 'signin' || mode === 'signup') && SHOW_PHONE && <><button className="link" onClick={() => go('phone')}>Use phone number instead</button><span aria-hidden="true">·</span></>}
                <button className="link" onClick={() => go('guest')}>Continue as guest</button>
              </div>
              {mode === 'google' ? (
                <p className="login-note">By continuing, you agree to the Terms of Service and Privacy Policy. Google only shares your name, email and picture.</p>
              ) : (
                <label className="agree">
                  <input id="auth-agree" type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
                  <span>I agree to the Terms of Service and Privacy Policy</span>
                </label>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
