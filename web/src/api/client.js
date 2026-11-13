// Thin client for the FastAPI backend (server/api.py).

async function json(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try { msg = (await res.json()).detail || msg } catch { /* not JSON */ }
    throw new Error(msg)
  }
  return res.json()
}

export const getInfo = () => fetch('/api/info').then(json)
export const listMedia = (kind) => fetch(`/api/media${kind ? `?kind=${kind}` : ''}`).then(json).then((d) => d.items)
export const listDocuments = () => fetch('/api/documents').then(json)
export const deleteDocument = (name) => fetch(`/api/documents/${encodeURIComponent(name)}`, { method: 'DELETE' }).then(json)

export function uploadDocuments(files) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return fetch('/api/documents', { method: 'POST', body: form }).then(json)
}

export function transcribe(blob, name = 'voice.wav') {
  const form = new FormData()
  form.append('file', blob, name)
  return fetch('/api/transcribe', { method: 'POST', body: form }).then(json).then((d) => d.text)
}

// Streams /api/chat. Calls onEvent for each NDJSON event until the stream ends or `signal` aborts.
export async function streamChat(body, onEvent, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  return fetch('/api/image', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, hd }) }).then(json)
}
