import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TRADERNET_API_KEY = os.getenv("TRADERNET_API_KEY")
TRADERNET_SECRET_KEY = os.getenv("TRADERNET_SECRET_KEY")
STORAGE_FILE = "users_data.json"