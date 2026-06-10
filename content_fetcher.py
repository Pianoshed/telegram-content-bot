import feedparser
from config import RSS_URL, POSTS_PER_CYCLE


def fetch_posts(rss_url: str = None, limit: int = None) -> list[dict]:
    url = rss_url or RSS_URL
    count = limit or POSTS_PER_CYCLE

    feed = feedparser.parse(url)
    posts = []

    for entry in feed.entries[:count]:
        # grab best available image
        image = None
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            image = entry.media_thumbnail[0].get("url")
        elif hasattr(entry, "media_content") and entry.media_content:
            image = entry.media_content[0].get("url")
        elif hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                if "image" in enc.get("type", ""):
                    image = enc.get("href") or enc.get("url")
                    break

        # strip html from summary
        summary = entry.get("summary", "")
        summary = _strip_html(summary)[:300].strip()

        posts.append(
            {
                "title": entry.get("title", "No title"),
                "content": summary,
                "link": entry.get("link", ""),
                "image": image,
                "tags": [t.term for t in entry.get("tags", [])],
            }
        )

    return posts


def _strip_html(text: str) -> str:
    import re
    clean = re.compile(r"<[^>]+>")
    return re.sub(clean, "", text)