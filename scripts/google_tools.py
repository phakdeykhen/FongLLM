"""
Google actions FongAI prepares in chat: a Gmail draft, a Calendar event (optionally with a Meet link), a Maps link.
The server only writes the content. The browser shows it as a card the user checks and edits, and only the
browser talks to Google, with the user's own permission. Nothing is sent or added without a click.
"""
import datetime
import json
import re
from urllib.parse import quote_plus

import requests

GMAIL_ASK = re.compile(r"\b(e-?mails?|gmail|mail (to|for))\b|អ៊ីមែល|邮件", re.I)
CAL_ASK = re.compile(r"\b(calendar|schedule|remind(er)? me|meeting|appointment|event|book (a|an|the)|google meet|meet link)\b|"
                     r"ប្រតិទិន|ណាត់|日历|会议", re.I)
MAPS_ASK = re.compile(r"\b(directions?|route|how (do i|to) get|navigate|on (the )?map|google maps?|where is|near ?by|"
                      r"near me|nearest|closest)\b|ផែនទី|地图", re.I)
DO = re.compile(r"\b(write|draft|compose|send|make|create|prepare|add|put|set( up)?|schedule|book|plan|remind|"
                r"show|find|open|get|give me|need|want)\b|បង្កើត|ធ្វើ|សរសេរ", re.I)
NOT_ACTION = re.compile(r"^\s*(how (do|can|to|should)|what('s| is| are)|why|explain)\b", re.I)


def detect(text):
    """'write an email to my boss' -> 'gmail'; 'meeting with Dara Friday 3pm' -> 'calendar'; None otherwise."""
    if NOT_ACTION.search(text) and not MAPS_ASK.search(text):
        return None
    if GMAIL_ASK.search(text) and DO.search(text):
        return "gmail"
    if CAL_ASK.search(text) and (DO.search(text) or re.search(r"\b\d{1,2}(:\d\d)?\s*(am|pm)\b|\btomorrow\b", text, re.I)):
        return "calendar"
    if MAPS_ASK.search(text):
        return "maps"
    return None


PROMPTS = {
    "gmail": """Write the email the user asks for. Reply with JSON only:
{{"to": "email address if the user gave one, else empty", "subject": "short subject", "body": "the full email text, with greeting and sign-off, plain text"}}
Write it in the language the user wrote in. Don't invent email addresses.""",
    "calendar": """Today is {today} ({weekday}). Turn the user's request into a calendar event. Reply with JSON only:
{{"title": "short event title", "date": "YYYY-MM-DD", "start": "HH:MM (24h)", "end": "HH:MM (24h)",
  "all_day": false, "location": "", "description": "", "meet": false}}
Rules: work out the real date from words like tomorrow / Friday / next week. If no time is given, use all_day true.
If no end time, end = start + 1 hour. meet = true only if they ask for a video call / Google Meet / online meeting.""",
    "maps": """The user wants a place or directions on Google Maps. Reply with JSON only:
{{"mode": "search or directions", "query": "the place to search for (for search)", "origin": "start (for directions; empty = my location)",
  "destination": "end (for directions)"}}""",
}


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def spoken_date(text, today=None):
    """'tomorrow' / 'friday' / 'next monday' / 'in 3 days' -> a real date. The chat model gets these wrong."""
    today = today or datetime.date.today()
    t = text.lower()
    if re.search(r"\bday after tomorrow\b", t):
        return today + datetime.timedelta(days=2)
    if re.search(r"\btomorrow\b|\btmr\b|ថ្ងៃស្អែក|明天", t):
        return today + datetime.timedelta(days=1)
    if re.search(r"\btoday\b|\btonight\b|ថ្ងៃនេះ|今天", t):
        return today
    m = re.search(r"\bin (\d+) days?\b", t)
    if m:
        return today + datetime.timedelta(days=int(m.group(1)))
    if re.search(r"\bnext week\b", t) and not re.search("|".join(DAYS), t):
        return today + datetime.timedelta(days=7)
    m = re.search(r"\b(next |this |on )?(" + "|".join(DAYS) + r")\b", t)
    if m:
        ahead = (DAYS.index(m.group(2)) - today.weekday()) % 7   # the coming one
        if ahead == 0 and (m.group(1) or "").strip() != "this":
            ahead = 7   # "friday" said on a Friday = next week's
        return today + datetime.timedelta(days=ahead)
    return None


def _json(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def prepare(kind, ask, history, ollama_url, model):
    """Ask the chat model for the action's fields. Returns the card the browser shows."""
    today = datetime.date.today()
    system = PROMPTS[kind].format(today=today.isoformat(), weekday=today.strftime("%A"))
    msgs = [{"role": "system", "content": system}] + list(history[-4:]) + [{"role": "user", "content": ask}]
    r = requests.post(f"{ollama_url}/api/chat", timeout=300, json={
        "model": model, "messages": msgs, "stream": False, "format": "json", "options": {"temperature": 0.3}})
    r.raise_for_status()
    data = _json(r.json().get("message", {}).get("content", ""))
    if kind == "gmail":
        to = str(data.get("to") or "")
        return {"service": "gmail", "to": to if "@" in to else "", "subject": str(data.get("subject") or ""),
                "body": str(data.get("body") or "")}
    if kind == "calendar":
        said = spoken_date(ask, today)
        date = said.isoformat() if said else str(data.get("date") or today.isoformat())
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", date):
            date = today.isoformat()
        start, end = str(data.get("start") or ""), str(data.get("end") or "")
        timed = re.fullmatch(r"\d\d?:\d\d", start) and not data.get("all_day")
        if timed and not re.fullmatch(r"\d\d?:\d\d", end):
            h, m = map(int, start.split(":"))
            end = f"{min(h + 1, 23):02d}:{m:02d}"
        return {"service": "calendar", "title": str(data.get("title") or ask[:60]), "date": date,
                "start": start.zfill(5) if timed else "", "end": end.zfill(5) if timed else "",
                "location": str(data.get("location") or ""), "description": str(data.get("description") or ""),
                "meet": bool(data.get("meet"))}
    return maps_card(data, ask)


def maps_card(data, ask):
    """A Google Maps link: no API key or permission needed."""
    if data.get("mode") == "directions" and data.get("destination"):
        url = "https://www.google.com/maps/dir/?api=1&destination=" + quote_plus(str(data["destination"]))
        if data.get("origin"):
            url += "&origin=" + quote_plus(str(data["origin"]))
        label = f"Directions to {data['destination']}" + (f" from {data['origin']}" if data.get("origin") else "")
    else:
        q = str(data.get("query") or ask)
        url = "https://www.google.com/maps/search/?api=1&query=" + quote_plus(q)
        label = q
    return {"service": "maps", "label": label, "url": url}


INTRO = {
    "gmail": "Here's your email. Change anything you like, then click **Open in Gmail**: it opens ready to send.",
    "calendar": "Here's the event. Check the date and time, then click **Add to Google Calendar** and Save.",
    "maps": "Here it is on Google Maps:",
}
