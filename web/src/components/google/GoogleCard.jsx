import { useState } from 'react'
import Icon from '@/components/ui/Icon.jsx'
import { calendarUrl, gmailComposeUrl } from '@/lib/google.js'

// What FongAI prepared for Gmail / Calendar / Maps. Everything is editable; nothing happens until you click.
// The button opens Google already filled in, in the user's own account: no sign-in to FongAI needed.
export default function GoogleCard({ item }) {
  const [v, setV] = useState(item)
  const set = (k) => (e) => setV({ ...v, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const open = (url) => window.open(url, '_blank', 'noopener')

  if (item.service === 'maps') {
    return (
      <div className="gcard">
        <div className="gcard-head"><span className="gcard-app maps">Google Maps</span></div>
        <div className="gcard-maps">{item.label}</div>
        <button className="gcard-go" onClick={() => open(item.url)}><Icon name="external" size={15} />Open in Google Maps</button>
      </div>
    )
  }

  if (item.service === 'gmail') {
    return (
      <div className="gcard">
        <div className="gcard-head"><span className="gcard-app gmail">Gmail</span></div>
        <label className="gfield"><span>To</span><input type="email" value={v.to} onChange={set('to')} placeholder="name@example.com" /></label>
        <label className="gfield"><span>Subject</span><input value={v.subject} onChange={set('subject')} /></label>
        <textarea className="gbody" rows={Math.min(14, Math.max(5, v.body.split('\n').length + 1))} value={v.body}
          onChange={set('body')} aria-label="Email text" />
        <button className="gcard-go" onClick={() => open(gmailComposeUrl(v))}>
          <Icon name="external" size={15} />Open in Gmail
        </button>
        <span className="gcard-note">Gmail opens with this email ready. Check it, then press Send there.</span>
      </div>
    )
  }

  const allDay = !v.start
  return (
    <div className="gcard">
      <div className="gcard-head"><span className="gcard-app calendar">Google Calendar</span></div>
      <label className="gfield"><span>Event</span><input value={v.title} onChange={set('title')} /></label>
      <div className="grow-fields">
        <label className="gfield"><span>Date</span><input type="date" value={v.date} onChange={set('date')} /></label>
        <label className="gfield"><span>Start</span>
          <input type="time" value={v.start} onChange={(e) => setV({ ...v, start: e.target.value, end: v.end || e.target.value })} /></label>
        <label className="gfield"><span>End</span><input type="time" value={v.end} onChange={set('end')} disabled={allDay} /></label>
      </div>
      <label className="gfield"><span>Where</span><input value={v.location} onChange={set('location')} placeholder="Optional" /></label>
      <label className="gcheck"><input type="checkbox" checked={v.meet} onChange={set('meet')} />Video call (Google Meet)</label>
      <button className="gcard-go" onClick={() => open(calendarUrl(v))} disabled={!v.title || !v.date}>
        <Icon name="external" size={15} />Add to Google Calendar
      </button>
      <span className="gcard-note">
        {allDay ? 'All-day event. ' : ''}Calendar opens with this filled in. Click Save there
        {v.meet ? ' (and "Add Google Meet video conferencing" for the call link)' : ''}.
      </span>
    </div>
  )
}
