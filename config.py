import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@your_channel")
RSS_URL = os.environ.get("RSS_URL", "https://9janetmovies.com.ng/rss")
POST_INTERVAL = 3600
POSTS_PER_CYCLE = 5
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "bot.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret")