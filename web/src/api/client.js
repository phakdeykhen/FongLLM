// Thin client for the FastAPI backend (server/api.py).
import { load, save } from '@/lib/storage.js'

// Who is asking: the signed-in account's token, else a random id this browser keeps as a guest.
// The server uses it so each person only sees the images and videos they made.
function guestId() {
  let id = load('guest', null)
  if (!id) { id = (crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^A-Za-z0-9]/g, ''); save('guest', id) }
  return id
}
function who() {
  const token = load('profile', null)?.token
  return { 'X-Fong-Guest': guestId(), ...(token && { Authorization: `Bearer ${token}` }) }
}

async function json(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try { msg = (await res.json()).detail || msg } catch { /* not JSON */ }
    throw new Error(msg)
  }
  return res.json()
}

export const getInfo = () => fetch('/api/info').then(json)
export const listMedia = (kind) => fetch(`/api/media${kind ? `?kind=${kind}` : ''}`, { headers: who() }).then(json).then((d) => d.items)
export const listDocuments = () => fetch('/api/documents').then(json)
export const deleteDocument = (name) => fetch(`/api/documents/${encodeURIComponent(name)}`, { method: 'DELETE' }).then(json)

export function uploadDocuments(files) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return fetch('/api/documents', { method: 'POST', body: form }).then(json)
}

// Khmer text -> spoken WAV blob (voice mode).
export async function speakKhmer(text) {
  const res = await fetch('/api/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
  if (!res.ok) throw new Error(`speak failed (${res.status})`)
  return res.blob()
}

// language: 'auto' (any language) or 'km' (Khmer speech model)
export function transcribe(blob, name = 'voice.wav', language = 'auto') {
  const form = new FormData()
  form.append('file', blob, name)
  form.append('language', language)
  return fetch('/api/transcribe', { method: 'POST', body: form }).then(json).then((d) => d.text)
}

// Streams /api/chat. Calls onEvent for each NDJSON event until the stream ends or `signal` aborts.
export async function streamChat(body, onEvent, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...who() },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    await json(res)
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (line) onEvent(JSON.parse(line))
    }
  }
}

export function googleLogin(credential) {
  return fetch('/api/auth/google', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ credential }) }).then(json)
}

export function makeImage(prompt, hd = false) {
  return fetch('/api/image', { method: 'POST', headers: { 'Content-Type': 'application/json', ...who() }, body: JSON.stringify({ prompt, hd }) }).then(json)
}


// Accounts: sign up / sign in return {user, token}; the token goes in the Authorization header.
const postJson = (url, body, token) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token && { Authorization: `Bearer ${token}` }) },
  body: JSON.stringify(body || {}) }).then(json)
export const signUp = (name, email, password) => postJson('/api/auth/signup', { name, email, password })
export const signIn = (email, password) => postJson('/api/auth/login', { email, password })
export const authLogout = (token) => postJson('/api/auth/logout', {}, token).catch(() => {})
export const authMe = (token) => fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } }).then(json)
export const phoneSend = (phone) => postJson('/api/auth/phone/send', { phone })
export const phoneVerify = (phone, code) => postJson('/api/auth/phone/verify', { phone, code })
export const approveCli = (token, userCode) => postJson('/api/auth/device/approve', { user_code: userCode }, token)
export const makeTitle = (text, reply = '') => postJson('/api/title', { text, reply }).then((r) => r.title)
