"""
Re-optimize and update metadata for already-migrated YouTube videos.
Uses the GEO (Generative Engine Optimization) template to generate descriptions
optimized for AI engine discoverability (ChatGPT, Gemini, Perplexity, Google AI Overviews).
"""

import sys
import time
import logging
import argparse
from config import DRY_RUN, LOG_DIR
from memory_store import MemoryStore
from wistia_client import WistiaClient
from youtube_client import YouTubeClient
from optimizer import Optimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "update_metadata.log"), mode="a"),
    ],
)
logger = logging.getLogger("update_metadata")

# YouTube API videos.update costs 50 quota units per call.
# Default daily quota is 10,000 units → ~200 updates/day max.
# Leave room for other operations (uploads, playlist ops).
QUOTA_SAFE_LIMIT = 100


def get_migrated_videos(memory: MemoryStore, project_ids: list = None) -> list:
    """Fetch all migrated videos from the DB, optionally filtered by project."""
    if project_ids:
        placeholders = ",".join("?" for _ in project_ids)
        query = f"""
            SELECT wistia_hashed_id, youtube_video_id, wistia_project_id, title, optimized_title
            FROM migrated_videos
            WHERE wistia_project_id IN ({placeholders})
            ORDER BY migrated_at
        """
        cur = memory.conn.execute(query, project_ids)
    else:
        cur = memory.conn.execute("""
            SELECT wistia_hashed_id, youtube_video_id, wistia_project_id, title, optimized_title
            FROM migrated_videos
            ORDER BY migrated_at
        """)
    return [dict(row) for row in cur.fetchall()]


def get_playlist_info(memory: MemoryStore, wistia_project_id: str) -> dict:
    """Look up playlist title and URL for a project."""
    cur = memory.conn.execute(
        "SELECT youtube_playlist_id, playlist_title FROM playlists WHERE wistia_project_id = ?",
        (wistia_project_id,),
    )
    row = cur.fetchone()
    if row:
        playlist_id = row["youtube_playlist_id"]
        title = row["playlist_title"]
        # Strip the playlist suffix to get the series name
        series_name = title.split(" | ")[0] if " | " in title else title
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        return {
            "series_name": series_name,
            "playlist_url": playlist_url,
        }
    return {"series_name": "", "playlist_url": ""}


def main():
    parser = argparse.ArgumentParser(
        description="Re-optimize YouTube metadata with GEO template for AI discoverability"
    )
    parser.add_argument(
        "projects",
        nargs="*",
        help="Wistia project IDs to update (default: all migrated videos)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without updating YouTube",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=QUOTA_SAFE_LIMIT,
        help=f"Max videos to update (default: {QUOTA_SAFE_LIMIT}, quota-safe)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N videos (for resuming after quota limit)",
    )
    args = parser.parse_args()

    memory = MemoryStore()
    wistia = WistiaClient()
    optimizer = Optimizer()

    videos = get_migrated_videos(memory, args.projects or None)
    logger.info(f"Found {len(videos)} migrated videos total")

    if args.offset:
        videos = videos[args.offset:]
        logger.info(f"Skipping first {args.offset}, {len(videos)} remaining")

    if not videos:
        logger.info("Nothing to update.")
        return

    if len(videos) > args.limit:
        logger.info(f"Limiting to {args.limit} videos (quota safety)")
        videos = videos[:args.limit]

    youtube = None
    if not args.dry_run:
        youtube = YouTubeClient()
        channel_info = youtube.verify_channel()
        logger.info(f"Updating videos on @{channel_info['handle']}")

    stats = {"updated": 0, "skipped": 0, "errors": 0}

    for idx, video in enumerate(videos):
        wistia_id = video["wistia_hashed_id"]
        yt_id = video["youtube_video_id"]
        original_title = video["title"]
        project_id = video["wistia_project_id"]

        logger.info(f"\n--- [{idx + 1}/{len(videos)}] {original_title} (YT: {yt_id}) ---")

        # Fetch original Wistia metadata for re-optimization
        try:
            wistia_media = wistia.get_media(wistia_id)
            original_desc = wistia_media.get("description", "")
            wistia_tags = [
                t.get("name", "") for t in wistia_media.get("tags", [])
            ] if wistia_media.get("tags") else []
        except Exception as e:
            logger.warning(f"Could not fetch Wistia data for {wistia_id}: {e}")
            original_desc = ""
            wistia_tags = []

        # Get playlist/series context
        playlist_info = get_playlist_info(memory, project_id)

        # Re-optimize with GEO template
        try:
            optimized = optimizer.optimize_video(
                original_title=original_title,
                original_description=original_desc,
                wistia_tags=wistia_tags,
                channel_name=playlist_info["series_name"],
                playlist_url=playlist_info["playlist_url"],
            )
        except Exception as e:
            logger.error(f"Optimization failed for {wistia_id}: {e}")
            stats["errors"] += 1
            continue

        new_title = optimized["title"]
        new_desc = optimized["description"]
        new_tags = optimized["tags"]

        word_count = len(new_desc.split())
        logger.info(f"  New title: {new_title}")
        logger.info(f"  Description: {len(new_desc)} chars, ~{word_count} words")
        logger.info(f"  Tags: {', '.join(new_tags[:5])}...")

        if args.dry_run:
            logger.info(f"  [DRY RUN] Would update {yt_id}")
            logger.info(f"  Description preview:\n{new_desc[:500]}...")
            stats["updated"] += 1
            continue

        # Push to YouTube
        try:
            success = youtube.update_video(
                video_id=yt_id,
                title=new_title,
                description=new_desc,
                tags=new_tags,
            )
            if success:
                # Update optimized_title in memory
                memory.conn.execute(
                    "UPDATE migrated_videos SET optimized_title = ? WHERE wistia_hashed_id = ?",
                    (new_title, wistia_id),
                )
                memory.conn.commit()
                stats["updated"] += 1
            else:
                stats["errors"] += 1
        except Exception as e:
            logger.error(f"YouTube update failed for {yt_id}: {e}")
            stats["errors"] += 1

        # Rate limit: ~1 request/sec to stay safe
        time.sleep(1)

    logger.info(f"\n{'='*60}")
    logger.info(f"GEO UPDATE COMPLETE — {stats}")
    logger.info(f"{'='*60}")

    memory.close()


if __name__ == "__main__":
    main()
