import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

_default_channels = "@naijanetmovies,@naijanetmovies1,@naijanetmovies2"
CHANNEL_USERNAMES = [
    c.strip() for c in os.environ.get("CHANNEL_USERNAMES", _default_channels).split(",") if c.strip()
]

RSS_URL = os.environ.get("RSS_URL", "https://9janetmovies.com.ng/rss")
POST_INTERVAL = 3600
POSTS_PER_CYCLE = 50
DATABASE_PATH = os.environ.get(
    "DATABASE_PATH", os.path.join(os.path.dirname(__file__), "bot.db")
)
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "my-key")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DAILY_POST_CAP = int(os.environ.get("DAILY_POST_CAP", 50))
REPOST_COOLDOWN_DAYS = int(os.environ.get("REPOST_COOLDOWN_DAYS", 14))