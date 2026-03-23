"""
Organize YouTube channel: reverse playlist ordering, rename playlists,
update playlist descriptions with GEO optimization, fix missing items.
"""

import sys
import time
import logging
from youtube_client import YouTubeClient
from optimizer import Optimizer
from config import LOG_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "organize.log"), mode="a"),
    ],
)
logger = logging.getLogger("organize")

# Map your YouTube playlist IDs to their corrected titles.
# Find playlist IDs in YouTube Studio or via agent.py --list-projects.
# Format: { "YOUTUBE_PLAYLIST_ID": "New Playlist Title | Your Channel" }
PLAYLISTS = {
    # "PLxxxxxxxxxxxxxxxxxxxx": "Your Show Title | Your Channel",
}


def reverse_playlist(yt: YouTubeClient, playlist_id: str, playlist_name: str):
    """Reverse the order of videos in a playlist (currently newest-first, should be oldest-first)."""
    items = yt.get_playlist_items(playlist_id)
    total = len(items)
    logger.info(f"  Reversing {total} videos in '{playlist_name}'")

    # We need to move items from the end to the beginning
    # Strategy: move each item to its reversed position
    # Items are currently [Conclusion, ..., Intro]. We want [Intro, ..., Conclusion].
    # Move the last item to position 0, then the second-to-last to position 1, etc.

    reversed_items = list(reversed(items))
    for new_pos, item in enumerate(reversed_items):
        item_id = item["id"]
        video_id = item["snippet"]["resourceId"]["videoId"]
        title = item["snippet"]["title"]

        success = yt.reorder_playlist_item(item_id, playlist_id, video_id, new_pos)
        if success:
            logger.info(f"    [{new_pos}] {title}")
        else:
            logger.error(f"    FAILED to move: {title}")
        time.sleep(0.5)  # rate limit


def check_missing_videos(yt: YouTubeClient, playlist_id: str, playlist_name: str):
    """Check for videos that should be in this playlist but aren't."""
    from memory_store import MemoryStore
    memory = MemoryStore()

    # Find the wistia project for this playlist
    cur = memory.conn.execute(
        "SELECT wistia_project_id FROM playlists WHERE youtube_playlist_id = ?",
        (playlist_id,),
    )
    row = cur.fetchone()
    if not row:
        return []

    # Get all migrated videos for this project
    cur = memory.conn.execute(
        "SELECT youtube_video_id, title FROM migrated_videos WHERE wistia_project_id = ?",
        (row["wistia_project_id"],),
    )
    migrated = {r["youtube_video_id"]: r["title"] for r in cur.fetchall()}

    # Get videos currently in playlist
    items = yt.get_playlist_items(playlist_id)
    in_playlist = {item["snippet"]["resourceId"]["videoId"] for item in items}

    # Find missing
    missing = []
    for vid, title in migrated.items():
        if vid not in in_playlist:
            missing.append((vid, title))
            logger.warning(f"  Missing from playlist: {title} ({vid})")

    memory.close()
    return missing


def main():
    yt = YouTubeClient()
    channel_info = yt.verify_channel()
    logger.info(f"Organizing @{channel_info['handle']}\n")

    optimizer = Optimizer()

    for playlist_id, new_title in PLAYLISTS.items():
        series_name = new_title.split(" | ")[0]
        logger.info(f"\n{'='*60}")
        logger.info(f"Playlist: {series_name}")
        logger.info(f"{'='*60}")

        # 1. Update playlist title and GEO description
        description = optimizer.generate_playlist_description(series_name)
        yt.update_playlist(playlist_id, new_title, description)
        logger.info(f"  Title updated: {new_title}")

        # 2. Check for missing videos and add them
        missing = check_missing_videos(yt, playlist_id, series_name)
        for vid, title in missing:
            logger.info(f"  Adding missing video: {title}")
            yt.add_to_playlist(playlist_id, vid)
            time.sleep(0.5)

        # 3. Reverse playlist order (intro first, conclusion last)
        reverse_playlist(yt, playlist_id, series_name)

        time.sleep(1)

    logger.info(f"\n{'#'*60}")
    logger.info("CHANNEL ORGANIZATION COMPLETE")
    logger.info(f"{'#'*60}")


if __name__ == "__main__":
    main()
