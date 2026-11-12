import { MediaCard } from '@/components/media/Media.jsx'
import Icon from '@/components/ui/Icon.jsx'
import { SERVER_CMD } from '@/lib/constants.js'

// Empty-chat screen: greeting, composer, recent images.
export default function HomePage({ composer, info, model, recent, onViewImages, onOpenImage }) {
  return (
    <div className="home">
      <h1 className="hero">Coffee and <span className="brand-ai">Fong AI</span> time?</h1>
      <p className="hero-sub">Your friendly language model</p>
      {composer}
      {info?.error && <p className="msg-error center">Can't reach the Fong AI server. Start it with <code>{SERVER_CMD}</code></p>}
      {info && !info.error && !info.ollama && model === 'mistral' && (
        <p className="msg-warn center">FongAI 3.4 isn't available right now. Switch to FongAI 3.2, or see Settings to start it.</p>
      )}
      {recent.length > 0 && (
        <section className="recent-media">
          <div className="section-head"><span>Recent images <em className="count">{recent.length}</em></span><button className="chip-link" onClick={onViewImages}>View all <Icon name="arrowRight" size={15} /></button></div>
          <div className="mgrid">{recent.map((it) => <MediaCard key={it.url} item={it} onOpen={onOpenImage} />)}</div>
        </section>
      )}
    </div>
  )
}
