"""
SQLite database for pipeline data: videos, metrics, A/B variants, playlists, topics.
"""

import os
import sqlite3
import json
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "pipeline.db")


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            platform TEXT NOT NULL,
            language TEXT NOT NULL,
            topic TEXT,
            category TEXT,
            title TEXT,
            upload_date TEXT NOT NULL,
            run_dir TEXT,
            playlist_id TEXT,
            ab_variant_id INTEGER,
            shorts_video_id TEXT,
            ig_media_id TEXT
        );

        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0.0,
            avg_watch_time REAL DEFAULT 0.0,
            impressions INTEGER DEFAULT 0,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ab_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_db_id INTEGER NOT NULL,
            variant_type TEXT NOT NULL,
            variant_data TEXT NOT NULL,
            is_winner INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0.0,
            FOREIGN KEY (video_db_id) REFERENCES videos(id)
        );

        CREATE TABLE IF NOT EXISTS topic_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            category TEXT NOT NULL,
            avg_views REAL DEFAULT 0.0,
            avg_ctr REAL DEFAULT 0.0,
            times_used INTEGER DEFAULT 1,
            last_score REAL DEFAULT 0.0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            language TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            video_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quota_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            date TEXT NOT NULL,
            units_used INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_videos_video_id ON videos(video_id);
        CREATE INDEX IF NOT EXISTS idx_videos_category ON videos(category);
        CREATE INDEX IF NOT EXISTS idx_metrics_video_id ON metrics(video_id);
        CREATE INDEX IF NOT EXISTS idx_playlists_category ON playlists(category, language);
        CREATE INDEX IF NOT EXISTS idx_quota_provider_date ON quota_usage(provider, date);
    """)

    conn.commit()
    conn.close()


# --- Video CRUD ---

def insert_video(video_id: str, platform: str, language: str, topic: str,
                 category: str, title: str, run_dir: str = None) -> int:
    """Insert a video record and return its DB id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO videos (video_id, platform, language, topic, category, title, upload_date, run_dir)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, platform, language, topic, category, title, datetime.now().isoformat(), run_dir)
    )
    db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return db_id


def update_video_shorts(db_id: int, shorts_video_id: str):
    """Update video record with shorts video ID."""
    conn = get_connection()
    conn.execute("UPDATE videos SET shorts_video_id = ? WHERE id = ?", (shorts_video_id, db_id))
    conn.commit()
    conn.close()


def update_video_ig(db_id: int, ig_media_id: str):
    """Update video record with Instagram media ID."""
    conn = get_connection()
    conn.execute("UPDATE videos SET ig_media_id = ? WHERE id = ?", (ig_media_id, db_id))
    conn.commit()
    conn.close()


def update_video_playlist(db_id: int, playlist_id: str):
    """Update video record with playlist ID."""
    conn = get_connection()
    conn.execute("UPDATE videos SET playlist_id = ? WHERE id = ?", (playlist_id, db_id))
    conn.commit()
    conn.close()


# --- Metrics ---

def insert_metrics(video_id: str, platform: str, metrics: dict):
    """Insert metrics for a video."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO metrics (video_id, platform, views, likes, ctr, avg_watch_time, impressions, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, platform, metrics.get("views", 0), metrics.get("likes", 0),
         metrics.get("ctr", 0.0), metrics.get("avg_watch_time", 0.0),
         metrics.get("impressions", 0), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_latest_metrics(video_id: str) -> dict:
    """Get most recent metrics for a video."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM metrics WHERE video_id = ? ORDER BY fetched_at DESC LIMIT 1",
        (video_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# --- A/B Variants ---

def insert_ab_variant(video_db_id: int, variant_type: str, variant_data: dict) -> int:
    """Insert an A/B variant and return its ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO ab_variants (video_db_id, variant_type, variant_data)
           VALUES (?, ?, ?)""",
        (video_db_id, variant_type, json.dumps(variant_data))
    )
    variant_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return variant_id


def update_ab_variant_result(variant_id: int, ctr: float, is_winner: bool = False):
    """Update A/B variant with performance results."""
    conn = get_connection()
    conn.execute(
        "UPDATE ab_variants SET ctr = ?, is_winner = ? WHERE id = ?",
        (ctr, 1 if is_winner else 0, variant_id)
    )
    conn.commit()
    conn.close()


# --- Topic Scores ---

def upsert_topic_score(topic: str, category: str, views: float = 0, ctr: float = 0):
    """Insert or update topic performance score."""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, times_used, avg_views, avg_ctr FROM topic_scores WHERE topic = ?",
        (topic,)
    ).fetchone()

    if existing:
        n = existing["times_used"]
        new_avg_views = (existing["avg_views"] * n + views) / (n + 1)
        new_avg_ctr = (existing["avg_ctr"] * n + ctr) / (n + 1)
        score = new_avg_views * 0.3 + new_avg_ctr * 0.7 * 10000
        conn.execute(
            """UPDATE topic_scores SET avg_views = ?, avg_ctr = ?, times_used = ?,
               last_score = ?, updated_at = ? WHERE id = ?""",
            (new_avg_views, new_avg_ctr, n + 1, score, datetime.now().isoformat(), existing["id"])
        )
    else:
        score = views * 0.3 + ctr * 0.7 * 10000
        conn.execute(
            """INSERT INTO topic_scores (topic, category, avg_views, avg_ctr, times_used, last_score, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (topic, category, views, ctr, score, datetime.now().isoformat())
        )

    conn.commit()
    conn.close()


def get_top_categories(limit: int = 5) -> list:
    """Get top-performing categories by score."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT category, AVG(last_score) as avg_score, SUM(times_used) as total_uses
           FROM topic_scores GROUP BY category ORDER BY avg_score DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Playlists ---

def get_playlist(category: str, language: str, platform: str = "youtube") -> dict:
    """Get playlist by category and language."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM playlists WHERE category = ? AND language = ? AND platform = ?",
        (category, language, platform)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_playlist(playlist_id: str, platform: str, language: str,
                    category: str, title: str) -> int:
    """Insert a new playlist record."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO playlists (playlist_id, platform, language, category, title, video_count, created_at)
           VALUES (?, ?, ?, ?, ?, 0, ?)""",
        (playlist_id, platform, language, category, title, datetime.now().isoformat())
    )
    db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return db_id


def increment_playlist_count(playlist_id: str):
    """Increment video count for a playlist."""
    conn = get_connection()
    conn.execute(
        "UPDATE playlists SET video_count = video_count + 1 WHERE playlist_id = ?",
        (playlist_id,)
    )
    conn.commit()
    conn.close()


# --- Quota Tracking ---

def log_quota_usage(provider: str, units: int = 1):
    """Log API quota usage for a provider."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, units_used FROM quota_usage WHERE provider = ? AND date = ?",
        (provider, today)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE quota_usage SET units_used = units_used + ? WHERE id = ?",
            (units, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO quota_usage (provider, date, units_used) VALUES (?, ?, ?)",
            (provider, today, units)
        )

    conn.commit()
    conn.close()


def get_quota_usage(provider: str, date: str = None) -> int:
    """Get quota usage for a provider on a given date."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    row = conn.execute(
        "SELECT units_used FROM quota_usage WHERE provider = ? AND date = ?",
        (provider, date)
    ).fetchone()
    conn.close()
    return row["units_used"] if row else 0
