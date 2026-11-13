// App-wide constants.

export const DEFAULT_SETTINGS = { model: 'fong4', temperature: 0.7, max_new: 512, use_tools: true, image_hd: false, top_k: 3, theme: 'system', voice_lang: 'auto' }

// Shown until /api/info answers; the server's list wins.
export const FALLBACK_MODELS = [
  { id: 'fong4', name: 'FongAI 4', detail: 'Our own model · creates images and videos' },
  { id: 'mistral', name: 'FongAI 3.4', detail: 'Smart and fast · creates images and videos' },
  { id: 'fongai', name: 'FongAI 3.2', detail: 'Tiny 64M model trained here · mostly Chinese' },
]

export const AVATAR_COLORS = ['#1f5cff', '#6d5dfc', '#0ea5e9', '#14b8a6', '#f97316', '#e11d48']

export const THEMES = [
  { id: 'system', icon: 'monitor', label: 'System' },
  { id: 'light', icon: 'sun', label: 'Light' },
  { id: 'dark', icon: 'moon', label: 'Dark' },
]

// Image styles: the card picture is a sample made with the same image model (public/styles/<id>.jpg).
export const IMAGE_STYLES = [
  { id: 'anime', label: 'Anime', suffix: 'anime style, vibrant colors, clean line art, studio quality' },
  { id: 'watercolor', label: 'Watercolor', suffix: 'soft watercolor painting, paper texture, gentle colors' },
  { id: 'photo', label: 'Photo', suffix: 'professional photograph, natural light, sharp focus, 50mm' },
  { id: '3d', label: '3D avatar', suffix: 'cute 3D render, pixar style, soft lighting, glossy' },
  { id: 'sketch', label: 'Sketch', suffix: 'pencil sketch, hand drawn, black ink on white paper' },
  { id: 'sticker', label: 'Sticker', suffix: 'die-cut sticker, bold outline, flat colors, white border' },
  { id: 'oil', label: 'Oil painting', suffix: 'impressionist oil painting, thick brush strokes' },
  { id: 'pixel', label: 'Pixel art', suffix: '16-bit pixel art, retro video game style' },
  { id: 'cyber', label: 'Neon city', suffix: 'cyberpunk, neon lights, rainy night, cinematic' },
  { id: 'khmer', label: 'Khmer temple', suffix: 'ancient Khmer temple, Angkor style stone carvings, golden sunrise' },
]

export const SERVER_CMD = 'uvicorn server.api:app --port 8000'
export const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)
