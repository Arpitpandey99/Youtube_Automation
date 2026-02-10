import os
import json
from instagrapi import Client
from instagrapi.exceptions import LoginRequired


def get_instagram_client(config: dict) -> Client:
    """Login to Instagram, reusing saved session if available."""
    cl = Client()
    ig_config = config["instagram"]
    session_file = ig_config["session_file"]

    # Try to load existing session
    if os.path.exists(session_file):
        try:
            cl.load_settings(session_file)
            cl.login(ig_config["username"], ig_config["password"])
            cl.get_timeline_feed()  # test if session is valid
            print("  Instagram: reused saved session")
            return cl
        except LoginRequired:
            print("  Instagram: saved session expired, logging in fresh...")
            # Delete stale session
            os.remove(session_file)
            cl = Client()
        except Exception as e:
            print(f"  Instagram: session load failed ({e}), logging in fresh...")
            cl = Client()

    # Fresh login
    cl.login(ig_config["username"], ig_config["password"])
    cl.dump_settings(session_file)
    print("  Instagram: logged in and session saved")
    return cl


def upload_reel(config: dict, video_path: str, caption: str,
                thumbnail_path: str = None) -> str:
    """Upload a video as an Instagram Reel."""
    cl = get_instagram_client(config)

    kwargs = {
        "path": video_path,
        "caption": caption,
    }
    if thumbnail_path and os.path.exists(thumbnail_path):
        kwargs["thumbnail"] = thumbnail_path

    media = cl.clip_upload(**kwargs)
    reel_url = f"https://www.instagram.com/reel/{media.code}/"
    print(f"  Instagram Reel uploaded: {reel_url}")
    return reel_url


def build_reel_caption(metadata: dict, language: str = "English") -> str:
    """Build an Instagram Reel caption from video metadata."""
    title = metadata["title"]
    description = metadata["description"]

    # Build hashtags from tags
    tags = metadata.get("tags", [])
    hashtags = " ".join(f"#{tag.replace(' ', '')}" for tag in tags[:15])

    caption = f"{title}\n\n{description}\n\n{hashtags}"

    # Instagram caption limit is 2200 chars
    if len(caption) > 2200:
        caption = caption[:2197] + "..."

    return caption
