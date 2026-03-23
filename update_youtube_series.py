"""
update_youtube_series.py — Re-optimize metadata for YouTube-native videos (not Wistia-migrated).

Use this for videos already on YouTube that you want to update with GEO-optimized descriptions.
Edit PLAYLIST_ID, SERIES_NAME, FANS_FIRST_CONTEXT, and FANS_FIRST_VIDEOS for your series.
"""

import sys
import time
import logging
from config import LOG_DIR
from youtube_client import YouTubeClient
from optimizer import Optimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "update_youtube_series.log"), mode="a"),
    ],
)
logger = logging.getLogger("update_youtube_series")

# Replace with your YouTube playlist ID (find it in YouTube Studio)
PLAYLIST_ID = "your_youtube_playlist_id_here"
PLAYLIST_URL = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"
SERIES_NAME = "Your Series Name"

# Context injected into the AI optimizer for this series.
# Customize this with your show's theme, host, and key topics.
FANS_FIRST_CONTEXT = """
SHOW CONTEXT (use this in the description):
- Series: Your Series Name
- Theme: Describe your show's theme and core topics here
- Key principles: List the main themes covered in this series
- The Links section MUST include:
  📺 Watch the full playlist: """ + PLAYLIST_URL + """
"""

# Add your YouTube video IDs here.
# These are already-uploaded YouTube videos (not Wistia — use agent.py for Wistia migration).
# Find video IDs in YouTube Studio or from the video URL: youtube.com/watch?v=VIDEO_ID
FANS_FIRST_VIDEOS = [
    # "VIDEO_ID_1",  # Episode title
    # "VIDEO_ID_2",  # Episode title
]


class SeriesOptimizer(Optimizer):
    """Optimizer with series-specific context injected into the GEO prompt."""

    def optimize_video(self, original_title, original_description="", wistia_tags=None,
                       channel_name=SERIES_NAME, trending_topics=None, playlist_url=PLAYLIST_URL):
        enriched_desc = f"{original_description}\n{FANS_FIRST_CONTEXT}"
        return super().optimize_video(
            original_title=original_title,
            original_description=enriched_desc,
            wistia_tags=wistia_tags,
            channel_name=channel_name,
            trending_topics=trending_topics,
            playlist_url=playlist_url,
        )


def main():
    youtube = YouTubeClient()
    optimizer = SeriesOptimizer()

    channel_info = youtube.verify_channel()
    logger.info(f"Updating {SERIES_NAME} on @{channel_info['handle']}")

    # Fetch current metadata for all videos in one API call
    video_ids = ",".join(FANS_FIRST_VIDEOS)
    resp = youtube.youtube.videos().list(
        part="snippet", id=video_ids
    ).execute()

    videos = {item["id"]: item for item in resp.get("items", [])}
    logger.info(f"Fetched metadata for {len(videos)} videos")

    stats = {"updated": 0, "errors": 0}

    for idx, vid_id in enumerate(FANS_FIRST_VIDEOS):
        logger.info(f"\n--- [{idx+1}/{len(FANS_FIRST_VIDEOS)}] ---")

        if vid_id not in videos:
            logger.error(f"Video {vid_id} not found on YouTube")
            stats["errors"] += 1
            continue

        snippet = videos[vid_id]["snippet"]
        original_title = snippet["title"]
        original_desc = snippet.get("description", "")
        original_tags = snippet.get("tags", [])

        logger.info(f"Original: {original_title}")

        # Optimize with GEO template + series context
        try:
            optimized = optimizer.optimize_video(
                original_title=original_title,
                original_description=original_desc,
                wistia_tags=original_tags,
                channel_name=SERIES_NAME,
                playlist_url=PLAYLIST_URL,
            )
        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            stats["errors"] += 1
            continue

        opt_title = optimized["title"]
        opt_desc = optimized["description"]
        opt_tags = optimized["tags"]

        logger.info(f"Optimized: {opt_title}")

        # Push update to YouTube
        success = youtube.update_video(
            video_id=vid_id,
            title=opt_title,
            description=opt_desc,
            tags=opt_tags,
        )

        if success:
            logger.info(f"SUCCESS: {original_title} → {opt_title}")
            stats["updated"] += 1
        else:
            logger.error(f"Failed to update {vid_id}")
            stats["errors"] += 1

        time.sleep(1)  # Rate limit (videos.update = 50 quota units each)

    logger.info(f"\n{'='*60}")
    logger.info(f"FANS FIRST UPDATE COMPLETE — {stats}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
