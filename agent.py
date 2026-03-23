"""
Main agent orchestrator — ties together Wistia, YouTube, Optimizer, and Memory.
Handles the full pipeline: fetch → optimize → upload → playlist → record.
"""

import os
import sys
import time
import logging
import tempfile
from pathlib import Path
from typing import List, Optional

from config import (
    DRY_RUN,
    TEMP_DIR,
    PLAYLIST_SUFFIX,
    COMPANY,
    WEBSITE,
    LOCATION,
    FOCUS,
    LOG_DIR,
)
from memory_store import MemoryStore
from wistia_client import WistiaClient
from youtube_client import YouTubeClient, download_file
from optimizer import Optimizer

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "agent.log"), mode="a"),
    ],
)
logger = logging.getLogger("agent")


class WistiaToYouTubeAgent:
    def __init__(self, dry_run: bool = DRY_RUN):
        self.dry_run = dry_run
        self.memory = MemoryStore()
        self.wistia = WistiaClient()

        if not dry_run:
            self.youtube = YouTubeClient()
            channel_info = self.youtube.verify_channel()
            logger.info(f"Verified: uploading to @{channel_info['handle']} ({channel_info['title']})")
        else:
            self.youtube = None
            logger.info("DRY RUN mode — YouTube operations will be simulated")

        try:
            self.optimizer = Optimizer()
        except ValueError:
            self.optimizer = None
            logger.warning("Anthropic API key not set — AI optimization disabled")
        self.trending_topics = []

    def refresh_trends(self):
        """Fetch current trending topics for B2B/marketing to inform optimizations."""
        cache_key = "b2b_marketing_trends"
        cached = self.memory.get_cached_trends(cache_key, max_age_hours=24)

        if cached:
            self.trending_topics = cached.get("topics", [])
            logger.info(f"Loaded {len(self.trending_topics)} cached trending topics")
            return

        if self.youtube:
            logger.info("Fetching fresh YouTube trends...")
            queries = [
                f"{FOCUS} trends" if FOCUS else "video content trends",
                f"trends {LOCATION}" if LOCATION else "industry trends",
                f"AI {FOCUS}" if FOCUS else "AI content strategy",
                "content marketing strategy",
            ]
            topics = set()
            for q in queries:
                results = self.youtube.search_trending(q, max_results=5)
                for r in results:
                    topics.add(r["title"])
                time.sleep(0.5)  # rate limit

            self.trending_topics = list(topics)[:20]
            self.memory.set_cached_trends(
                cache_key, {"topics": self.trending_topics}
            )
            logger.info(f"Cached {len(self.trending_topics)} trending topics")
        else:
            # Dry run fallback trends
            self.trending_topics = [
                "AI in B2B Marketing 2026",
                "B2B Content Strategy Trends",
                "Business Innovation Best Practices",
                "Content Marketing ROI Strategies",
                "B2B Video Marketing Best Practices",
            ]
            logger.info("Using fallback trends for dry run")

    def process_channel(self, wistia_project_id: str) -> dict:
        """
        Process a single Wistia channel/project:
        1. Fetch all videos
        2. Create/find YouTube playlist
        3. For each video: download → optimize → upload → add to playlist
        """
        stats = {"uploaded": 0, "skipped": 0, "errors": 0}

        # 1. Fetch project + videos
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing Wistia project: {wistia_project_id}")
        logger.info(f"{'='*60}")

        try:
            project = self.wistia.get_project(wistia_project_id)
        except Exception as e:
            logger.error(f"Failed to fetch project {wistia_project_id}: {e}")
            stats["errors"] += 1
            return stats

        project_name = project.get("name", wistia_project_id)
        medias = project.get("medias", [])
        logger.info(f"Project '{project_name}' — {len(medias)} video(s)")

        if not medias:
            logger.warning("No videos found in project.")
            return stats

        # 2. Create/find playlist
        playlist_title = f"{project_name}{PLAYLIST_SUFFIX}"
        playlist_desc = self.optimizer.generate_playlist_description(project_name) if self.optimizer else ""
        playlist_id = None

        if not self.dry_run:
            # Check memory first
            playlist_id = self.memory.get_playlist(wistia_project_id)
            if not playlist_id:
                playlist_id = self.youtube.get_or_create_playlist(
                    playlist_title, playlist_desc
                )
                self.memory.record_playlist(
                    wistia_project_id, playlist_id, playlist_title
                )
        else:
            playlist_id = self.memory.get_playlist(wistia_project_id) or "DRY_RUN_PLAYLIST"
            logger.info(f"[DRY RUN] Would create/find playlist: '{playlist_title}'")

        # 3. Process each video
        for idx, media in enumerate(medias):
            hashed_id = media.get("hashed_id", "")
            original_title = media.get("name", "Untitled")
            logger.info(f"\n--- Video {idx + 1}/{len(medias)}: {original_title} ---")

            # Skip already migrated
            if self.memory.is_migrated(hashed_id):
                yt_id = self.memory.get_youtube_id(hashed_id)
                logger.info(f"Already migrated → {yt_id}. Skipping.")
                stats["skipped"] += 1
                continue

            try:
                video_id = self._process_single_video(
                    media, project_name, wistia_project_id, playlist_id
                )
                if video_id:
                    stats["uploaded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                logger.error(f"Error processing {hashed_id}: {e}", exc_info=True)
                stats["errors"] += 1

        logger.info(f"\nChannel '{project_name}' done: {stats}")
        return stats

    def _process_single_video(
        self,
        media: dict,
        channel_name: str,
        wistia_project_id: str,
        playlist_id: Optional[str],
    ) -> Optional[str]:
        """Process a single video: download, optimize metadata, upload."""
        hashed_id = media.get("hashed_id", "")
        original_title = media.get("name", "Untitled")
        original_desc = media.get("description", "")
        wistia_tags = [t.get("name", "") for t in media.get("tags", [])] if media.get("tags") else []

        # Fetch full media for download URL
        full_media = self.wistia.get_media(hashed_id)
        download_url = self.wistia.get_download_url(full_media)
        thumbnail_url = self.wistia.get_thumbnail_url(full_media)

        if not download_url:
            logger.error(f"No download URL available for {hashed_id}")
            return None

        # Optimize metadata with AI (GEO template)
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}" if playlist_id else ""
        if self.optimizer:
            logger.info("Optimizing metadata with GEO template...")
            optimized = self.optimizer.optimize_video(
                original_title=original_title,
                original_description=original_desc,
                wistia_tags=wistia_tags,
                channel_name=channel_name,
                trending_topics=self.trending_topics,
                playlist_url=playlist_url,
            )
        else:
            optimized = {"title": original_title, "description": original_desc, "tags": wistia_tags or []}

        opt_title = optimized["title"]
        opt_desc = optimized["description"]
        opt_tags = optimized["tags"]

        logger.info(f"  Title: {opt_title}")
        logger.info(f"  Tags: {', '.join(opt_tags[:5])}...")

        if self.dry_run:
            logger.info(f"[DRY RUN] Would upload: '{opt_title}'")
            logger.info(f"[DRY RUN] Description preview: {opt_desc[:150]}...")
            logger.info(f"[DRY RUN] Download URL: {download_url[:80]}...")
            return None

        # Download video
        video_path = str(TEMP_DIR / f"{hashed_id}.mp4")
        try:
            download_file(download_url, video_path)
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None

        # Download thumbnail if available
        thumb_path = None
        if thumbnail_url:
            thumb_path = str(TEMP_DIR / f"{hashed_id}_thumb.jpg")
            try:
                download_file(thumbnail_url, thumb_path)
            except Exception:
                thumb_path = None

        # Upload to YouTube
        try:
            youtube_video_id = self.youtube.upload_video(
                file_path=video_path,
                title=opt_title,
                description=opt_desc,
                tags=opt_tags,
                thumbnail_path=thumb_path,
            )
        finally:
            # Cleanup temp files
            for p in [video_path, thumb_path]:
                if p and os.path.exists(p):
                    os.remove(p)

        if not youtube_video_id:
            logger.error("Upload returned no video ID")
            return None

        # Add to playlist
        if playlist_id:
            self.youtube.add_to_playlist(playlist_id, youtube_video_id)

        # Record in memory
        self.memory.record_migration(
            wistia_hashed_id=hashed_id,
            youtube_video_id=youtube_video_id,
            wistia_project_id=wistia_project_id,
            youtube_playlist_id=playlist_id or "",
            title=original_title,
            optimized_title=opt_title,
        )

        logger.info(f"SUCCESS: {original_title} → youtube.com/watch?v={youtube_video_id}")
        return youtube_video_id

    def run(self, wistia_project_ids: List[str]):
        """Main entry point — process a list of Wistia channels."""
        logger.info(f"\n{'#'*60}")
        logger.info(f"Wistia→YouTube Agent {'[DRY RUN]' if self.dry_run else '[LIVE]'}")
        logger.info(f"Projects to process: {len(wistia_project_ids)}")
        logger.info(f"{'#'*60}\n")

        run_id = self.memory.start_run(self.dry_run)
        total_stats = {"channels": 0, "uploaded": 0, "skipped": 0, "errors": 0}

        # Step 1: Refresh trends
        self.refresh_trends()

        # Step 2: Process each channel
        for project_id in wistia_project_ids:
            try:
                stats = self.process_channel(project_id)
                total_stats["channels"] += 1
                total_stats["uploaded"] += stats["uploaded"]
                total_stats["skipped"] += stats["skipped"]
                total_stats["errors"] += stats["errors"]
            except Exception as e:
                logger.error(f"Channel {project_id} failed: {e}", exc_info=True)
                total_stats["errors"] += 1

        # Step 3: Log run
        self.memory.finish_run(
            run_id,
            channels=total_stats["channels"],
            uploaded=total_stats["uploaded"],
            skipped=total_stats["skipped"],
            errors=total_stats["errors"],
        )

        logger.info(f"\n{'#'*60}")
        logger.info(f"RUN COMPLETE — {total_stats}")
        logger.info(f"Migration stats: {self.memory.get_migration_stats()}")
        logger.info(f"{'#'*60}")

        return total_stats

    def list_projects(self):
        """Utility: list all Wistia projects to help find IDs."""
        projects = self.wistia.list_projects()
        logger.info(f"\nFound {len(projects)} Wistia projects:")
        for p in projects:
            count = p.get("mediaCount", "?")
            logger.info(f"  [{p['hashedId']}] {p['name']} ({count} videos)")
        return projects


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Wistia→YouTube migration agent with AI-powered SEO optimization"
    )
    parser.add_argument(
        "projects",
        nargs="*",
        help="Wistia project hashed IDs to process",
    )
    parser.add_argument(
        "--list-projects",
        action="store_true",
        help="List all Wistia projects and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Preview without uploading (overrides .env)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live mode (upload to YouTube)",
    )

    args = parser.parse_args()

    # Determine dry_run mode
    if args.live:
        dry_run = False
    elif args.dry_run is not None:
        dry_run = args.dry_run
    else:
        dry_run = DRY_RUN

    agent = WistiaToYouTubeAgent(dry_run=dry_run)

    if args.list_projects:
        agent.list_projects()
        return

    if not args.projects:
        logger.info("No projects specified. Use --list-projects to see available ones.")
        logger.info("Usage: python agent.py <project_id1> <project_id2> ...")
        logger.info("       python agent.py --list-projects")
        return

    agent.run(args.projects)


if __name__ == "__main__":
    main()
