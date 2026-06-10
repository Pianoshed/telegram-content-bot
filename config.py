import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@your_channel")
RSS_URL = os.environ.get("RSS_URL", "https://9janetmovies.com.ng/rss")
POST_INTERVAL = int(os.environ.get("POST_INTERVAL") or 3600)
POSTS_PER_CYCLE = int(os.environ.get("POSTS_PER_CYCLE") or 5)
DATABASE_PATH = os.environ.get("DATABASE_PATH", "bot.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret")