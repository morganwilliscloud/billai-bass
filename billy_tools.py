"""Billy's tools — the "personal assistant" half of the fish.

Three capabilities, kept deliberately small and fast because Billy is a
voice agent: long tool calls mean a fish staring at you in silence.

    get_weather         Open-Meteo current conditions + today's forecast.
                        No API key. Location from BILLY_LATITUDE /
                        BILLY_LONGITUDE (defaults to Seattle).

    get_news_headlines  Top headlines from RSS feeds. Feeds from
                        BILLY_NEWS_FEEDS (comma-separated URLs),
                        defaults to BBC and NPR.

    check_calendar      Today's Google Calendar events.
    check_recent_email  Latest messages from the PRIMARY inbox tab only
                        (no promotions/social).

    Both Google tools call the API directly with a client that's built
    once and cached. (The generic use_google tool fetches Google's
    Discovery schema over HTTP on every call - several seconds of dead
    fish per question.) Enabled when either GOOGLE_OAUTH_CREDENTIALS
    (token file path) or BILLY_GOOGLE_SECRET_ID (AWS Secrets Manager
    secret holding the token, fetched into tmpfs at startup so it never
    touches the SD card) is set. See README and google_setup.py for the
    one-time OAuth setup. Scopes are read-only; Billy has no business
    sending email.
"""

import json
import os
import subprocess
import sys
import urllib.request

from strands import tool

WEATHER_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 77: "snow grains", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 85: "snow showers",
    86: "snow showers", 95: "thunderstorm", 96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}

DEFAULT_FEEDS = "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.npr.org/1001/rss.xml"


@tool
def get_weather() -> dict:
    """Get current weather and today's forecast for Billy's home location.

    Returns current temperature, conditions, today's high/low, and chance
    of precipitation.
    """
    lat = os.environ.get("BILLY_LATITUDE", "47.61")
    lon = os.environ.get("BILLY_LONGITUDE", "-122.33")
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph"
        "&timezone=auto&forecast_days=1"
    )
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.load(resp)

    current = data["current"]
    daily = data["daily"]
    return {
        "temperature_f": round(current["temperature_2m"]),
        "feels_like_f": round(current["apparent_temperature"]),
        "conditions": WEATHER_CODES.get(current["weather_code"], "unknown"),
        "wind_mph": round(current["wind_speed_10m"]),
        "today_high_f": round(daily["temperature_2m_max"][0]),
        "today_low_f": round(daily["temperature_2m_min"][0]),
        "chance_of_rain_pct": daily["precipitation_probability_max"][0],
    }


@tool
def get_news_headlines(limit: int = 6) -> dict:
    """Get the latest news headlines.

    Args:
        limit: Maximum number of headlines to return across all feeds.
    """
    import feedparser

    feeds = os.environ.get("BILLY_NEWS_FEEDS", DEFAULT_FEEDS).split(",")
    per_feed = max(1, limit // len(feeds))
    headlines = []
    for url in feeds:
        parsed = feedparser.parse(url.strip())
        source = parsed.feed.get("title", url.strip())
        for entry in parsed.entries[:per_feed]:
            headlines.append({"source": source, "headline": entry.title})
    return {"headlines": headlines[:limit]}


_song_proc: subprocess.Popen | None = None


def song_now_playing() -> bool:
    """True while Billy's song is playing. billy.py uses this to gate the
    mic (so the model doesn't hear the song) and to chomp the mouth."""
    return _song_proc is not None and _song_proc.poll() is None


@tool
def play_song() -> dict:
    """Play Billy's original song out loud. Use whenever someone asks Billy
    to sing, play his song, or perform."""
    global _song_proc
    song = os.environ.get("BILLY_SONG", "")
    if not song or not os.path.exists(os.path.expanduser(song)):
        return {"error": "no song configured - set BILLY_SONG to an audio file"}
    if song_now_playing():
        return {"status": "already singing"}
    player = "afplay" if sys.platform == "darwin" else "aplay"
    _song_proc = subprocess.Popen(
        [player, os.path.expanduser(song)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "status": "playing",
        "note": "The song is now playing out loud. Say one short hype line.",
    }


_google_services: dict = {}


def _google_service(name: str, version: str):
    """Build a Google API client once and cache it (Discovery is slow)."""
    key = (name, version)
    if key not in _google_services:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(
            os.environ["GOOGLE_OAUTH_CREDENTIALS"]
        )
        _google_services[key] = build(name, version, credentials=creds)
    return _google_services[key]


@tool
def check_calendar() -> dict:
    """Get today's events from the user's Google Calendar."""
    from datetime import datetime, time, timedelta

    now = datetime.now().astimezone()
    start = datetime.combine(now.date(), time.min).astimezone()
    end = start + timedelta(days=1)
    events = (
        _google_service("calendar", "v3")
        .events()
        .list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=15,
        )
        .execute()
    )
    return {
        "today": [
            {
                "title": e.get("summary", "(no title)"),
                "start": e["start"].get("dateTime", e["start"].get("date")),
            }
            for e in events.get("items", [])
        ]
    }


@tool
def check_recent_email(limit: int = 5) -> dict:
    """Get the latest emails from the user's primary inbox.

    Only the primary tab - never promotions or social.

    Args:
        limit: Maximum number of emails to return.
    """
    gmail = _google_service("gmail", "v1")
    listing = (
        gmail.users()
        .messages()
        .list(userId="me", q="category:primary", maxResults=limit)
        .execute()
    )
    emails = []
    for m in listing.get("messages", []):
        msg = (
            gmail.users()
            .messages()
            .get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        emails.append(
            {
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "snippet": msg.get("snippet", "")[:120],
                "unread": "UNREAD" in msg.get("labelIds", []),
            }
        )
    return {"primary_inbox": emails}


def _load_google_token_from_secrets() -> None:
    """Fetch the Google OAuth token from AWS Secrets Manager into tmpfs.

    Runs only when BILLY_GOOGLE_SECRET_ID is set and GOOGLE_OAUTH_CREDENTIALS
    isn't already pointing at a file. /dev/shm is RAM-backed, so the token
    exists only while the Pi is powered on.
    """
    import boto3

    secret_id = os.environ["BILLY_GOOGLE_SECRET_ID"]
    token = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    path = "/dev/shm/billy_google_token.json" if os.path.isdir("/dev/shm") else "/tmp/billy_google_token.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token["SecretString"])
    os.environ["GOOGLE_OAUTH_CREDENTIALS"] = path


def billy_tools() -> list:
    """All tools Billy should carry, based on what's configured."""
    tools = [get_weather, get_news_headlines]
    if os.environ.get("BILLY_SONG"):
        tools.append(play_song)
    if os.environ.get("BILLY_GOOGLE_SECRET_ID") and not os.environ.get("GOOGLE_OAUTH_CREDENTIALS"):
        _load_google_token_from_secrets()
    if os.environ.get("GOOGLE_OAUTH_CREDENTIALS"):
        tools.extend([check_calendar, check_recent_email])
        # The universal 200-API tool is off by default: it re-fetches
        # Google's Discovery schema every call (slow) and improvises its
        # own Gmail queries (reads your promotions tab). Opt back in if
        # you want Billy to reach APIs the focused tools don't cover.
        if os.environ.get("BILLY_UNIVERSAL_GOOGLE"):
            from strands_google import use_google

            tools.append(use_google)
    return tools
