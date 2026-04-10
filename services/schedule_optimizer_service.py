"""
Upload Schedule Optimizer — tests different upload time slots and
identifies optimal publishing times based on performance data.
"""

from datetime import datetime

from agents.db import (
    insert_upload_time_slot, update_upload_time_metrics,
    get_upload_time_stats, get_connection,
)


def record_upload_time(video_db_id: int):
    """Record when a video was uploaded for later time-performance correlation."""
    now = datetime.now()
    upload_hour = now.hour
    day_of_week = now.strftime("%A")  # Monday, Tuesday, etc.

    insert_upload_time_slot(video_db_id, upload_hour, day_of_week)


def get_optimal_upload_time(config: dict) -> dict:
    """Analyze upload_time_slots to find the best upload time.

    Correlates upload hour/day with 48h views and CTR.
    Returns: {"best_hour": int, "best_day": str, "confidence": float,
              "stats": list, "recommendation": str}
    """
    min_data = config.get("schedule", {}).get("min_data_for_optimization", 20)

    stats = get_upload_time_stats()

    # Check total data points
    total_videos = sum(s["total_videos"] for s in stats)
    if total_videos < min_data:
        return {
            "best_hour": None,
            "best_day": None,
            "confidence": 0.0,
            "stats": stats,
            "recommendation": f"Not enough data ({total_videos}/{min_data} videos). "
                              "Continue uploading at varied times to gather data.",
        }

    if not stats:
        return {
            "best_hour": None,
            "best_day": None,
            "confidence": 0.0,
            "stats": [],
            "recommendation": "No upload time data available yet.",
        }

    # Find best hour (by average views)
    hour_stats = {}
    for s in stats:
        hour = s["upload_hour"]
        if hour not in hour_stats:
            hour_stats[hour] = {"total_views": 0, "total_ctr": 0, "count": 0}
        hour_stats[hour]["total_views"] += s["avg_views"] * s["total_videos"]
        hour_stats[hour]["total_ctr"] += s["avg_ctr"] * s["total_videos"]
        hour_stats[hour]["count"] += s["total_videos"]

    best_hour = max(hour_stats.items(),
                    key=lambda x: x[1]["total_views"] / max(x[1]["count"], 1))

    # Find best day
    day_stats = {}
    for s in stats:
        day = s["day_of_week"]
        if day not in day_stats:
            day_stats[day] = {"total_views": 0, "count": 0}
        day_stats[day]["total_views"] += s["avg_views"] * s["total_videos"]
        day_stats[day]["count"] += s["total_videos"]

    best_day = max(day_stats.items(),
                   key=lambda x: x[1]["total_views"] / max(x[1]["count"], 1))

    # Confidence: based on data volume (0-1)
    confidence = min(total_videos / (min_data * 3), 1.0)

    best_hour_num = best_hour[0]
    best_day_name = best_day[0]

    return {
        "best_hour": best_hour_num,
        "best_day": best_day_name,
        "confidence": round(confidence, 2),
        "stats": stats,
        "recommendation": f"Best upload time: {best_day_name} at {best_hour_num}:00 "
                          f"(confidence: {confidence*100:.0f}%)",
    }


def backfill_upload_time_metrics(config: dict):
    """For videos with upload time records, fetch and store their 48h metrics.

    This updates the upload_time_slots table with actual performance data.
    """
    conn = get_connection()
    slots = conn.execute(
        """SELECT uts.video_db_id, v.video_id
           FROM upload_time_slots uts
           JOIN videos v ON uts.video_db_id = v.id
           WHERE uts.views_48h = 0
           AND v.video_id IS NOT NULL"""
    ).fetchall()
    conn.close()

    if not slots:
        print("  No upload time slots need metrics backfill.")
        return

    from agents.db import get_latest_metrics

    updated = 0
    for slot in slots:
        metrics = get_latest_metrics(slot["video_id"])
        if metrics and metrics.get("views", 0) > 0:
            update_upload_time_metrics(
                slot["video_db_id"],
                views_48h=metrics.get("views", 0),
                ctr_48h=metrics.get("ctr", 0.0),
            )
            updated += 1

    print(f"  Backfilled metrics for {updated}/{len(slots)} upload time slots.")
