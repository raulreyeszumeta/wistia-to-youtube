"""
Weekly YouTube Report — Mondays at 5am
Pulls analytics, runs Claude YouTube Strategist, pushes to Notion.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests
import anthropic
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- Setup ---
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "logs" / "weekly_report.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# --- Config ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
NOTION_REPORTS_DB = os.getenv("NOTION_REPORTS_DB", "")
NOTION_TASKS_DB = os.getenv("NOTION_TASKS_DB", "")

TOKEN_FILE = Path(__file__).parent / "data" / "youtube_token.json"
CLIENT_SECRETS = Path(__file__).parent / "client_secrets.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CHANNEL_ID = os.getenv("YOUTUBE_BRAND_CHANNEL_ID", "")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


# --- YouTube Auth ---

def get_youtube_credentials():
    """Load and refresh YouTube OAuth2 credentials."""
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE) as f:
            token_data = json.load(f)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing YouTube token...")
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "YouTube token expired and no refresh token. "
                "Run the main app interactively to re-authenticate."
            )
    return creds


# --- YouTube Analytics ---

def pull_analytics():
    """Pull weekly YouTube analytics."""
    creds = get_youtube_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    yt_analytics = build("youtubeAnalytics", "v2", credentials=creds)

    # Date range: last 7 days
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # --- Channel stats (current totals) ---
    channel_resp = youtube.channels().list(
        part="statistics,snippet", id=CHANNEL_ID
    ).execute()
    channel = channel_resp["items"][0]
    stats = channel["statistics"]

    total_subs = int(stats.get("subscriberCount", 0))
    total_videos = int(stats.get("videoCount", 0))
    total_views = int(stats.get("viewCount", 0))

    # --- Weekly analytics (views, watch time, subs gained/lost) ---
    try:
        analytics_resp = yt_analytics.reports().query(
            ids="channel==mine",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost",
            dimensions="day",
            sort="day",
        ).execute()

        rows = analytics_resp.get("rows", [])
        weekly_views = sum(r[1] for r in rows)
        weekly_watch_minutes = sum(r[2] for r in rows)
        weekly_subs_gained = sum(r[3] for r in rows)
        weekly_subs_lost = sum(r[4] for r in rows)
        weekly_watch_hours = round(weekly_watch_minutes / 60, 1)
        weekly_sub_growth = weekly_subs_gained - weekly_subs_lost
    except Exception as e:
        logger.warning(f"Analytics API failed (may need scope): {e}")
        weekly_views = 0
        weekly_watch_hours = 0
        weekly_sub_growth = 0
        weekly_subs_gained = 0
        weekly_subs_lost = 0

    # --- Top videos this week ---
    try:
        top_resp = yt_analytics.reports().query(
            ids="channel==mine",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="video",
            sort="-views",
            maxResults=5,
        ).execute()
        top_video_rows = top_resp.get("rows", [])
    except Exception as e:
        logger.warning(f"Top videos query failed: {e}")
        top_video_rows = []

    # Resolve video titles
    top_videos = []
    if top_video_rows:
        video_ids = [r[0] for r in top_video_rows]
        vid_resp = youtube.videos().list(
            part="snippet,statistics", id=",".join(video_ids)
        ).execute()
        vid_map = {v["id"]: v for v in vid_resp.get("items", [])}
        for row in top_video_rows:
            vid_id = row[0]
            vid = vid_map.get(vid_id, {})
            title = vid.get("snippet", {}).get("title", vid_id)
            views = row[1]
            top_videos.append({"title": title, "video_id": vid_id, "views": views})

    report = {
        "week_start": start_date,
        "week_end": end_date,
        "total_subscribers": total_subs,
        "total_videos": total_videos,
        "total_views": total_views,
        "weekly_views": weekly_views,
        "weekly_watch_hours": weekly_watch_hours,
        "weekly_sub_growth": weekly_sub_growth,
        "weekly_subs_gained": weekly_subs_gained,
        "weekly_subs_lost": weekly_subs_lost,
        "top_videos": top_videos,
    }

    logger.info(f"Analytics pulled: {weekly_views} views, {weekly_watch_hours}h watch time, {weekly_sub_growth:+d} subs")
    return report


# --- Claude YouTube Strategist Agent ---

_COMPANY = os.getenv("COMPANY_NAME", "Your Company")
_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE", "")
_FOCUS = os.getenv("COMPANY_FOCUS", "video content, industry interviews, business insights")
_CHANNEL_REF = f"@{_CHANNEL_HANDLE}" if _CHANNEL_HANDLE else _COMPANY

STRATEGIST_PROMPT = f"""You are a YouTube Growth Strategist for {_COMPANY} ({_CHANNEL_REF}). The channel focuses on: {_FOCUS}.

Your role: Analyze weekly performance data and generate 5-7 actionable tasks for the coming week. Each task must be specific, measurable, and tied to a data insight.

For each task, provide:
- task: Clear action item (under 80 chars)
- priority: High, Medium, or Low
- category: One of Content, SEO, Growth, Engagement, Optimization
- details: 2-3 sentences explaining what to do and expected impact
- source_insight: The specific data point that triggered this recommendation

Focus on:
- Content gaps and opportunities based on top-performing videos
- SEO improvements (titles, descriptions, tags, thumbnails)
- Audience growth tactics specific to B2B YouTube
- Engagement optimization (CTAs, end screens, cards, community posts)
- Upload schedule and consistency recommendations

Be specific to THIS channel's data. No generic advice. Every recommendation must connect to the numbers.

Respond in JSON format:
{
  "growth_summary": "2-3 sentence analysis of this week's performance and trends",
  "tasks": [
    {
      "task": "...",
      "priority": "High|Medium|Low",
      "category": "Content|SEO|Growth|Engagement|Optimization",
      "details": "...",
      "source_insight": "..."
    }
  ]
}"""


def run_strategist(report: dict) -> dict:
    """Run Claude YouTube Strategist agent on the weekly data."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    data_prompt = f"""Here is this week's YouTube analytics for {_CHANNEL_REF}:

**Period:** {report['week_start']} to {report['week_end']}

**Channel Totals:**
- Total Subscribers: {report['total_subscribers']:,}
- Total Videos: {report['total_videos']}
- Total Views (all time): {report['total_views']:,}

**This Week:**
- Views: {report['weekly_views']:,}
- Watch Time: {report['weekly_watch_hours']} hours
- Subscriber Growth: {report['weekly_sub_growth']:+d} (gained {report['weekly_subs_gained']}, lost {report['weekly_subs_lost']})

**Top Videos This Week:**
{chr(10).join(f"  {i+1}. {v['title']} — {v['views']} views" for i, v in enumerate(report['top_videos'])) if report['top_videos'] else "  No data available"}

Analyze this data and generate your weekly strategy tasks."""

    logger.info("Running YouTube Strategist agent...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=STRATEGIST_PROMPT,
        messages=[{"role": "user", "content": data_prompt}],
    )

    text = response.content[0].text
    # Extract JSON from response
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    result = json.loads(text.strip())
    logger.info(f"Strategist generated {len(result.get('tasks', []))} tasks")
    return result


# --- Notion Integration ---

def push_report_to_notion(report: dict, strategy: dict):
    """Create a Weekly YouTube Report page in Notion."""
    week_label = f"Week of {report['week_start']}"
    top_video = report["top_videos"][0] if report["top_videos"] else None

    properties = {
        "Week": {"title": [{"text": {"content": week_label}}]},
        "Date": {"date": {"start": report["week_start"], "end": report["week_end"]}},
        "Views": {"number": report["weekly_views"]},
        "Watch Time (hrs)": {"number": report["weekly_watch_hours"]},
        "Subscribers": {"number": report["total_subscribers"]},
        "Sub Growth": {"number": report["weekly_sub_growth"]},
        "Total Videos": {"number": report["total_videos"]},
        "Growth Summary": {
            "rich_text": [{"text": {"content": strategy.get("growth_summary", "")[:2000]}}]
        },
    }

    if top_video:
        properties["Top Video"] = {
            "rich_text": [{"text": {"content": top_video["title"][:2000]}}]
        }
        properties["Top Video Views"] = {"number": top_video["views"]}

    payload = {
        "parent": {"database_id": NOTION_REPORTS_DB},
        "properties": properties,
    }

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=NOTION_HEADERS,
        json=payload,
    )
    if resp.status_code == 200:
        logger.info(f"Report pushed to Notion: {week_label}")
    else:
        logger.error(f"Failed to push report: {resp.status_code} — {resp.text}")

    return resp.status_code == 200


def push_tasks_to_notion(tasks: list, week_start: str):
    """Create strategy tasks in Notion task board (all start in Backlog)."""
    created = 0
    for task in tasks:
        properties = {
            "Task": {"title": [{"text": {"content": task["task"][:2000]}}]},
            "Status": {"select": {"name": "Backlog"}},
            "Priority": {"select": {"name": task.get("priority", "Medium")}},
            "Category": {"select": {"name": task.get("category", "Content")}},
            "Week": {"date": {"start": week_start}},
            "Details": {
                "rich_text": [{"text": {"content": task.get("details", "")[:2000]}}]
            },
            "Source Insight": {
                "rich_text": [{"text": {"content": task.get("source_insight", "")[:2000]}}]
            },
        }

        payload = {
            "parent": {"database_id": NOTION_TASKS_DB},
            "properties": properties,
        }

        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json=payload,
        )
        if resp.status_code == 200:
            created += 1
        else:
            logger.error(f"Failed to create task '{task['task']}': {resp.status_code} — {resp.text}")

    logger.info(f"Created {created}/{len(tasks)} tasks in Notion (Backlog)")
    return created


# --- Main ---

def main():
    logger.info("=" * 60)
    logger.info("Weekly YouTube Report — Starting")
    logger.info("=" * 60)

    # 1. Pull YouTube analytics
    report = pull_analytics()

    # 2. Run Claude YouTube Strategist
    strategy = run_strategist(report)

    # 3. Push report to Notion
    push_report_to_notion(report, strategy)

    # 4. Push tasks to Notion (Backlog)
    tasks = strategy.get("tasks", [])
    push_tasks_to_notion(tasks, report["week_start"])

    logger.info("=" * 60)
    logger.info("Weekly report complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
