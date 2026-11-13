// Google from the browser: sign-in script, and saving FongAI's spreadsheets as real Google Sheets.
// The access token stays in this tab's memory. It never goes to the FongAI server.

let clientId = null   // set from /api/info (the server's GOOGLE_CLIENT_ID)
const tokens = {}     // scope -> { value, expires }: each Google app asks for its own permission the first time

export function setGoogleClientId(id) {
  clientId = id || null
  if (clientId) loadGoogleScript().catch(() => {})   // ready before the first click, so Google's popup isn't blocked
}
export function googleReady() { return !!clientId }

export function loadGoogleScript() {
  if (window.google?.accounts) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.onload = resolve
    s.onerror = () => reject(new Error("Couldn't load Google. Check your internet connection."))
    document.head.appendChild(s)
  })
}

// drive.file: FongAI sees and changes only the files it creates itself, nothing else in your Drive.
// (Gmail, Calendar and Maps need no permission at all: FongAI opens them already filled in. See googleLinks below.)
export const SCOPES = { drive: 'https://www.googleapis.com/auth/drive.file' }

async function accessToken(scope = SCOPES.drive) {
  const token = tokens[scope]
  if (token && token.expires > Date.now() + 60_000) return token.value
  if (!clientId) throw new Error('Google isn\'t connected yet. Start the server with GOOGLE_CLIENT_ID set (see Settings → Help).')
  await loadGoogleScript()
  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope,
      include_granted_scopes: true,
      callback: (r) => {
        if (r.error || !r.access_token) return reject(new Error(r.error_description || 'Google permission was not given.'))
        if (!window.google.accounts.oauth2.hasGrantedAllScopes(r, scope)) return reject(new Error('Please tick the permission box in the Google window, then try again.'))
        tokens[scope] = { value: r.access_token, expires: Date.now() + (r.expires_in || 3600) * 1000 }
        resolve(r.access_token)
      },
      error_callback: (e) => reject(new Error(e?.type === 'popup_closed' ? 'The Google window was closed.' : 'Google permission was not given.')),
    })
    client.requestAccessToken()
  })
}

// What each FongAI file becomes in Google Drive (Drive converts Office files into Google's own apps).
export const GOOGLE_APP = {
  xlsx: { name: 'Google Sheets', mime: 'application/vnd.google-apps.spreadsheet' },
  docx: { name: 'Google Docs', mime: 'application/vnd.google-apps.document' },
  pptx: { name: 'Google Slides', mime: 'application/vnd.google-apps.presentation' },
}

// A FongAI file -> your Google Drive (as Sheets / Docs / Slides when it can). Returns the link that opens it.
export async function saveToGoogle(item) {
  const t = await accessToken(SCOPES.drive)   // first: Google's permission popup must open straight from the click
  const file = await fetch(item.url)
  if (!file.ok) throw new Error('That file is gone. Ask FongAI to make it again.')
  const blob = await file.blob()
  const app = GOOGLE_APP[item.kind]
  const meta = { name: app ? item.title : item.name, ...(app && { mimeType: app.mime }) }
  const b = `fongai${Date.now()}`
  const body = new Blob([
    `--${b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(meta)}\r\n`,
    `--${b}\r\nContent-Type: ${blob.type || 'application/octet-stream'}\r\n\r\n`, blob, `\r\n--${b}--`,
  ])
  const res = await fetch('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink', {
    method: 'POST', headers: { Authorization: `Bearer ${t}`, 'Content-Type': `multipart/related; boundary=${b}` }, body,
  })
  return (await check(res, 'drive', 'Google Drive API')).webViewLink
}

async function check(res, key, api) {
  const data = await res.json().catch(() => ({}))
  if (res.status === 401) delete tokens[SCOPES[key]]   // expired: the next click asks again
  if (!res.ok) {
    const msg = data.error?.message || `Google error ${res.status}`
    if (/has not been used|is disabled/i.test(msg)) throw new Error(`Turn on the ${api} in your Google Cloud project, then try again.`)
    if (res.status === 403 && /scope|permission/i.test(msg)) throw new Error(`Add the ${key} permission on your Google Cloud consent screen, then try again.`)
    throw new Error(msg)
  }
  return data
}

// Day one, no Google sign-in in FongAI: open Gmail / Calendar / Maps already filled in. The user presses Send or Save.
const q = (o) => Object.entries(o).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')

export function gmailComposeUrl({ to, subject, body }) {
  return `https://mail.google.com/mail/?view=cm&fs=1&${q({ to, su: subject, body })}`
}

export function calendarUrl({ title, date, start, end, location, description, meet }) {
  const d = date.replaceAll('-', '')
  const next = (x) => { const t = new Date(`${x}T00:00:00Z`); t.setUTCDate(t.getUTCDate() + 1); return t.toISOString().slice(0, 10).replaceAll('-', '') }
  const dates = start && end
    ? `${d}T${start.replace(':', '')}00/${end <= start ? next(date) : d}T${end.replace(':', '')}00`
    : `${d}/${next(date)}`
  const details = [description, meet && 'Video call: click "Add Google Meet video conferencing" before saving.'].filter(Boolean).join('\n\n')
  return `https://calendar.google.com/calendar/render?action=TEMPLATE&${q({
    text: title, dates, ctz: Intl.DateTimeFormat().resolvedOptions().timeZone, details, location })}`
}
