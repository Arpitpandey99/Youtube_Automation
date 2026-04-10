"""
SQLite database for pipeline data: videos, metrics, A/B variants, playlists, topics.
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta


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

        -- v2: Category performance weights
        CREATE TABLE IF NOT EXISTS category_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL UNIQUE,
            weight REAL DEFAULT 0.0,
            total_videos INTEGER DEFAULT 0,
            avg_ctr REAL DEFAULT 0.0,
            avg_views REAL DEFAULT 0.0,
            computed_at TEXT NOT NULL
        );

        -- v2: Trending topics discovered by trend intelligence
        CREATE TABLE IF NOT EXISTS trend_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            category TEXT,
            trend_score REAL DEFAULT 0.0,
            source TEXT,
            discovered_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        );

        -- v2: Competitor channels to track
        CREATE TABLE IF NOT EXISTS competitor_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL UNIQUE,
            channel_name TEXT,
            avg_views REAL DEFAULT 0.0,
            last_scraped TEXT
        );

        -- v2: Thematic topic clusters
        CREATE TABLE IF NOT EXISTS topic_clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_name TEXT NOT NULL,
            theme TEXT,
            topics_json TEXT NOT NULL,
            priority_score REAL DEFAULT 0.0,
            topics_used INTEGER DEFAULT 0,
            topics_total INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- v2: Episodic content series
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_name TEXT NOT NULL UNIQUE,
            series_description TEXT,
            character_id TEXT,
            cluster_id INTEGER,
            target_episodes INTEGER DEFAULT 10,
            produced_episodes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            FOREIGN KEY (cluster_id) REFERENCES topic_clusters(id)
        );

        -- v2: Episodes within a series
        CREATE TABLE IF NOT EXISTS series_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            episode_number INTEGER NOT NULL,
            topic TEXT NOT NULL,
            title TEXT,
            description TEXT,
            continuity_notes TEXT,
            video_db_id INTEGER,
            status TEXT DEFAULT 'planned',
            FOREIGN KEY (series_id) REFERENCES series(id),
            FOREIGN KEY (video_db_id) REFERENCES videos(id)
        );

        -- v2: Thumbnail A/B variants
        CREATE TABLE IF NOT EXISTS thumbnail_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_db_id INTEGER NOT NULL,
            variant_index INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            description TEXT,
            is_active INTEGER DEFAULT 0,
            ctr_at_activation REAL,
            activated_at TEXT,
            FOREIGN KEY (video_db_id) REFERENCES videos(id)
        );

        -- v2: Upload time performance tracking
        CREATE TABLE IF NOT EXISTS upload_time_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_db_id INTEGER NOT NULL,
            upload_hour INTEGER NOT NULL,
            day_of_week TEXT NOT NULL,
            views_48h INTEGER DEFAULT 0,
            ctr_48h REAL DEFAULT 0.0,
            FOREIGN KEY (video_db_id) REFERENCES videos(id)
        );

        CREATE INDEX IF NOT EXISTS idx_videos_video_id ON videos(video_id);
        CREATE INDEX IF NOT EXISTS idx_videos_category ON videos(category);
        CREATE INDEX IF NOT EXISTS idx_metrics_video_id ON metrics(video_id);
        CREATE INDEX IF NOT EXISTS idx_playlists_category ON playlists(category, language);
        CREATE INDEX IF NOT EXISTS idx_quota_provider_date ON quota_usage(provider, date);
        CREATE INDEX IF NOT EXISTS idx_trend_topics_score ON trend_topics(trend_score DESC);
        CREATE INDEX IF NOT EXISTS idx_series_status ON series(status);
        CREATE INDEX IF NOT EXISTS idx_series_episodes_status ON series_episodes(status);
    """)

    _migrate_db(conn)
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


# --- DB Migration ---

def _migrate_db(conn: sqlite3.Connection):
    """Add new columns to existing tables if they don't exist."""
    existing = [row[1] for row in conn.execute("PRAGMA table_info(metrics)").fetchall()]
    if "avg_view_percentage" not in existing:
        conn.execute("ALTER TABLE metrics ADD COLUMN avg_view_percentage REAL DEFAULT 0.0")
    if "subscribers_gained" not in existing:
        conn.execute("ALTER TABLE metrics ADD COLUMN subscribers_gained INTEGER DEFAULT 0")


# --- Category Weights (v2) ---

def upsert_category_weight(category: str, weight: float, total_videos: int = 0,
                           avg_ctr: float = 0.0, avg_views: float = 0.0):
    """Insert or update a category weight."""
    conn = get_connection()
    now = datetime.now().isoformat()
    existing = conn.execute(
        "SELECT id FROM category_weights WHERE category = ?", (category,)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE category_weights SET weight = ?, total_videos = ?,
               avg_ctr = ?, avg_views = ?, computed_at = ? WHERE id = ?""",
            (weight, total_videos, avg_ctr, avg_views, now, existing["id"])
        )
    else:
        conn.execute(
            """INSERT INTO category_weights (category, weight, total_videos, avg_ctr, avg_views, computed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (category, weight, total_videos, avg_ctr, avg_views, now)
        )

    conn.commit()
    conn.close()


def get_category_weights() -> list:
    """Get all category weights, sorted by weight descending."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM category_weights ORDER BY weight DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Trend Topics (v2) ---

def insert_trend_topic(topic: str, category: str, trend_score: float, source: str) -> int:
    """Insert a trending topic."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO trend_topics (topic, category, trend_score, source, discovered_at)
           VALUES (?, ?, ?, ?, ?)""",
        (topic, category, trend_score, source, datetime.now().isoformat())
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_unused_trend_topics(limit: int = 20) -> list:
    """Get unused trending topics, sorted by score."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trend_topics WHERE used = 0 ORDER BY trend_score DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_trend_topic_used(topic_id: int):
    """Mark a trending topic as used."""
    conn = get_connection()
    conn.execute("UPDATE trend_topics SET used = 1 WHERE id = ?", (topic_id,))
    conn.commit()
    conn.close()


def clear_old_trend_topics(days_old: int = 7):
    """Remove trend topics older than N days."""
    cutoff = (datetime.now() - timedelta(days=days_old)).isoformat()
    conn = get_connection()
    conn.execute("DELETE FROM trend_topics WHERE discovered_at < ?", (cutoff,))
    conn.commit()
    conn.close()


# --- Competitor Channels (v2) ---

def upsert_competitor_channel(channel_id: str, channel_name: str, avg_views: float = 0.0):
    """Insert or update a competitor channel."""
    conn = get_connection()
    now = datetime.now().isoformat()
    existing = conn.execute(
        "SELECT id FROM competitor_channels WHERE channel_id = ?", (channel_id,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE competitor_channels SET channel_name = ?, avg_views = ?, last_scraped = ? WHERE id = ?",
            (channel_name, avg_views, now, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO competitor_channels (channel_id, channel_name, avg_views, last_scraped) VALUES (?, ?, ?, ?)",
            (channel_id, channel_name, avg_views, now)
        )

    conn.commit()
    conn.close()


def get_competitor_channels() -> list:
    """Get all tracked competitor channels."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM competitor_channels").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Topic Clusters (v2) ---

def insert_topic_cluster(cluster_name: str, theme: str, topics: list,
                         priority_score: float = 0.0) -> int:
    """Insert a new topic cluster."""
    conn = get_connection()
    now = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO topic_clusters (cluster_name, theme, topics_json, priority_score,
           topics_used, topics_total, created_at, updated_at)
           VALUES (?, ?, ?, ?, 0, ?, ?, ?)""",
        (cluster_name, theme, json.dumps(topics), priority_score, len(topics), now, now)
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_active_clusters() -> list:
    """Get clusters that still have unused topics."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM topic_clusters
           WHERE topics_used < topics_total
           ORDER BY priority_score DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def increment_cluster_usage(cluster_id: int):
    """Increment the topics_used count for a cluster."""
    conn = get_connection()
    conn.execute(
        "UPDATE topic_clusters SET topics_used = topics_used + 1, updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(), cluster_id)
    )
    conn.commit()
    conn.close()


def clear_clusters():
    """Clear all topic clusters for regeneration."""
    conn = get_connection()
    conn.execute("DELETE FROM topic_clusters")
    conn.commit()
    conn.close()


# --- Series (v2) ---

def insert_series(series_name: str, series_description: str, character_id: str = None,
                  cluster_id: int = None, target_episodes: int = 10) -> int:
    """Insert a new content series."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO series (series_name, series_description, character_id, cluster_id,
           target_episodes, produced_episodes, status, created_at)
           VALUES (?, ?, ?, ?, ?, 0, 'active', ?)""",
        (series_name, series_description, character_id, cluster_id,
         target_episodes, datetime.now().isoformat())
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def insert_series_episode(series_id: int, episode_number: int, topic: str,
                          title: str = None, description: str = None,
                          continuity_notes: str = None) -> int:
    """Insert a series episode."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO series_episodes (series_id, episode_number, topic, title,
           description, continuity_notes, status)
           VALUES (?, ?, ?, ?, ?, ?, 'planned')""",
        (series_id, episode_number, topic, title, description, continuity_notes)
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_active_series() -> list:
    """Get all active series."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM series WHERE status = 'active' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_next_planned_episode(series_id: int) -> dict:
    """Get the next planned (unproduced) episode for a series."""
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM series_episodes
           WHERE series_id = ? AND status = 'planned'
           ORDER BY episode_number ASC LIMIT 1""",
        (series_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_episode_produced(episode_id: int, video_db_id: int):
    """Mark an episode as produced and link it to a video."""
    conn = get_connection()
    conn.execute(
        "UPDATE series_episodes SET status = 'produced', video_db_id = ? WHERE id = ?",
        (video_db_id, episode_id)
    )
    # Also increment produced_episodes count on the series
    conn.execute(
        """UPDATE series SET produced_episodes = produced_episodes + 1
           WHERE id = (SELECT series_id FROM series_episodes WHERE id = ?)""",
        (episode_id,)
    )
    conn.commit()
    conn.close()


def get_series_by_name(series_name: str) -> dict:
    """Get a series by name."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM series WHERE series_name = ?", (series_name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# --- Thumbnail Variants (v2) ---

def insert_thumbnail_variant(video_db_id: int, variant_index: int,
                             file_path: str, description: str = None,
                             is_active: bool = False) -> int:
    """Insert a thumbnail variant."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO thumbnail_variants (video_db_id, variant_index, file_path,
           description, is_active, activated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (video_db_id, variant_index, file_path, description,
         1 if is_active else 0, datetime.now().isoformat() if is_active else None)
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_thumbnail_variants(video_db_id: int) -> list:
    """Get all thumbnail variants for a video."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM thumbnail_variants WHERE video_db_id = ? ORDER BY variant_index",
        (video_db_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def activate_thumbnail_variant(variant_id: int, ctr_at_activation: float = None):
    """Mark a thumbnail variant as active."""
    conn = get_connection()
    # Deactivate all other variants for this video
    video_db_id = conn.execute(
        "SELECT video_db_id FROM thumbnail_variants WHERE id = ?", (variant_id,)
    ).fetchone()
    if video_db_id:
        conn.execute(
            "UPDATE thumbnail_variants SET is_active = 0 WHERE video_db_id = ?",
            (video_db_id["video_db_id"],)
        )
    conn.execute(
        "UPDATE thumbnail_variants SET is_active = 1, ctr_at_activation = ?, activated_at = ? WHERE id = ?",
        (ctr_at_activation, datetime.now().isoformat(), variant_id)
    )
    conn.commit()
    conn.close()


# --- Upload Time Slots (v2) ---

def insert_upload_time_slot(video_db_id: int, upload_hour: int, day_of_week: str):
    """Record when a video was uploaded for time optimization."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO upload_time_slots (video_db_id, upload_hour, day_of_week) VALUES (?, ?, ?)",
        (video_db_id, upload_hour, day_of_week)
    )
    conn.commit()
    conn.close()


def update_upload_time_metrics(video_db_id: int, views_48h: int, ctr_48h: float):
    """Update 48h metrics for an upload time slot."""
    conn = get_connection()
    conn.execute(
        "UPDATE upload_time_slots SET views_48h = ?, ctr_48h = ? WHERE video_db_id = ?",
        (views_48h, ctr_48h, video_db_id)
    )
    conn.commit()
    conn.close()


def get_upload_time_stats() -> list:
    """Get aggregated performance stats by upload hour."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT upload_hour, day_of_week,
           COUNT(*) as total_videos,
           AVG(views_48h) as avg_views,
           AVG(ctr_48h) as avg_ctr
           FROM upload_time_slots
           WHERE views_48h > 0
           GROUP BY upload_hour, day_of_week
           ORDER BY avg_views DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
