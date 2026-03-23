"""
One-time re-authentication to add YouTube Analytics scope.
Run this interactively — it will open a browser for consent.
"""
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

PROJECT_DIR = Path(__file__).parent
TOKEN_FILE = PROJECT_DIR / "data" / "youtube_token.json"
CLIENT_SECRETS = PROJECT_DIR / "client_secrets.json"

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
creds = flow.run_local_server(
    port=8090,
    open_browser=True,
    prompt="consent",

)

with open(TOKEN_FILE, "w") as f:
    f.write(creds.to_json())

print(f"Token saved with scopes: {creds.scopes}")
print("You can now run youtube_report.py")
