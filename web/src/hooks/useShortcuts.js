import { useEffect, useRef } from 'react'

// Global keyboard shortcuts: ⌘K / Ctrl+K new chat, ⇧⌘, / Ctrl+Shift+, settings.
export default function useShortcuts({ onNewChat, onSettings }) {
  const handlers = useRef({ onNewChat, onSettings })
  handlers.current = { onNewChat, onSettings }

  useEffect(() => {
    const onKey = (e) => {
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.shiftKey && (e.key === ',' || e.key === '<')) { e.preventDefault(); handlers.current.onSettings?.() }
      else if (!e.shiftKey && e.key.toLowerCase() === 'k') { e.preventDefault(); handlers.current.onNewChat?.() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
