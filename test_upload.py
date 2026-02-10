"""Test upload: uploads the last generated video to YouTube as PRIVATE."""

import os
import json
import yaml

from agents.upload_agent import upload_video

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_latest_output():
    output_dir = os.path.join(BASE_DIR, "output")
    runs = sorted(os.listdir(output_dir), reverse=True)
    for run in runs:
        run_path = os.path.join(output_dir, run)
        video = os.path.join(run_path, "final_video.mp4")
        metadata_file = os.path.join(run_path, "metadata.json")
        if os.path.exists(video):
            return run_path, video, metadata_file
    raise FileNotFoundError("No generated video found in output/")


if __name__ == "__main__":
    # Load config
    with open(os.path.join(BASE_DIR, "config.yaml")) as f:
        config = yaml.safe_load(f)

    # Override to PRIVATE for testing
    config["youtube"]["privacy_status"] = "private"

    run_path, video_path, metadata_file = get_latest_output()
    print(f"Latest run: {run_path}")
    print(f"Video: {video_path}")

    # Load metadata
    if os.path.exists(metadata_file):
        with open(metadata_file) as f:
            metadata = json.load(f)
    else:
        metadata = {
            "title": "[TEST] Kids Video Upload",
            "description": "Test upload from automation pipeline",
            "tags": ["test", "kids", "education"],
        }

    thumbnail_path = os.path.join(run_path, "thumbnail.png")
    if not os.path.exists(thumbnail_path):
        thumbnail_path = None

    print(f"Title: {metadata['title']}")
    print(f"Privacy: PRIVATE (safe test)")
    print()

    url = upload_video(config, video_path, metadata, thumbnail_path)
    print(f"\nVideo uploaded: {url}")
    print("(Video is PRIVATE - only you can see it)")
