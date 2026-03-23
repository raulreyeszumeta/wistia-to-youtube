"""
YouTube Data API v3 client — OAuth2 auth, upload, playlist management, metadata.
"""

import os
import json
import logging
import tempfile
import time
import requests
from pathlib import Path
from typing import Optional, List

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from config import (
    YOUTUBE_TOKEN_FILE,
    YOUTUBE_CLIENT_SECRETS_FILE,
    YOUTUBE_UPLOAD_CHUNK_SIZE,
    DEFAULT_YOUTUBE_CATEGORY,
    DEFAULT_PRIVACY,
    MAX_RETRIES,
    RETRY_BACKOFF,
    YOUTUBE_CHANNEL_HANDLE,
    YOUTUBE_BRAND_CHANNEL_ID,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


class YouTubeClient:
    def __init__(self):
        self.credentials = self._authenticate()
        self.youtube = build("youtube", "v3", credentials=self.credentials)

    def _authenticate(self) -> Credentials:
        """OAuth2 flow: load saved token or run consent flow."""
        creds = None
        token_path = str(YOUTUBE_TOKEN_FILE)

        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                token_data = json.load(f)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing YouTube token...")
                creds.refresh(Request())
            else:
                if not os.path.exists(str(YOUTUBE_CLIENT_SECRETS_FILE)):
                    raise FileNotFoundError(
                        f"Missing {YOUTUBE_CLIENT_SECRETS_FILE}. "
                        "Download OAuth client secrets from Google Cloud Console "
                        "and save as client_secrets.json in the project root."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(YOUTUBE_CLIENT_SECRETS_FILE), SCOPES
                )
                # Force account picker so user can select Brand Account channel
                creds = flow.run_local_server(
                    port=8090,
                    open_browser=True,
                    prompt="consent",
                )
                logger.info("YouTube OAuth2 authorized successfully.")

            # Save token
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            logger.info(f"Token saved to {token_path}")

        return creds

    # --- Channel Verification ---

    def verify_channel(self) -> dict:
        """Verify we can access the configured YouTube channel."""
        # First try mine=True (works if user directly owns channel)
        resp = (
            self.youtube.channels()
            .list(part="snippet,statistics", mine=True)
            .execute()
        )
        items = resp.get("items", [])

        # If no personal channel, look up the Brand Account by ID
        if not items and YOUTUBE_BRAND_CHANNEL_ID:
            logger.info("No personal channel found, checking Brand Account...")
            resp = (
                self.youtube.channels()
                .list(part="snippet,statistics", id=YOUTUBE_BRAND_CHANNEL_ID)
                .execute()
            )
            items = resp.get("items", [])

        if not items:
            channel_ref = f"@{YOUTUBE_CHANNEL_HANDLE}" if YOUTUBE_CHANNEL_HANDLE else "your YouTube channel"
            raise RuntimeError(
                f"Cannot access {channel_ref}. "
                "Ensure your Google account has manager/owner access to the channel."
            )

        channel = items[0]
        channel_id = channel["id"]
        title = channel["snippet"]["title"]
        handle = channel["snippet"].get("customUrl", "").lstrip("@").lower()
        subs = channel["statistics"].get("subscriberCount", "?")
        videos = channel["statistics"].get("videoCount", "?")

        logger.info(f"Target channel: {title} (@{handle}) — {subs} subs, {videos} videos")

        return {
            "channel_id": channel_id,
            "title": title,
            "handle": handle,
            "subscribers": subs,
            "video_count": videos,
        }

    # --- Playlist Operations ---

    def find_playlist_by_title(self, title: str) -> Optional[str]:
        """Search user's playlists for an exact title match. Returns playlist ID."""
        next_page = None
        while True:
            resp = (
                self.youtube.playlists()
                .list(part="snippet", mine=True, maxResults=50, pageToken=next_page)
                .execute()
            )
            for item in resp.get("items", []):
                if item["snippet"]["title"] == title:
                    return item["id"]
            next_page = resp.get("nextPageToken")
            if not next_page:
                break
        return None

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy: str = DEFAULT_PRIVACY,
    ) -> str:
        """Create a YouTube playlist. Returns playlist ID."""
        body = {
            "snippet": {"title": title[:150], "description": description[:5000]},
            "status": {"privacyStatus": privacy},
        }
        resp = (
            self.youtube.playlists().insert(part="snippet,status", body=body).execute()
        )
        playlist_id = resp["id"]
        logger.info(f"Created playlist '{title}' → {playlist_id}")
        return playlist_id

    def get_or_create_playlist(
        self, title: str, description: str = ""
    ) -> str:
        """Find existing playlist by title or create new one."""
        existing = self.find_playlist_by_title(title)
        if existing:
            logger.info(f"Found existing playlist '{title}' → {existing}")
            return existing
        return self.create_playlist(title, description)

    # --- Video Upload ---

    def upload_video(
        self,
        file_path: str,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = DEFAULT_YOUTUBE_CATEGORY,
        privacy: str = DEFAULT_PRIVACY,
        thumbnail_path: Optional[str] = None,
    ) -> str:
        """
        Upload a video to YouTube using resumable upload.
        Returns the YouTube video ID.
        """
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=YOUTUBE_UPLOAD_CHUNK_SIZE,
        )

        request = self.youtube.videos().insert(
            part="snippet,status", body=body, media_body=media
        )

        video_id = self._resumable_upload(request)

        if thumbnail_path and video_id:
            self._set_thumbnail(video_id, thumbnail_path)

        return video_id

    def _resumable_upload(self, request) -> str:
        """Execute resumable upload with retry logic."""
        response = None
        for attempt in range(MAX_RETRIES):
            try:
                logger.info("Uploading...")
                status, response = request.next_chunk()
                while response is None:
                    logger.info(
                        f"Upload progress: {int(status.progress() * 100)}%"
                        if status
                        else "Uploading..."
                    )
                    status, response = request.next_chunk()

                video_id = response["id"]
                logger.info(f"Upload complete → youtube.com/watch?v={video_id}")
                return video_id

            except HttpError as e:
                if e.resp.status in (500, 502, 503, 504):
                    wait = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning(f"Server error {e.resp.status}, retrying in {wait}s")
                    time.sleep(wait)
                else:
                    raise
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning(f"Upload error ({e}), retrying in {wait}s")
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError("Upload failed after all retries")

    def _set_thumbnail(self, video_id: str, thumbnail_path: str):
        """Set a custom thumbnail for a video."""
        try:
            media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            self.youtube.thumbnails().set(
                videoId=video_id, media_body=media
            ).execute()
            logger.info(f"Thumbnail set for {video_id}")
        except HttpError as e:
            logger.warning(f"Failed to set thumbnail: {e}")

    # --- Playlist Update ---

    def update_playlist(
        self,
        playlist_id: str,
        title: str,
        description: str = "",
    ) -> bool:
        """Update a playlist's title and description."""
        body = {
            "id": playlist_id,
            "snippet": {
                "title": title[:150],
                "description": description[:5000],
            },
        }
        try:
            self.youtube.playlists().update(
                part="snippet", body=body
            ).execute()
            logger.info(f"Updated playlist {playlist_id}: '{title}'")
            return True
        except HttpError as e:
            logger.error(f"Failed to update playlist {playlist_id}: {e}")
            return False

    def get_playlist_items(self, playlist_id: str) -> List[dict]:
        """Get all items in a playlist, ordered by position."""
        items = []
        next_page = None
        while True:
            resp = (
                self.youtube.playlistItems()
                .list(part="snippet", playlistId=playlist_id, maxResults=50, pageToken=next_page)
                .execute()
            )
            items.extend(resp.get("items", []))
            next_page = resp.get("nextPageToken")
            if not next_page:
                break
        items.sort(key=lambda x: x["snippet"]["position"])
        return items

    def reorder_playlist_item(self, item_id: str, playlist_id: str, video_id: str, new_position: int) -> bool:
        """Move a playlist item to a new position."""
        body = {
            "id": item_id,
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
                "position": new_position,
            },
        }
        try:
            self.youtube.playlistItems().update(
                part="snippet", body=body
            ).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to reorder item {item_id}: {e}")
            return False

    # --- Video Update ---

    def update_video(
        self,
        video_id: str,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = DEFAULT_YOUTUBE_CATEGORY,
    ) -> bool:
        """Update title, description, and tags for an existing YouTube video."""
        body = {
            "id": video_id,
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": category_id,
            },
        }
        try:
            self.youtube.videos().update(
                part="snippet", body=body
            ).execute()
            logger.info(f"Updated metadata for {video_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to update {video_id}: {e}")
            return False

    # --- Playlist Items ---

    def add_to_playlist(self, playlist_id: str, video_id: str, position: int = 0):
        """Add a video to a playlist."""
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
                "position": position,
            }
        }
        try:
            self.youtube.playlistItems().insert(
                part="snippet", body=body
            ).execute()
            logger.info(f"Added {video_id} to playlist {playlist_id}")
        except HttpError as e:
            logger.warning(f"Failed to add to playlist: {e}")

    # --- Search (for trends) ---

    def search_trending(
        self, query: str, max_results: int = 10, region: str = "US"
    ) -> List[dict]:
        """Search YouTube for trending videos on a topic."""
        try:
            resp = (
                self.youtube.search()
                .list(
                    part="snippet",
                    q=query,
                    type="video",
                    order="viewCount",
                    regionCode=region,
                    maxResults=max_results,
                    publishedAfter="2025-01-01T00:00:00Z",
                )
                .execute()
            )
            return [
                {
                    "title": item["snippet"]["title"],
                    "channel": item["snippet"]["channelTitle"],
                    "video_id": item["id"]["videoId"],
                    "description": item["snippet"]["description"],
                }
                for item in resp.get("items", [])
            ]
        except HttpError as e:
            logger.warning(f"Trend search failed: {e}")
            return []


def download_file(url: str, dest_path: str, chunk_size: int = 8192) -> str:
    """Download a file from URL to local path with progress logging."""
    logger.info(f"Downloading {url} → {dest_path}")
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0 and downloaded % (10 * 1024 * 1024) < chunk_size:
                pct = int(downloaded / total * 100)
                logger.info(f"Download: {pct}% ({downloaded // (1024*1024)} MB)")
    logger.info(f"Download complete: {dest_path} ({downloaded // (1024*1024)} MB)")
    return dest_path
