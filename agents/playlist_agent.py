"""
Playlist & Series automation for YouTube.
Auto-creates playlists by category and adds videos to them.
"""

from agents.db import get_playlist, insert_playlist, increment_playlist_count, get_connection


def _get_youtube_service(config: dict):
    """Get authenticated YouTube API service."""
    from agents.upload_agent import get_authenticated_service
    return get_authenticated_service(config)


def get_or_create_playlist(config: dict, category: str, language: str) -> str:
    """Get existing playlist or create a new one for the given category + language.

    Returns the YouTube playlist ID.
    """
    # Check database first
    existing = get_playlist(category, language)
    if existing:
        return existing["playlist_id"]

    # Check if we should auto-create
    playlist_config = config.get("playlists", {})
    if not playlist_config.get("auto_create", True):
        return None

    # Check minimum video threshold
    min_videos = playlist_config.get("min_videos_for_playlist", 3)
    conn = get_connection()
    video_count = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE category = ? AND language = ? AND platform = 'youtube'",
        (category, language)
    ).fetchone()[0]
    conn.close()

    if video_count < min_videos:
        print(f"  Playlist skipped: only {video_count}/{min_videos} videos in '{category}' ({language})")
        return None

    # Create playlist via YouTube API
    naming_template = playlist_config.get(
        "naming_template", "{category} for Kids - {language}"
    )
    playlist_title = naming_template.format(category=category.title(), language=language)

    youtube = _get_youtube_service(config)

    body = {
        "snippet": {
            "title": playlist_title,
            "description": f"A collection of fun and educational {category} videos for kids!",
        },
        "status": {
            "privacyStatus": "public",
        },
    }

    response = youtube.playlists().insert(
        part="snippet,status",
        body=body,
    ).execute()

    playlist_id = response["id"]
    print(f"  Created playlist: {playlist_title} ({playlist_id})")

    # Store in database
    insert_playlist(
        playlist_id=playlist_id,
        platform="youtube",
        language=language,
        category=category,
        title=playlist_title,
    )

    # Add existing videos in this category to the playlist
    conn = get_connection()
    existing_videos = conn.execute(
        """SELECT video_id FROM videos
           WHERE category = ? AND language = ? AND platform = 'youtube'
           AND video_id IS NOT NULL""",
        (category, language)
    ).fetchall()
    conn.close()

    for row in existing_videos:
        try:
            add_to_playlist(config, row["video_id"], playlist_id)
        except Exception as e:
            print(f"  Warning: Failed to add {row['video_id']} to playlist: {e}")

    return playlist_id


def add_to_playlist(config: dict, video_id: str, playlist_id: str):
    """Add a video to a YouTube playlist."""
    if not playlist_id or not video_id:
        return

    youtube = _get_youtube_service(config)

    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {
                "kind": "youtube#video",
                "videoId": video_id,
            },
        },
    }

    youtube.playlistItems().insert(
        part="snippet",
        body=body,
    ).execute()

    increment_playlist_count(playlist_id)
    print(f"  Added video {video_id} to playlist {playlist_id}")
