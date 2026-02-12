import os
import json
import httplib2
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from agents.rate_limiter import get_limiter


SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/youtube.force-ssl"]


def get_authenticated_service(config: dict):
    """Authenticate with YouTube API using OAuth 2.0."""
    token_file = config["youtube"]["token_file"]
    client_secrets = config["youtube"]["client_secrets_file"]

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secrets):
                raise FileNotFoundError(
                    f"Missing {client_secrets}. Download OAuth 2.0 credentials from "
                    "Google Cloud Console → APIs & Services → Credentials"
                )
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def _sanitize_tags(tags: list) -> list:
    """Clean tags for YouTube: remove special chars, max 10 tags, allow Unicode."""
    import re
    clean = []
    seen = set()
    for tag in tags:
        # Remove characters that YouTube rejects: < > " ' { } etc.
        tag = re.sub(r'[<>\"\'{}()\[\]@#$%^&*+=|\\~`]', '', tag)
        tag = re.sub(r'\s+', ' ', tag).strip()
        tag_lower = tag.lower()
        if 2 <= len(tag) <= 30 and tag_lower not in seen:
            clean.append(tag)
            seen.add(tag_lower)
        if len(clean) >= 10:
            break
    return clean


def upload_video(config: dict, video_path: str, metadata: dict,
                 thumbnail_path: str = None, publish_at: str = None) -> str:
    """Upload video to YouTube with metadata."""
    youtube = get_authenticated_service(config)

    # Clean title: remove characters YouTube rejects, keep Unicode
    import re
    clean_title = re.sub(r'[<>]', '', metadata["title"]).strip()[:100]
    clean_desc = re.sub(r'[<>]', '', metadata["description"]).strip()

    body = {
        "snippet": {
            "title": clean_title,
            "description": clean_desc,
            "tags": _sanitize_tags(metadata.get("tags", [])),
            "categoryId": config["youtube"]["category_id"],
        },
        "status": {
            "privacyStatus": config["youtube"]["privacy_status"],
            "selfDeclaredMadeForKids": config["youtube"]["made_for_kids"],
        },
    }

    # Schedule publish time if provided
    if publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at

    get_limiter("youtube").acquire()
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    print(f"  Title: {body['snippet']['title']}")
    print(f"  Tags: {body['snippet']['tags']}")
    print("  Uploading video...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"  Upload complete: {video_url}")

    # Upload thumbnail
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
            ).execute()
            print("  Thumbnail uploaded.")
        except Exception as e:
            print(f"  Warning: Thumbnail upload failed: {e}")

    return video_url, video_id


def upload_captions(config: dict, video_id: str, srt_path: str,
                    language: str = "en", name: str = "Auto-generated"):
    """Upload an SRT caption file to a YouTube video."""
    youtube = get_authenticated_service(config)

    # Map language names to ISO codes
    lang_codes = {"English": "en", "Hindi": "hi", "en": "en", "hi": "hi"}
    lang_code = lang_codes.get(language, language)

    body = {
        "snippet": {
            "videoId": video_id,
            "language": lang_code,
            "name": name,
        }
    }

    media = MediaFileUpload(srt_path, mimetype="application/x-subrip")

    try:
        get_limiter("youtube").acquire()
        youtube.captions().insert(
            part="snippet",
            body=body,
            media_body=media,
        ).execute()
        print(f"  Captions uploaded ({lang_code})")
    except Exception as e:
        print(f"  Warning: Caption upload failed: {e}")
