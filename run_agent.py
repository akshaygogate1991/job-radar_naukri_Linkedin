"""
run_agent.py
────────────
Master runner for the Job Application Agent.

Flow:
  1. Check if already ran today (prevents double runs)
  2. Run LinkedIn bot
  3. Run Naukri bot
  4. Run Hirist bot  ← NEW
  5. Send email summary + manual apply digest
  6. Log completion

Run manually anytime:
  python run_agent.py
"""

import os
import sys
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.profile import SEARCH, PLATFORMS
from notifier import send_telegram_message, send_daily_summary, send_error_alert, send_manual_digest, clear_digest
from tracker import get_todays_summary

# ── Lock file to prevent double runs ─────────────────────────
LOCK_FILE = os.path.join(os.path.dirname(__file__), "logs", "last_run.json")


def already_ran_today() -> bool:
    """Returns True if agent already ran successfully today."""
    if not os.path.exists(LOCK_FILE):
        return False
    try:
        with open(LOCK_FILE, "r") as f:
            data = json.load(f)
        last_run = data.get("date", "")
        return last_run == datetime.now().date().isoformat()
    except Exception:
        return False


def mark_run_complete(li_count: int, nk_count: int, hr_count: int = 0):
    """Save today's completion record."""
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    with open(LOCK_FILE, "w") as f:
        json.dump({
            "date":           datetime.now().date().isoformat(),
            "time":           datetime.now().strftime("%H:%M:%S"),
            "linkedin_count": li_count,
            "naukri_count":   nk_count,
            "hirist_count":   hr_count,
            "total":          li_count + nk_count + hr_count,
        }, f, indent=2)


def main():
    print("=" * 55)
    print(f"  JOB AGENT STARTING — {datetime.now().strftime('%d %b %Y, %I:%M %p')}")
    print("=" * 55)

    # ── Guard: skip if already ran today ─────────────────────
    if already_ran_today():
        print("Agent already ran today. Exiting.")

    clear_digest()  # reset manual jobs list for this run
    linkedin_count = 0
    naukri_count   = 0
    hirist_count   = 0

    # ── Run LinkedIn bot ──────────────────────────────────────
    if PLATFORMS["linkedin"]["enabled"]:
        print("\n── LINKEDIN ──────────────────────────────────────────")
        try:
            from linkedin_bot import run_linkedin_bot
            linkedin_count = run_linkedin_bot() or 0
        except Exception as e:
            print(f"LinkedIn bot crashed: {e}")
            send_error_alert("linkedin", str(e))
    else:
        print("LinkedIn disabled in profile.py — skipping.")

    # ── Break between platforms ─────────────────────────────
    print("\nBreak between platforms (2 min)...")
    import time
    time.sleep(120)

    # ── Run Naukri bot ────────────────────────────────────────
    if PLATFORMS["naukri"]["enabled"]:
        print("\n── NAUKRI ────────────────────────────────────────────")
        try:
            from naukri_bot import run_naukri_bot
            naukri_count = run_naukri_bot() or 0
        except Exception as e:
            print(f"Naukri bot crashed: {e}")
            send_error_alert("naukri", str(e))
    else:
        print("Naukri disabled in profile.py — skipping.")

    # ── Break before Hirist ──────────────────────────────────
    print("\nBreak between platforms (2 min)...")
    time.sleep(120)

    # ── Run Hirist bot ────────────────────────────────────────
    if PLATFORMS.get("hirist", {}).get("enabled"):
        print("\n── HIRIST ────────────────────────────────────────────")
        try:
            from hirist_bot import run_hirist_bot
            hirist_count = run_hirist_bot() or 0
        except Exception as e:
            print(f"Hirist bot crashed: {e}")
            send_error_alert("hirist", str(e))
    else:
        print("Hirist disabled in profile.py — skipping.")

    # ── Mark complete & send summary ──────────────────────────
    mark_run_complete(linkedin_count, naukri_count, hirist_count)

    # Each wrapped so a failure here can NEVER skip the cloud sync below.
    try:
        send_manual_digest()   # grouped email: LinkedIn + Naukri + Hirist external jobs
    except Exception as _e:
        print(f"Manual digest email failed: {_e}")
    try:
        send_daily_summary()
    except Exception as _e:
        print(f"Daily summary email failed: {_e}")

    # Push today's jobs to Supabase so the phone dashboard stays in sync
    try:
        import sync_to_cloud
        sync_to_cloud.sync()
    except Exception as _e:
        print(f"Cloud sync skipped: {_e}")

    print("\n" + "=" * 55)
    print(f"  DONE — LinkedIn: {linkedin_count} | Naukri: {naukri_count} | Hirist: {hirist_count}")
    print("=" * 55)


if __name__ == "__main__":
    main()
