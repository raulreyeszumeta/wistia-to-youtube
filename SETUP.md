# Wistia → YouTube Migration Agent — Setup Guide

## 1. Install Dependencies

```bash
cd ~/wistia-to-youtube
pip3 install -r requirements.txt
```

## 2. Wistia API Token

1. Go to: https://app.wistia.com/account/api
2. Generate a **Read-only** API token (or Read + Download if needed)
3. Copy it

## 3. YouTube Data API + OAuth2

### Enable API:
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select existing)
3. Enable **YouTube Data API v3**
4. Go to **APIs & Services → Credentials**

### Create OAuth Credentials:
1. Click **Create Credentials → OAuth 2.0 Client ID**
2. Application type: **Desktop app**
3. Download the JSON file
4. Save it as `client_secrets.json` in `~/wistia-to-youtube/`

### First Run Auth:
On first run, a browser window will open for Google OAuth consent.
After authorizing, the token is saved to `data/youtube_token.json`.

## 4. Anthropic API Key

1. Get from: https://console.anthropic.com/
2. Any active key with Messages API access works

## 5. Configure .env

```bash
cp .env.example .env
# Edit .env with your keys
```

## 6. Usage

### List all Wistia projects (find IDs):
```bash
python3 agent.py --list-projects
```

### Dry run (preview, no uploads):
```bash
python3 agent.py PROJECT_ID_1 PROJECT_ID_2 --dry-run
```

### Live run (actually upload to YouTube):
```bash
python3 agent.py PROJECT_ID_1 PROJECT_ID_2 --live
```

### Cron (weekly):
```bash
# Add to crontab -e:
0 6 * * 1 cd ~/wistia-to-youtube && python3 agent.py PROJECT_IDS --live >> logs/cron.log 2>&1
```

## Architecture

```
agent.py          → Main orchestrator + CLI
wistia_client.py  → Wistia Data API wrapper
youtube_client.py → YouTube Data API v3 + OAuth2
optimizer.py      → Claude-powered SEO optimization
memory_store.py   → SQLite persistence (migrated videos, playlists, trends)
config.py         → All configuration + env loading
```

## Memory / Resumability

- SQLite DB at `data/memory.db` tracks every migrated video
- Re-running the same projects safely skips already-uploaded videos
- Trends are cached for 24h to minimize API calls
- Run log tracks every execution for auditing
