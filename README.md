# Wistia → YouTube Migration Agent

Migrate your entire Wistia video library to YouTube with AI-powered SEO optimization. Each video gets a GEO (Generative Engine Optimization) description structured to be cited by AI engines like ChatGPT, Gemini, and Perplexity — while also maximizing YouTube search rankings.

## Features

- **Bulk migration** — fetch all videos from Wistia projects and upload to YouTube
- **AI-powered descriptions** — Claude generates 8-section GEO descriptions optimized for both YouTube SEO and AI engine discoverability
- **Resumable** — SQLite memory tracks every migrated video; re-running safely skips already-uploaded content
- **Playlist management** — auto-creates and manages YouTube playlists matching your Wistia projects
- **HD thumbnails** — pulls 1280x720 thumbnails from Wistia and sets them on YouTube
- **Weekly analytics reports** — pulls YouTube analytics, generates strategy tasks via Claude, pushes to Notion
- **Dry run mode** — preview everything before any uploads happen

## Prerequisites

- Python 3.9+
- A Wistia account with API access
- A YouTube channel with a Google Cloud project and OAuth2 credentials
- An Anthropic API key (for AI optimization — optional but recommended)
- A Notion account (optional — for weekly reports)

## Setup

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable | Description |
|----------|-------------|
| `WISTIA_API_TOKEN` | From https://app.wistia.com/account/api |
| `YOUTUBE_CLIENT_ID` | From Google Cloud Console OAuth2 credentials |
| `YOUTUBE_CLIENT_SECRET` | From Google Cloud Console OAuth2 credentials |
| `ANTHROPIC_API_KEY` | From https://console.anthropic.com |
| `NOTION_API_KEY` | Optional — for weekly reports |
| `NOTION_REPORTS_DB` | Optional — Notion database ID for reports |
| `NOTION_TASKS_DB` | Optional — Notion database ID for strategy tasks |
| `COMPANY_NAME` | Your company/channel name |
| `COMPANY_WEBSITE` | Your website URL |
| `COMPANY_LOCATION` | City, State (used in AI descriptions) |
| `COMPANY_FOCUS` | Brief description of your content focus |
| `PLAYLIST_SUFFIX` | Appended to playlist titles (e.g. `\| Your Channel`) |
| `YOUTUBE_CHANNEL_HANDLE` | Your YouTube handle (without @) |
| `YOUTUBE_BRAND_CHANNEL_ID` | Optional — your Brand Account channel ID |

### 3. Set up YouTube OAuth2

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **YouTube Data API v3** and **YouTube Analytics API**
3. Create **OAuth 2.0 Client ID** (Desktop app type)
4. Download the JSON file → save as `client_secrets.json` in the project root

On first run, a browser window will open for Google consent. The token is saved to `data/youtube_token.json` for future runs.

## Usage

### List your Wistia projects (find project IDs)

```bash
python3 agent.py --list-projects
```

### Dry run — preview without uploading

```bash
python3 agent.py PROJECT_ID_1 PROJECT_ID_2 --dry-run
```

### Live run — migrate to YouTube

```bash
python3 agent.py PROJECT_ID_1 PROJECT_ID_2 --live
```

### Re-optimize metadata for already-migrated videos

```bash
python3 update_metadata.py --dry-run        # preview
python3 update_metadata.py --limit 50       # update up to 50 videos (quota-safe)
```

### Re-upload HD thumbnails

```bash
python3 update_thumbnails.py --dry-run
python3 update_thumbnails.py --limit 50
```

### Organize channel homepage sections

Edit the `SECTIONS` list in `rebuild_sections.py` with your playlist IDs and titles, then:

```bash
python3 rebuild_sections.py
```

### Update metadata for YouTube-native videos (not from Wistia)

Copy `update_youtube_series.py` as a template. Edit `PLAYLIST_ID`, `SERIES_NAME`, the context block, and `FANS_FIRST_VIDEOS` for your series, then run it.

### Upload a curated "Best Of" playlist

Copy `upload_curated_playlist.py`, set `PLAYLIST_NAME` and fill in `EPISODES`, then run it.

### Upload a show playlist with a host

Copy `upload_show_example.py`, rename it, fill in the `SHOW_*` constants and `EPISODES` list, then run it.

### Weekly YouTube analytics report

```bash
python3 youtube_report.py
```

Or schedule via cron (Mondays at 5am):
```
0 5 * * 1 cd /path/to/wistia-to-youtube && bash run_weekly_report.sh
```

If your YouTube token needs the Analytics scope re-added:
```bash
python3 reauth_analytics.py
```

## Architecture

```
agent.py              Main orchestrator — fetch → optimize → upload → playlist → record
wistia_client.py      Wistia Data API wrapper
youtube_client.py     YouTube Data API v3 + OAuth2
optimizer.py          Claude-powered GEO (Generative Engine Optimization)
memory_store.py       SQLite persistence — migrated videos, playlists, trends cache
config.py             All configuration and env loading
youtube_report.py     Weekly analytics → Claude strategist → Notion
update_metadata.py    Re-optimize descriptions for already-migrated videos
update_thumbnails.py  Re-upload HD thumbnails from Wistia
organize_channel.py   Rename/reorder playlists, fix missing videos
rebuild_sections.py   Rebuild YouTube channel homepage sections
upload_show_example.py  Template for uploading a curated show playlist
reauth_analytics.py   One-time re-auth to add YouTube Analytics scope
```

## YouTube API Quota

The YouTube Data API has a default daily quota of 10,000 units. Key costs:

| Operation | Quota cost |
|-----------|-----------|
| `videos.insert` (upload) | 1,600 units |
| `videos.update` (metadata) | 50 units |
| `thumbnails.set` | 50 units |
| `playlists.insert` | 50 units |
| `search.list` | 100 units |

`update_metadata.py` and `update_thumbnails.py` default to a `--limit 100` safety cap. Use `--offset N` to resume after hitting the daily limit.

## Notes

- `data/` is gitignored — contains `memory.db` (migration history) and `youtube_token.json` (OAuth token)
- `client_secrets.json` is gitignored — never commit this
- `.env` is gitignored — never commit this
- All API keys should be in `.env`, never hardcoded
