"""
Re-upload HD thumbnails (1280x720) for all migrated YouTube videos.
Replaces the low-res 200x120 thumbnails from the initial migration.
"""

import sys
import time
import os
import logging
import argparse
from config import LOG_DIR, TEMP_DIR
from memory_store import MemoryStore
from wistia_client import WistiaClient
from youtube_client import YouTubeClient, download_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "update_thumbnails.log"), mode="a"),
    ],
)
logger = logging.getLogger("update_thumbnails")

# thumbnails.set costs 50 quota units per call
QUOTA_SAFE_LIMIT = 100


def main():
    parser = argparse.ArgumentParser(
        description="Re-upload HD thumbnails for migrated YouTube videos"
    )
    parser.add_argument(
        "projects", nargs="*",
        help="Wistia project IDs to update (default: all migrated videos)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=QUOTA_SAFE_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    memory = MemoryStore()
    wistia = WistiaClient()

    if args.projects:
        placeholders = ",".join("?" for _ in args.projects)
        cur = memory.conn.execute(
            f"SELECT wistia_hashed_id, youtube_video_id, title FROM migrated_videos "
            f"WHERE wistia_project_id IN ({placeholders}) ORDER BY migrated_at",
            args.projects,
        )
    else:
        cur = memory.conn.execute(
            "SELECT wistia_hashed_id, youtube_video_id, title FROM migrated_videos ORDER BY migrated_at"
        )
    videos = [dict(r) for r in cur.fetchall()]

    if args.offset:
        videos = videos[args.offset:]
    if len(videos) > args.limit:
        videos = videos[:args.limit]

    logger.info(f"Updating thumbnails for {len(videos)} videos")

    youtube = None
    if not args.dry_run:
        youtube = YouTubeClient()
        youtube.verify_channel()

    stats = {"updated": 0, "skipped": 0, "errors": 0}

    for idx, video in enumerate(videos):
        wistia_id = video["wistia_hashed_id"]
        yt_id = video["youtube_video_id"]
        title = video["title"]

        logger.info(f"\n[{idx+1}/{len(videos)}] {title} (YT: {yt_id})")

        try:
            media = wistia.get_media(wistia_id)
            thumb_url = wistia.get_thumbnail_url(media)
        except Exception as e:
            logger.error(f"  Failed to get Wistia data: {e}")
            stats["errors"] += 1
            continue

        if not thumb_url:
            logger.warning(f"  No thumbnail available")
            stats["skipped"] += 1
            continue

        logger.info(f"  Thumbnail: {thumb_url}")

        if args.dry_run:
            logger.info(f"  [DRY RUN] Would update thumbnail for {yt_id}")
            stats["updated"] += 1
            continue

        # Download HD thumbnail
        thumb_path = str(TEMP_DIR / f"{wistia_id}_thumb_hd.jpg")
        try:
            download_file(thumb_url, thumb_path)
            youtube._set_thumbnail(yt_id, thumb_path)
            stats["updated"] += 1
        except Exception as e:
            logger.error(f"  Thumbnail update failed: {e}")
            stats["errors"] += 1
        finally:
            if os.path.exists(thumb_path):
                os.remove(thumb_path)

        time.sleep(0.5)

    logger.info(f"\n{'='*60}")
    logger.info(f"THUMBNAIL UPDATE COMPLETE — {stats}")
    logger.info(f"{'='*60}")
    memory.close()


if __name__ == "__main__":
    main()
