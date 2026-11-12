import { useEffect, useState } from 'react'

// Resolves "system" | "light" | "dark" to a boolean and sets <html data-theme>.
export default function useTheme(theme) {
  const query = typeof window !== 'undefined' ? window.matchMedia?.('(prefers-color-scheme: dark)') : null
  const [systemDark, setSystemDark] = useState(() => !!query?.matches)

  useEffect(() => {
    if (!query) return
    const onChange = (e) => setSystemDark(e.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [query])

  const dark = theme === 'dark' || (theme === 'system' && systemDark)
  useEffect(() => { document.documentElement.dataset.theme = dark ? 'dark' : 'light' }, [dark])
  return dark
}
