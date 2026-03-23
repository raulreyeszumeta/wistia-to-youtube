"""
SQLite-based persistent memory for the Wistia-to-YouTube agent.
Tracks: migrated videos, playlists, trends cache, run history.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional
from config import MEMORY_DB


class MemoryStore:
    def __init__(self, db_path=MEMORY_DB):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS migrated_videos (
                wistia_hashed_id TEXT PRIMARY KEY,
                youtube_video_id TEXT NOT NULL,
                wistia_project_id TEXT,
                youtube_playlist_id TEXT,
                title TEXT,
                optimized_title TEXT,
                migrated_at TEXT NOT NULL,
                status TEXT DEFAULT 'uploaded'
            );

            CREATE TABLE IF NOT EXISTS playlists (
                wistia_project_id TEXT PRIMARY KEY,
                youtube_playlist_id TEXT NOT NULL,
                playlist_title TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trends_cache (
                cache_key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                channels_processed INTEGER DEFAULT 0,
                videos_uploaded INTEGER DEFAULT 0,
                videos_skipped INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                dry_run INTEGER DEFAULT 1,
                notes TEXT
            );
        """)
        self.conn.commit()

    # --- Migrated Videos ---

    def is_migrated(self, wistia_hashed_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM migrated_videos WHERE wistia_hashed_id = ?",
            (wistia_hashed_id,),
        )
        return cur.fetchone() is not None

    def get_youtube_id(self, wistia_hashed_id: str) -> Optional[str]:
        cur = self.conn.execute(
            "SELECT youtube_video_id FROM migrated_videos WHERE wistia_hashed_id = ?",
            (wistia_hashed_id,),
        )
        row = cur.fetchone()
        return row["youtube_video_id"] if row else None

    def record_migration(
        self,
        wistia_hashed_id: str,
        youtube_video_id: str,
        wistia_project_id: str = "",
        youtube_playlist_id: str = "",
        title: str = "",
        optimized_title: str = "",
    ):
        self.conn.execute(
            """INSERT OR REPLACE INTO migrated_videos
               (wistia_hashed_id, youtube_video_id, wistia_project_id,
                youtube_playlist_id, title, optimized_title, migrated_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded')""",
            (
                wistia_hashed_id,
                youtube_video_id,
                wistia_project_id,
                youtube_playlist_id,
                title,
                optimized_title,
                datetime.utcnow().isoformat(),
            ),
        )
        self.conn.commit()

    def get_migration_stats(self) -> dict:
        cur = self.conn.execute(
            "SELECT COUNT(*) as total, status FROM migrated_videos GROUP BY status"
        )
        return {row["status"]: row["total"] for row in cur.fetchall()}

    # --- Playlists ---

    def get_playlist(self, wistia_project_id: str) -> Optional[str]:
        cur = self.conn.execute(
            "SELECT youtube_playlist_id FROM playlists WHERE wistia_project_id = ?",
            (wistia_project_id,),
        )
        row = cur.fetchone()
        return row["youtube_playlist_id"] if row else None

    def record_playlist(
        self, wistia_project_id: str, youtube_playlist_id: str, title: str
    ):
        self.conn.execute(
            """INSERT OR REPLACE INTO playlists
               (wistia_project_id, youtube_playlist_id, playlist_title, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                wistia_project_id,
                youtube_playlist_id,
                title,
                datetime.utcnow().isoformat(),
            ),
        )
        self.conn.commit()

    # --- Trends Cache ---

    def get_cached_trends(self, cache_key: str, max_age_hours: int = 24) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT data, fetched_at FROM trends_cache WHERE cache_key = ?",
            (cache_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        if datetime.utcnow() - fetched_at > timedelta(hours=max_age_hours):
            return None
        return json.loads(row["data"])

    def set_cached_trends(self, cache_key: str, data: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO trends_cache (cache_key, data, fetched_at)
               VALUES (?, ?, ?)""",
            (cache_key, json.dumps(data), datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    # --- Run Log ---

    def start_run(self, dry_run: bool) -> int:
        cur = self.conn.execute(
            "INSERT INTO run_log (started_at, dry_run) VALUES (?, ?)",
            (datetime.utcnow().isoformat(), 1 if dry_run else 0),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(
        self,
        run_id: int,
        channels: int = 0,
        uploaded: int = 0,
        skipped: int = 0,
        errors: int = 0,
        notes: str = "",
    ):
        self.conn.execute(
            """UPDATE run_log SET finished_at = ?, channels_processed = ?,
               videos_uploaded = ?, videos_skipped = ?, errors = ?, notes = ?
               WHERE id = ?""",
            (
                datetime.utcnow().isoformat(),
                channels,
                uploaded,
                skipped,
                errors,
                notes,
                run_id,
            ),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
