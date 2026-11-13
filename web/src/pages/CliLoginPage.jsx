import { useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { approveCli } from '@/api/client.js'

// /cli-login?code=ABCD-2345 — opened by `fong login`: the signed-in person connects their terminal to their account.
export default function CliLoginPage({ profile, onLogin }) {
  const code = new URLSearchParams(window.location.search).get('code') || ''
  const [state, setState] = useState('')   // '' | 'busy' | 'done' | error message
  const signedIn = !!profile?.token

  async function connect() {
    setState('busy')
    try { await approveCli(profile.token, code); setState('done') } catch (e) { setState(e.message) }
  }

  return (
    <div className="cli-login">
      <div className="cli-card">
        <span className="cli-icon"><Icon name="code" size={26} /></span>
        <h1>Connect FongAI CLI</h1>
        {state === 'done' ? (
          <>
            <p className="cli-lead">Your terminal is connected to <b>{profile.name}</b>. You can close this tab and go back to the terminal.</p>
            <span className="cli-ok"><Icon name="check" size={18} /> Connected</span>
          </>
        ) : !code ? (
          <p className="cli-lead">Open this page from your terminal: run <code>fong login</code>.</p>
        ) : (
          <>
            <p className="cli-lead">Check that your terminal shows this code:</p>
            <div className="cli-code" aria-label={`Code ${code}`}>{code}</div>
            {signedIn ? (
              <>
                <p className="cli-who">Signed in as <b>{profile.name}</b>{profile.email ? ` · ${profile.email}` : ''}</p>
                <button className="login-btn inline" onClick={connect} disabled={state === 'busy'}>
                  {state === 'busy' ? 'Connecting…' : 'Connect'}
                </button>
              </>
            ) : (
              <>
                <p className="cli-who">{profile ? 'Guests can’t use the CLI. ' : ''}Sign in to your FongAI account first.</p>
                <button className="login-btn inline" onClick={onLogin}>Sign in</button>
              </>
            )}
            {state && state !== 'busy' && <p className="msg-error" role="alert">{state}</p>}
            <p className="login-note">Only connect if you just ran <code>fong login</code> yourself. The terminal gets its own session, which you can end by running <code>fong logout</code>.</p>
          </>
        )}
      </div>
    </div>
  )
}
