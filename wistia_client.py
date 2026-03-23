"""
Wistia API client — list projects, list videos, fetch metadata, get download URLs.
Docs: https://wistia.com/support/developers/data-api
"""

import time
import logging
import requests
from typing import List, Optional, Union
from config import WISTIA_API_TOKEN, WISTIA_RATE_LIMIT_DELAY, MAX_RETRIES, RETRY_BACKOFF

logger = logging.getLogger(__name__)

BASE_URL = "https://api.wistia.com/v1"


class WistiaClient:
    def __init__(self, api_token: str = WISTIA_API_TOKEN):
        if not api_token:
            raise ValueError("WISTIA_API_TOKEN is required. Set it in .env")
        self.session = requests.Session()
        self.session.auth = ("api", api_token)
        self.session.headers.update({"Accept": "application/json"})

    def _request(self, method: str, endpoint: str, **kwargs) -> Union[dict, list]:
        url = f"{BASE_URL}/{endpoint}"
        for attempt in range(MAX_RETRIES):
            try:
                time.sleep(WISTIA_RATE_LIMIT_DELAY)
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code == 429:
                    wait = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning(f"Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning(f"Request failed ({e}), retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        return {}

    def list_projects(self, page: int = 1, per_page: int = 100) -> List[dict]:
        """List all Wistia projects (channels)."""
        return self._request(
            "GET", "projects.json", params={"page": page, "per_page": per_page}
        )

    def get_project(self, project_hashed_id: str) -> dict:
        """Get a single project with its medias."""
        return self._request("GET", f"projects/{project_hashed_id}.json")

    def list_medias(
        self, project_id: Optional[str] = None, page: int = 1, per_page: int = 100
    ) -> List[dict]:
        """List medias, optionally filtered by project."""
        params = {"page": page, "per_page": per_page}
        if project_id:
            params["project_id"] = project_id
        return self._request("GET", "medias.json", params=params)

    def get_media(self, media_hashed_id: str) -> dict:
        """Get full media details including assets (download URLs)."""
        return self._request("GET", f"medias/{media_hashed_id}.json")

    def get_all_medias_in_project(self, project_hashed_id: str) -> List[dict]:
        """Paginate through all medias in a project."""
        project = self.get_project(project_hashed_id)
        medias = project.get("medias", [])
        logger.info(
            f"Project '{project.get('name', project_hashed_id)}' has {len(medias)} media(s)"
        )
        return medias

    def get_download_url(self, media: dict, max_height: int = 1080) -> Optional[str]:
        """
        Extract the best MP4 download URL from media assets.
        Picks the highest quality MP4 up to max_height (default 1080p).
        Skips OriginalFile to avoid unnecessarily large 4K downloads.
        """
        assets = media.get("assets", [])
        if not assets:
            full = self.get_media(media["hashed_id"])
            assets = full.get("assets", [])

        mp4s = [
            a
            for a in assets
            if (a.get("contentType", "").startswith("video/mp4")
                or a.get("type", "").endswith("VideoFile"))
            and a.get("type") != "OriginalFile"
        ]
        if mp4s:
            # Filter to max_height, then pick the highest available
            within_limit = [a for a in mp4s if a.get("height", 0) <= max_height]
            candidates = within_limit if within_limit else mp4s
            candidates.sort(key=lambda a: a.get("height", 0), reverse=True)
            chosen = candidates[0]
            logger.info(
                f"Selected {chosen.get('width', '?')}x{chosen.get('height', '?')} "
                f"({chosen.get('type', 'mp4')})"
            )
            return chosen.get("url")

        # Fallback to OriginalFile if no transcoded MP4s available
        original = next((a for a in assets if a.get("type") == "OriginalFile"), None)
        if original and original.get("url"):
            logger.info("No transcoded MP4 found, using OriginalFile")
            return original["url"]

        return None

    def get_thumbnail_url(self, media: dict, width: int = 1280, height: int = 720) -> Optional[str]:
        """Get the thumbnail URL for a media at YouTube-recommended resolution (1280x720)."""
        thumb = media.get("thumbnail", {})
        if isinstance(thumb, dict):
            url = thumb.get("url", "")
            if url:
                # Replace Wistia's default low-res crop with HD
                base = url.split("?")[0]
                return f"{base}?image_crop_resized={width}x{height}"
        return None
