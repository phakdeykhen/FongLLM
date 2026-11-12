// App icons come from Lucide (lucide-react). Components ask for icons by these short names.
import {
  Archive, ArrowRight, ArrowUp, Check, ChevronDown, CircleHelp, CircleUser, Clapperboard, Copy, File, FileText, FolderOpen, House, Image, LogIn,
  LogOut, MessageCirclePlus, Mic, Monitor, Moon, PanelLeft, Pencil, Pin, PieChart, Play, Plus, RotateCw, Search, Share, SlidersHorizontal, Sparkles, Square, Sun,
  Trash2, X,
} from 'lucide-react'

const ICONS = {
  newchat: MessageCirclePlus,
  plus: Plus,
  search: Search,
  home: House,
  image: Image,
  video: Clapperboard,
  folder: FolderOpen,
  settings: SlidersHorizontal,
  mic: Mic,
  arrowUp: ArrowUp,
  arrowRight: ArrowRight,
  play: Play,
  stop: Square,
  chevron: ChevronDown,
  sidebar: PanelLeft,
  copy: Copy,
  check: Check,
  trash: Trash2,
  file: File,
  x: X,
  doc: FileText,
  usage: PieChart,
  user: CircleUser,
  help: CircleHelp,
  logout: LogOut,
  login: LogIn,
  monitor: Monitor,
  sun: Sun,
  moon: Moon,
  sparkles: Sparkles,
  pin: Pin,
  rename: Pencil,
  share: Share,
  archive: Archive,
  retry: RotateCw,
}

export default function Icon({ name, size = 18, className = '' }) {
  const C = ICONS[name] || Square
  return <C className={`icon ${className}`} size={size} strokeWidth={1.75} aria-hidden="true" />
}
