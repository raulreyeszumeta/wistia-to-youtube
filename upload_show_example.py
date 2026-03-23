"""
Example: Upload a curated show playlist to YouTube with custom CTAs.
Edit the SHOW_* constants and EPISODES list for your show before running.
"""

import sys
import os
import time
import logging
from config import LOG_DIR, TEMP_DIR, COMPANY
from memory_store import MemoryStore
from wistia_client import WistiaClient
from youtube_client import YouTubeClient, download_file
from optimizer import Optimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "upload_show.log"), mode="a"),
    ],
)
logger = logging.getLogger("upload_show")

# Configure these for your show
SHOW_NAME = "Your Show Name"
SHOW_URL = "https://yourcompany.com/shows/your-show/"
HOST_NAME = "Host Name"
HOST_TITLE = "Host Title"
HOST_LINKEDIN = ""  # optional
WISTIA_PROJECT_ID = "your_wistia_project_id"

# Add your Wistia media IDs and fallback titles here
EPISODES = [
    # ("wistia_media_id", "Episode Title"),
]


class ShowOptimizer(Optimizer):
    """Optimizer with show-specific CTA and context injected into prompts."""

    def optimize_video(self, original_title, original_description="", wistia_tags=None,
                       channel_name=SHOW_NAME, trending_topics=None, playlist_url=""):
        enriched_desc = f"""{original_description}

SHOW CONTEXT (use this in the description):
- Show: {SHOW_NAME}, hosted by {HOST_NAME} ({HOST_TITLE})
- Host LinkedIn: {HOST_LINKEDIN}
- Full episode archive: {SHOW_URL}
- The Links section MUST include:
  🎙️ Watch more {SHOW_NAME}: {SHOW_URL}
  👤 Connect with {HOST_NAME} on LinkedIn: {HOST_LINKEDIN}
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
    optimizer = ShowOptimizer()

    channel_info = youtube.verify_channel()
    logger.info(f"Uploading to @{channel_info['handle']}")

    playlist_title = f"{SHOW_NAME} with {HOST_NAME} | {COMPANY}"
    host_line = f"Connect with {HOST_NAME}: {HOST_LINKEDIN}" if HOST_LINKEDIN else ""
    playlist_desc = f"""{SHOW_URL}

{SHOW_NAME} is hosted by {HOST_NAME} ({HOST_TITLE}). Each episode features in-depth conversations with industry leaders.

{host_line}

#{SHOW_NAME.replace(' ', '')} #{COMPANY.replace(' ', '')}"""

    playlist_id = youtube.get_or_create_playlist(playlist_title, playlist_desc)
    memory.record_playlist(WISTIA_PROJECT_ID, playlist_id, playlist_title)
    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

    stats = {"uploaded": 0, "skipped": 0, "errors": 0}

    for idx, (wistia_id, fallback_title) in enumerate(EPISODES):
        logger.info(f"\n--- [{idx+1}/{len(EPISODES)}] ---")

        # Skip if already migrated
        if memory.is_migrated(wistia_id):
            yt_id = memory.get_youtube_id(wistia_id)
            logger.info(f"Already migrated → {yt_id}. Skipping.")
            stats["skipped"] += 1
            continue

        # Fetch Wistia metadata
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

        # Optimize with GEO template + Pro AV CTA
        try:
            optimized = optimizer.optimize_video(
                original_title=original_title,
                original_description=original_desc,
                wistia_tags=wistia_tags,
                channel_name=SHOW_NAME,
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

        # Download video
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

            # Upload
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

        # Add to playlist
        youtube.add_to_playlist(playlist_id, youtube_video_id)

        # Record
        memory.record_migration(
            wistia_hashed_id=wistia_id,
            youtube_video_id=youtube_video_id,
            wistia_project_id=WISTIA_PROJECT_ID,
            youtube_playlist_id=playlist_id,
            title=original_title,
            optimized_title=opt_title,
        )

        logger.info(f"SUCCESS: {original_title} → youtube.com/watch?v={youtube_video_id}")
        stats["uploaded"] += 1

    logger.info(f"\n{'='*60}")
    logger.info(f"SHOW UPLOAD COMPLETE — {stats}")
    logger.info(f"{'='*60}")
    memory.close()


if __name__ == "__main__":
    main()
