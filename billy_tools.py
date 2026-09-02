"""Billy's tools — the "personal assistant" half of the fish.

Three capabilities, kept deliberately small and fast because Billy is a
voice agent: long tool calls mean a fish staring at you in silence.

    get_weather         Open-Meteo current conditions + today's forecast.
                        No API key. Location from BILLY_LATITUDE /
                        BILLY_LONGITUDE (defaults to Seattle).

    get_news_headlines  Top headlines from RSS feeds. Feeds from
                        BILLY_NEWS_FEEDS (comma-separated URLs),
                        defaults to BBC and NPR.

    use_google          Calendar and Gmail via the strands-google
                        community integration. Only enabled when
                        GOOGLE_OAUTH_CREDENTIALS is set — see README
                        for the one-time OAuth setup. Keep the scopes
                        read-only; Billy has no business sending email.
"""

import json
import os
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


def billy_tools() -> list:
    """All tools Billy should carry, based on what's configured."""
    tools = [get_weather, get_news_headlines]
    if os.environ.get("GOOGLE_OAUTH_CREDENTIALS"):
        from strands_google import use_google

        tools.append(use_google)
    return tools
