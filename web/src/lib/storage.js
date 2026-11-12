// localStorage helpers that never throw (private windows and full storage just fall back).
const PREFIX = 'fongai.'

export function load(key, fallback) {
  try { return JSON.parse(localStorage.getItem(PREFIX + key)) ?? fallback } catch { return fallback }
}

export function save(key, value) {
  try { localStorage.setItem(PREFIX + key, JSON.stringify(value)) } catch { /* storage full or blocked */ }
}
