// Page <-> URL: "/" home, "/chat/<id>" an open chat, "/images", "/documents", ... so a refresh or a shared link
// lands on the same place, and the browser's Back / Forward buttons work.
const PATHS = { search: 'search', images: 'images', videos: 'videos', docs: 'documents', settings: 'settings',
  usage: 'usage', profile: 'profile', help: 'help' }
const VIEWS = Object.fromEntries(Object.entries(PATHS).map(([v, p]) => [p, v]))

export function pathFor(view, chatId) {
  if (view === 'home') return chatId ? `/chat/${chatId}` : '/'
  return `/${PATHS[view] || ''}`
}

export function parsePath(path = window.location.pathname) {
  const m = path.match(/^\/chat\/([\w-]+)\/?$/)
  if (m) return { view: 'home', chatId: m[1] }
  return { view: VIEWS[path.replace(/^\/|\/$/g, '')] || 'home', chatId: null }
}
