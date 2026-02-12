import time
import requests


GRAPH_API_BASE = "https://graph.facebook.com"


def _upload_to_temp_host(video_path: str) -> str:
    """Upload video to a temporary file host and return a public URL.

    Uses tmpfiles.org (free, no auth, files persist ~1 hour).
    Instagram only needs the URL long enough to fetch the video.
    """
    with open(video_path, "rb") as f:
        response = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": f},
            timeout=300,
        )
    response.raise_for_status()
    data = response.json()

    # tmpfiles.org returns URL like https://tmpfiles.org/12345/video.mp4
    # Direct download requires /dl/ segment: https://tmpfiles.org/dl/12345/video.mp4
    url = data["data"]["url"]
    direct_url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
    return direct_url


def _wait_for_container(container_id: str, access_token: str,
                        api_version: str, max_retries: int = 60,
                        poll_interval: int = 5) -> str:
    """Poll the media container until it finishes processing or errors out."""
    url = f"{GRAPH_API_BASE}/{api_version}/{container_id}"
    params = {
        "fields": "status_code,status",
        "access_token": access_token,
    }

    for attempt in range(max_retries):
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        status_code = data.get("status_code")

        if status_code == "FINISHED":
            print(f"  Instagram: container ready (took ~{attempt * poll_interval}s)")
            return status_code
        elif status_code == "ERROR":
            error_msg = data.get("status", "Unknown error during processing")
            raise Exception(f"Instagram container processing failed: {error_msg}")

        # Still IN_PROGRESS
        time.sleep(poll_interval)

    raise Exception(f"Instagram container timed out after {max_retries * poll_interval}s")


def upload_reel(config: dict, video_path: str, caption: str,
                thumbnail_path: str = None) -> str:
    """Upload a video as an Instagram Reel using the official Graph API.

    Flow:
    1. Upload video to temporary public host
    2. Create media container (REELS type)
    3. Poll until container is ready
    4. Publish the container
    """
    ig_config = config["instagram"]
    ig_user_id = ig_config["ig_user_id"]
    access_token = ig_config["access_token"]
    api_version = ig_config.get("graph_api_version", "v21.0")

    # Step 1: Get a public URL for the video
    print("  Instagram: uploading video to temp host...")
    video_url = _upload_to_temp_host(video_path)
    print(f"  Instagram: temp URL obtained")

    # Step 2: Create media container
    create_url = f"{GRAPH_API_BASE}/{api_version}/{ig_user_id}/media"
    create_params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true",
        "access_token": access_token,
    }

    response = requests.post(create_url, data=create_params, timeout=60)
    response.raise_for_status()
    container_id = response.json()["id"]
    print(f"  Instagram: container created ({container_id})")

    # Step 3: Wait for processing
    print("  Instagram: waiting for video processing...")
    _wait_for_container(container_id, access_token, api_version)

    # Step 4: Publish
    publish_url = f"{GRAPH_API_BASE}/{api_version}/{ig_user_id}/media_publish"
    publish_params = {
        "creation_id": container_id,
        "access_token": access_token,
    }

    response = requests.post(publish_url, data=publish_params, timeout=60)
    response.raise_for_status()
    media_id = response.json()["id"]

    # Get the permalink
    permalink_url = f"{GRAPH_API_BASE}/{api_version}/{media_id}"
    permalink_params = {
        "fields": "permalink",
        "access_token": access_token,
    }
    permalink_response = requests.get(permalink_url, params=permalink_params, timeout=30)
    if permalink_response.ok:
        reel_url = permalink_response.json().get("permalink", f"https://www.instagram.com/reel/{media_id}/")
    else:
        reel_url = f"https://www.instagram.com/reel/{media_id}/"

    print(f"  Instagram Reel published: {reel_url}")
    return reel_url


def build_reel_caption(metadata: dict, language: str = "English",
                       ig_metadata: dict = None) -> str:
    """Build an Instagram Reel caption from Instagram-specific or YouTube metadata.

    If ig_metadata is provided (from generate_instagram_metadata), uses the
    Instagram-optimized caption and hashtags. Otherwise falls back to YouTube metadata.
    """
    if ig_metadata:
        caption = ig_metadata["caption"]
        hashtags = ig_metadata.get("hashtags", [])
        hashtag_str = " ".join(
            f"#{h.lstrip('#').replace(' ', '')}" for h in hashtags[:30]
        )
        full_caption = f"{caption}\n\n.\n.\n.\n{hashtag_str}"
    else:
        title = metadata["title"]
        description = metadata["description"]
        tags = metadata.get("tags", [])
        hashtags = " ".join(f"#{tag.replace(' ', '')}" for tag in tags[:15])
        full_caption = f"{title}\n\n{description}\n\n{hashtags}"

    # Instagram caption limit is 2200 chars
    if len(full_caption) > 2200:
        full_caption = full_caption[:2197] + "..."

    return full_caption
