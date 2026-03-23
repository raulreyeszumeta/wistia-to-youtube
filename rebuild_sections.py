"""
Rebuild YouTube channel homepage sections in the desired playlist order.
Deletes existing sections, then creates new ones in order.
"""

import sys
import time
import logging
from youtube_client import YouTubeClient
from googleapiclient.errors import HttpError
from config import LOG_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "rebuild_sections.log"), mode="a"),
    ],
)
logger = logging.getLogger("rebuild_sections")

# Desired homepage section order (top to bottom).
# Find your playlist IDs in YouTube Studio or via: python3 agent.py --list-projects
# Format: [("YOUTUBE_PLAYLIST_ID", "Section Title"), ...]
SECTIONS = [
    # ("PLxxxxxxxxxxxxxxxxxxxx", "Your Show Title"),
    # ("PLyyyyyyyyyyyyyyyyyyyy", "Another Series"),
]


def list_sections(yt):
    """List all existing channel sections."""
    resp = yt.youtube.channelSections().list(
        part="snippet,contentDetails", mine=True
    ).execute()
    return resp.get("items", [])


def delete_section(yt, section_id):
    """Delete a channel section by ID."""
    yt.youtube.channelSections().delete(id=section_id).execute()
    logger.info(f"  Deleted section {section_id}")


def create_section(yt, playlist_id, title, position):
    """Create a single-playlist channel section at the given position."""
    body = {
        "snippet": {
            "type": "singlePlaylist",
            "position": position,
            "title": title,
        },
        "contentDetails": {
            "playlists": [playlist_id],
        },
    }
    resp = yt.youtube.channelSections().insert(
        part="snippet,contentDetails", body=body
    ).execute()
    section_id = resp["id"]
    logger.info(f"  [{position}] Created: {title} → {section_id}")
    return section_id


def main():
    yt = YouTubeClient()
    channel_info = yt.verify_channel()
    logger.info(f"Rebuilding homepage sections for @{channel_info['handle']}\n")

    # Step 1: List and delete existing sections
    existing = list_sections(yt)
    logger.info(f"Found {len(existing)} existing sections")
    for section in existing:
        sid = section["id"]
        stype = section["snippet"].get("type", "?")
        stitle = section["snippet"].get("title", section["snippet"].get("defaultLanguage", ""))
        logger.info(f"  Existing: {stitle or stype} ({sid})")
        try:
            delete_section(yt, sid)
            time.sleep(0.5)
        except HttpError as e:
            logger.error(f"  Failed to delete {sid}: {e}")

    logger.info(f"\nCreating {len(SECTIONS)} new sections...")

    # Step 2: Create sections in order
    for position, (playlist_id, title) in enumerate(SECTIONS):
        try:
            create_section(yt, playlist_id, title, position)
            time.sleep(0.5)
        except HttpError as e:
            logger.error(f"  Failed to create '{title}': {e}")
            if "quotaExceeded" in str(e):
                logger.error("Quota exceeded — stopping. Resume tomorrow.")
                logger.error(f"  Completed {position}/{len(SECTIONS)} sections.")
                break

    # Step 3: Verify
    logger.info("\nVerifying final sections:")
    final = list_sections(yt)
    for s in sorted(final, key=lambda x: x["snippet"].get("position", 99)):
        pos = s["snippet"].get("position", "?")
        title = s["snippet"].get("title", "?")
        logger.info(f"  [{pos}] {title}")

    logger.info(f"\nDone — {len(final)} sections on homepage.")


if __name__ == "__main__":
    main()
