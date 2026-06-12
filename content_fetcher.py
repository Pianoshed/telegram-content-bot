import feedparser
import re
import requests
from config import RSS_URL, POSTS_PER_CYCLE, TMDB_API_KEY


def fetch_posts(rss_url: str = None, limit: int = None) -> list[dict]:
    url = rss_url or RSS_URL
    count = limit or POSTS_PER_CYCLE

    feed = feedparser.parse(url)
    posts = []

    for entry in feed.entries[:count]:
        image = None

        # Standard media fields (likely empty for this feed)
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            image = entry.media_thumbnail[0].get("url")
        elif hasattr(entry, "media_content") and entry.media_content:
            image = entry.media_content[0].get("url")
        elif hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                if "image" in enc.get("type", ""):
                    image = enc.get("href") or enc.get("url")
                    break

        # Fallback 1: <img> embedded in description/summary
        raw_html = entry.get("summary", "")
        if not image and raw_html:
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html)
            if img_match:
                image = img_match.group(1)

        title = entry.get("title", "No title")

        # Fallback 2: query TMDB for a poster using the title
        if not image:
            image = _tmdb_poster(title)

        summary = _strip_html(raw_html)[:300].strip()

        posts.append(
            {
                "title": title,
                "content": summary,
                "link": entry.get("link", ""),
                "image": image,
                "tags": [t.term for t in entry.get("tags", [])],
            }
        )

    return posts


def _tmdb_poster(title: str) -> str | None:
    """Search TMDB by title and return a poster URL if found."""
    if not TMDB_API_KEY:
        return None

    # Strip trailing year/extra info like "(2026)" and "Download" for a cleaner search query
    clean_title = re.sub(r"\(\d{4}\)", "", title)
    clean_title = re.sub(r"\bDownload\b", "", clean_title, flags=re.IGNORECASE).strip()

    try:
        resp = requests.get(
            "https://api.themoviedb.org/3/search/movie",
            params={"api_key": TMDB_API_KEY, "query": clean_title},
            timeout=10,
        )
        data = resp.json()
        results = data.get("results", [])
        if results and results[0].get("poster_path"):
            return f"https://image.tmdb.org/t/p/w500{results[0]['poster_path']}"
    except requests.RequestException:
        pass

    return None


def _strip_html(text: str) -> str:
    clean = re.compile(r"<[^>]+>")
    return re.sub(clean, "", text)