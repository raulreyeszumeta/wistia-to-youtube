"""
upload_curated_playlist.py — Upload a hand-curated playlist of best-of videos to YouTube.

Use this to create a "Best Of" or highlight reel playlist from specific Wistia videos.
Edit PLAYLIST_NAME, PLAYLIST_PROJECT_ID, and EPISODES before running.
"""

import sys
import os
import logging
from config import LOG_DIR, TEMP_DIR, COMPANY, WEBSITE
from memory_store import MemoryStore
from wistia_client import WistiaClient
from youtube_client import YouTubeClient, download_file
from optimizer import Optimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "upload_curated_playlist.log"), mode="a"),
    ],
)
logger = logging.getLogger("upload_curated_playlist")

# Name of your curated playlist
PLAYLIST_NAME = "Best Of"
PLAYLIST_PROJECT_ID = "curated_playlist"  # virtual project ID for memory tracking

# Add your curated Wistia media IDs and fallback titles here.
# Find media IDs via: python3 agent.py --list-projects, then browse the project.
# Format: [("wistia_media_id", "Fallback title if Wistia has none"), ...]
EPISODES = [
    # ("wistia_media_id", "Episode Title"),
]


class CuratedPlaylistOptimizer(Optimizer):
    """Optimizer with curated playlist context injected into the GEO prompt."""

    def optimize_video(self, original_title, original_description="", wistia_tags=None,
                       channel_name=PLAYLIST_NAME, trending_topics=None, playlist_url=""):
        enriched_desc = f"""{original_description}

SHOW CONTEXT (use this in the description):
- This video is part of {COMPANY}'s {PLAYLIST_NAME} — a curated collection of the best episodes.
- These are hand-selected by the editorial team for exceptional storytelling, insights, and guest quality.
- The Links section MUST include:
  📺 Watch more {PLAYLIST_NAME}: {playlist_url}
"""
        return super().optimize_video(
            original_title=original_title,
            original_description=enriched_desc,
            wistia_tags=wistia_tags,
            channel_name=channel_name,
            trending_topics=trending_topics,
            playlist_url=playlist_url,
        )


def main():
    memory = MemoryStore()
    wistia = WistiaClient()
    youtube = YouTubeClient()
    optimizer = CuratedPlaylistOptimizer()

    channel_info = youtube.verify_channel()
    logger.info(f"Uploading to @{channel_info['handle']}")

    playlist_title = f"{PLAYLIST_NAME} | {COMPANY}"
    playlist_desc = f"""{WEBSITE}

{PLAYLIST_NAME} is a curated collection of the best episodes from {COMPANY}. Hand-selected by the editorial team, these videos feature exceptional storytelling, bold insights, and standout guests.

Visit {WEBSITE} for the full experience.

#{COMPANY.replace(' ', '')} #BestOf #B2B #BusinessInsights"""

    playlist_id = youtube.get_or_create_playlist(playlist_title, playlist_desc)
    memory.record_playlist(PLAYLIST_PROJECT_ID, playlist_id, playlist_title)
    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

    stats = {"uploaded": 0, "skipped": 0, "errors": 0}

    for idx, (wistia_id, fallback_title) in enumerate(EPISODES):
        logger.info(f"\n--- [{idx+1}/{len(EPISODES)}] ---")

        if memory.is_migrated(wistia_id):
            yt_id = memory.get_youtube_id(wistia_id)
            logger.info(f"Already migrated → {yt_id}. Skipping.")
            stats["skipped"] += 1
            continue

        try:
            media = wistia.get_media(wistia_id)
            original_title = media.get("name", fallback_title)
            original_desc = media.get("description", "")
            wistia_tags = [t.get("name", "") for t in media.get("tags", [])] if media.get("tags") else []
        except Exception as e:
            logger.error(f"Failed to fetch Wistia data for {wistia_id}: {e}")
            stats["errors"] += 1
            continue

        logger.info(f"Original: {original_title}")

        try:
            optimized = optimizer.optimize_video(
                original_title=original_title,
                original_description=original_desc,
                wistia_tags=wistia_tags,
                channel_name=PLAYLIST_NAME,
                playlist_url=playlist_url,
            )
        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            stats["errors"] += 1
            continue

        opt_title = optimized["title"]
        opt_desc = optimized["description"]
        opt_tags = optimized["tags"]

        logger.info(f"Optimized: {opt_title}")

        download_url = wistia.get_download_url(media)
        thumbnail_url = wistia.get_thumbnail_url(media)

        if not download_url:
            logger.error(f"No download URL for {wistia_id}")
            stats["errors"] += 1
            continue

        video_path = str(TEMP_DIR / f"{wistia_id}.mp4")
        thumb_path = None

        try:
            download_file(download_url, video_path)

            if thumbnail_url:
                thumb_path = str(TEMP_DIR / f"{wistia_id}_thumb.jpg")
                try:
                    download_file(thumbnail_url, thumb_path)
                except Exception:
                    thumb_path = None

            youtube_video_id = youtube.upload_video(
                file_path=video_path,
                title=opt_title,
                description=opt_desc,
                tags=opt_tags,
                thumbnail_path=thumb_path,
            )
        finally:
            for p in [video_path, thumb_path]:
                if p and os.path.exists(p):
                    os.remove(p)

        if not youtube_video_id:
            logger.error("Upload returned no video ID")
            stats["errors"] += 1
            continue

        youtube.add_to_playlist(playlist_id, youtube_video_id)

        memory.record_migration(
            wistia_hashed_id=wistia_id,
            youtube_video_id=youtube_video_id,
            wistia_project_id=PLAYLIST_PROJECT_ID,
            youtube_playlist_id=playlist_id,
            title=original_title,
            optimized_title=opt_title,
        )

        logger.info(f"SUCCESS: {original_title} → youtube.com/watch?v={youtube_video_id}")
        stats["uploaded"] += 1

    logger.info(f"\n{'='*60}")
    logger.info(f"CURATED PLAYLIST UPLOAD COMPLETE — {stats}")
    logger.info(f"{'='*60}")
    memory.close()


if __name__ == "__main__":
    main()
