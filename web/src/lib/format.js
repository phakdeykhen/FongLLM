export const formatDate = (iso) =>
  new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

// "Just now", "12m ago", "3h ago", "Yesterday", then "Nov 2".
export const timeAgo = (iso) => {
  const d = new Date(iso)
  const s = (Date.now() - d.getTime()) / 1000
  if (s < 60) return 'Just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  if (s < 172800) return 'Yesterday'
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6)

export const chatTitle = (text) => (text.length > 40 ? text.slice(0, 40) + '…' : text)
