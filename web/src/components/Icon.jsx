// Small stroke icon set (24px grid, 1.6px strokes) so the UI needs no icon library.
const PATHS = {
  plus: 'M12 5v14M5 12h14',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  home: 'M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z',
  image: 'M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15.5 8.5h.01',
  video: 'M4 6h12v12H4zM16 10l4-2v8l-4-2',
  folder: 'M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z',
  settings: 'M4 7h10M18 7h2M4 17h4M12 17h8M14 5v4M8 15v4',
  mic: 'M12 4a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V7a3 3 0 0 0-3-3zM6 11a6 6 0 0 0 12 0M12 17v3',
  arrowUp: 'M12 19V5M6 11l6-6 6 6',
  stop: 'M8 8h8v8H8z',
  chevron: 'M7 10l5 5 5-5',
  sidebar: 'M4 5h16v14H4zM9 5v14',
  copy: 'M9 9h10v10H9zM5 15V5h10',
  check: 'M5 12l4 4 10-10',
  trash: 'M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12',
  file: 'M7 3h7l5 5v13H7zM14 3v5h5',
  x: 'M6 6l12 12M18 6L6 18',
  doc: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
}

export default function Icon({ name, size = 18, className = '' }) {
  return (
    <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  )
}
