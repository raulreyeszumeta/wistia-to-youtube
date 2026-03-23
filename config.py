"""
Configuration and constants for the Wistia-to-YouTube agent.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
WISTIA_API_TOKEN = os.getenv("WISTIA_API_TOKEN", "")
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Mode ---
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# --- Paths ---
PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
MEMORY_DB = DATA_DIR / "memory.db"
YOUTUBE_TOKEN_FILE = DATA_DIR / "youtube_token.json"
YOUTUBE_CLIENT_SECRETS_FILE = PROJECT_DIR / "client_secrets.json"
LOG_DIR = PROJECT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
TEMP_DIR = PROJECT_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# --- Company / SEO Context ---
COMPANY = os.getenv("COMPANY_NAME", "Your Company")
WEBSITE = os.getenv("COMPANY_WEBSITE", "https://yourcompany.com")
LOCATION = os.getenv("COMPANY_LOCATION", "")
FOCUS = os.getenv("COMPANY_FOCUS", "video content, industry interviews, business insights")
PLAYLIST_SUFFIX = os.getenv("PLAYLIST_SUFFIX", "")

# --- YouTube Channel ---
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE", "")
YOUTUBE_BRAND_CHANNEL_ID = os.getenv("YOUTUBE_BRAND_CHANNEL_ID", "")

# --- YouTube Defaults ---
YOUTUBE_CATEGORY_EDUCATION = "27"
YOUTUBE_CATEGORY_SCIENCE_TECH = "28"
YOUTUBE_CATEGORY_PEOPLE_BLOGS = "22"
DEFAULT_YOUTUBE_CATEGORY = YOUTUBE_CATEGORY_EDUCATION
DEFAULT_PRIVACY = "public"

# --- Rate Limits ---
WISTIA_RATE_LIMIT_DELAY = 0.5  # seconds between Wistia API calls
YOUTUBE_UPLOAD_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB chunks for resumable upload

# --- Retry ---
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # exponential backoff multiplier
