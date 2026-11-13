import Icon from '@/components/ui/Icon.jsx'
import { THEMES } from '@/lib/constants.js'

export default function SettingsPage({ settings, setSettings, info, onClearChats }) {
  return (
    <div className="page">
      <h1 className="page-title">Settings</h1>
      <div className="setting-row">
        <span>Theme</span>
        <div className="seg" role="radiogroup" aria-label="Theme">
          {THEMES.map((t) => (
            <button key={t.id} role="radio" aria-checked={settings.theme === t.id} title={t.label} aria-label={t.label}
              className={settings.theme === t.id ? 'on' : ''} onClick={() => setSettings({ theme: t.id })}>
              <Icon name={t.icon} size={16} />
            </button>
          ))}
        </div>
      </div>
      {info && !info.ollama && (
        <p className="msg-error">FongAI 3.4 isn't available. To start its engine, run <code>brew services start ollama && ollama pull {info.ollama_model}</code></p>
      )}
      <label className="field check">
        <input type="checkbox" checked={settings.use_tools} onChange={(e) => setSettings({ use_tools: e.target.checked })} />
        <span>Let the model create images and videos when you ask for them</span>
      </label>
      <label className="field check">
        <input type="checkbox" checked={!!settings.image_hd} onChange={(e) => setSettings({ image_hd: e.target.checked })} />
        <span>HD images (FLUX, 1024px): much better pictures, but each one takes a few minutes. Off = Fast (about 5 s, 512px).</span>
      </label>
      <label className="field">
        <span>Temperature <b>{settings.temperature.toFixed(2)}</b></span>
        <input type="range" min="0" max="1.5" step="0.05" value={settings.temperature} onChange={(e) => setSettings({ temperature: +e.target.value })} />
      </label>
      <label className="field">
        <span>Max answer tokens <b>{settings.max_new}</b></span>
        <input type="range" min="64" max="2048" step="64" value={settings.max_new} onChange={(e) => setSettings({ max_new: +e.target.value })} />
      </label>
      <p className="muted">Commands: <code>/image prompt</code> (about 5 s) · <code>/video prompt</code> (minutes). Khmer is translated automatically. Device: {info?.device || '…'}</p>
      <button className="danger" onClick={onClearChats}><Icon name="trash" size={16} /> Delete all chats</button>
    </div>
  )
}
