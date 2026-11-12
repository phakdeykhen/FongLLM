import { useEffect, useState } from 'react'
import { load, save } from '@/lib/storage.js'

// useState that is saved to localStorage under "fongai.<key>".
export default function useLocalStorage(key, initial) {
  const [value, setValue] = useState(() => load(key, typeof initial === 'function' ? initial() : initial))
  useEffect(() => save(key, value), [key, value])
  return [value, setValue]
}
