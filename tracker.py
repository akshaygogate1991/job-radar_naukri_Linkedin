"""
tracker.py
──────────
Logs every job application to:
  - applications.csv  (easy to open in Excel / Google Sheets)
  - applications.json (for the bot to check "already applied?")
"""

import csv
import json
import os
from datetime import datetime

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.profile import LOG_FILE, SHEETS_LOG, SEARCH


def _load_json_log() -> list:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    return []


def _save_json_log(data: list):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def already_applied(company: str, job_title: str) -> bool:
    """Check if we applied to this company+role within the cooldown window."""
    log = _load_json_log()
    cutoff_days = SEARCH["skip_if_applied_within_days"]
    for entry in log:
        if (entry["company"].lower() == company.lower() and
                entry["job_title"].lower() == job_title.lower()):
            applied_date = datetime.fromisoformat(entry["date"])
            days_ago = (datetime.now() - applied_date).days
            if days_ago < cutoff_days:
                return True
    return False


def log_application(
    platform:     str,
    company:      str,
    job_title:    str,
    job_url:      str,
    match_score:  int,
    status:       str = "Applied",   # Applied / Skipped / Failed
    notes:        str = ""
):
    """Log one job application."""
    entry = {
        "date":        datetime.now().isoformat(),
        "platform":    platform,
        "company":     company,
        "job_title":   job_title,
        "job_url":     job_url,
        "match_score": match_score,
        "status":      status,
        "notes":       notes,
    }

    # ── JSON log ──────────────────────────────────────────────
    log = _load_json_log()
    log.append(entry)
    _save_json_log(log)

    # ── CSV log ───────────────────────────────────────────────
    os.makedirs(os.path.dirname(SHEETS_LOG), exist_ok=True)
    file_exists = os.path.exists(SHEETS_LOG)
    with open(SHEETS_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=entry.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(entry)

    print(f"  [{status}] {company} — {job_title} (score: {match_score})")


def get_todays_summary() -> dict:
    """Returns count of today's applications per platform."""
    log = _load_json_log()
    today = datetime.now().date().isoformat()
    summary = {"linkedin": 0, "naukri": 0, "hirist": 0, "total": 0, "applied": [], "skipped": 0}

    for entry in log:
        if entry["date"].startswith(today):
            if entry["status"] == "Applied":
                p = entry.get("platform", "other")
                summary[p] = summary.get(p, 0) + 1
                summary["total"] += 1
                summary["applied"].append({
                    "company":    entry["company"],
                    "job_title":  entry["job_title"],
                    "score":      entry["match_score"],
                    "url":        entry["job_url"],
                })
            elif entry["status"] == "Skipped":
                summary["skipped"] += 1

    return summary


def get_all_stats() -> dict:
    """Overall stats across all time."""
    log = _load_json_log()
    total     = len([e for e in log if e["status"] == "Applied"])
    skipped   = len([e for e in log if e["status"] == "Skipped"])
    failed    = len([e for e in log if e["status"] == "Failed"])
    platforms = {}
    for entry in log:
        p = entry["platform"]
        platforms[p] = platforms.get(p, 0) + (1 if entry["status"] == "Applied" else 0)
    return {
        "total_applied": total,
        "total_skipped": skipped,
        "total_failed":  failed,
        "by_platform":   platforms,
    }


if __name__ == "__main__":
    # Test the tracker
    log_application(
        platform="linkedin",
        company="Test Corp",
        job_title="Data Analyst",
        job_url="https://linkedin.com/jobs/test",
        match_score=82,
        status="Applied",
        notes="Test entry"
    )
    print("\nToday's summary:", get_todays_summary())
    print("All-time stats: ", get_all_stats())
