"""
dashboard_store.py
──────────────────
Persistent store for the "Manual Apply" dashboard.

Why this exists:
  - notifier.py rebuilds manual_digest.json fresh on EVERY run (clear_digest),
    so it only ever holds the latest run's jobs.
  - This store ACCUMULATES every manual-apply job across all runs into one
    file: logs/dashboard_jobs.json — deduped by job URL.
  - Each job has a status: "pending" (still to apply) or "applied".
  - When you click "Mark Applied" in the dashboard, the job is set to
    "applied" and never shows in the To-Apply list again.

Safety:
  - Writes are ATOMIC (temp file + os.replace) and keep a .bak backup, so a
    read happening at the same time can never see a half-written file.
  - Obvious test/junk records are filtered out on load and purged on next save.

Nothing here deletes or changes your existing logs. It only ADDS a new file.
"""

import os
import json
import shutil
from datetime import datetime

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_DIR    = os.path.join(BASE_DIR, "logs")
STORE_FILE = os.path.join(LOG_DIR, "dashboard_jobs.json")
BAK_FILE   = STORE_FILE + ".bak"

DIGEST_FILE = os.path.join(LOG_DIR, "manual_digest.json")
APPS_FILE   = os.path.join(LOG_DIR, "applications.json")

# ── junk / test-record filter ────────────────────────────────────
_TEST_COMPANIES = {"spyco", "wirecheck ltd", "zz test co", "finalco", "test corp"}
_TEST_DOMAINS   = ("ex.com", "example.com")


def _is_junk(url: str, rec: dict) -> bool:
    u = (url or "").lower()
    if any(dom in u for dom in _TEST_DOMAINS):
        return True
    if (rec.get("company", "") or "").strip().lower() in _TEST_COMPANIES:
        return True
    return False


# ── low level load / save ────────────────────────────────────────
def _read_file(path: str):
    """Return parsed JSON dict, or None if unreadable/corrupt."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load() -> dict:
    """
    Load the store, dropping junk records. Never returns partial/empty data
    silently: if the main file is corrupt, fall back to the .bak backup.
    """
    data = _read_file(STORE_FILE)
    if data is None:                      # corrupt / mid-write → try backup
        data = _read_file(BAK_FILE)
    if not isinstance(data, dict):
        data = {}
    # strip junk test records
    clean = {u: v for u, v in data.items() if not _is_junk(u, v)}
    return clean


def _save(data: dict):
    """Atomic write + backup, so concurrent readers never see a half file."""
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = STORE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # keep previous good copy as backup
    if os.path.exists(STORE_FILE):
        try:
            shutil.copy2(STORE_FILE, BAK_FILE)
        except Exception:
            pass
    os.replace(tmp, STORE_FILE)           # atomic on Windows & Linux


# ── public API ───────────────────────────────────────────────────
def add_job(platform: str, title: str, company: str, url: str,
            score: int = 0, cover_letter: str = "", summary: str = "",
            notes: str = "") -> None:
    """Add a manual-apply job. Deduped by URL. Never overwrites status."""
    if not url:
        return
    data = _load()
    existing = data.get(url)
    if existing:
        if cover_letter and not existing.get("cover_letter"):
            existing["cover_letter"] = cover_letter
        if summary and not existing.get("summary"):
            existing["summary"] = summary
        if score and not existing.get("score"):
            existing["score"] = score
        data[url] = existing
    else:
        data[url] = {
            "title":        title,
            "company":      company,
            "platform":     platform,
            "url":          url,
            "score":        score or 0,
            "cover_letter": cover_letter or "",
            "summary":      summary or "",
            "notes":        notes or "",
            "first_seen":   datetime.now().isoformat(),
            "status":       "pending",
            "applied_at":   "",
        }
    _save(data)


def mark_applied(url: str) -> None:
    data = _load()
    if url in data:
        data[url]["status"] = "applied"
        data[url]["applied_at"] = datetime.now().isoformat()
        _save(data)


def mark_pending(url: str) -> None:
    """Undo an accidental 'applied' / 'closed' / 'discarded'."""
    data = _load()
    if url in data:
        data[url]["status"] = "pending"
        data[url]["applied_at"] = ""
        _save(data)


def set_status(url: str, status: str) -> None:
    """
    Set any status: 'pending' | 'applied' | 'closed' | 'discarded'.
      closed    = the job opening is no longer open
      discarded = not relevant to my profile ("removed")
    We keep the row rather than deleting it, so the next scrape/sync can't
    re-add the same job as new.
    """
    data = _load()
    if url in data:
        data[url]["status"] = status
        if status == "applied":
            data[url]["applied_at"] = datetime.now().isoformat()
        elif status == "pending":
            data[url]["applied_at"] = ""
        _save(data)


def all_jobs() -> list:
    """Return all jobs as a list of dicts."""
    return list(_load().values())


def purge_junk() -> int:
    """Physically remove junk/test records from disk. Returns count removed."""
    raw = _read_file(STORE_FILE)
    if not isinstance(raw, dict):
        return 0
    clean = {u: v for u, v in raw.items() if not _is_junk(u, v)}
    removed = len(raw) - len(clean)
    if removed:
        _save(clean)
    return removed


def stats() -> dict:
    jobs = all_jobs()
    pending = [j for j in jobs if j.get("status") == "pending"]
    applied = [j for j in jobs if j.get("status") == "applied"]
    by_platform = {}
    for j in pending:
        p = j.get("platform", "other")
        by_platform[p] = by_platform.get(p, 0) + 1
    return {
        "total":       len(jobs),
        "pending":     len(pending),
        "applied":     len(applied),
        "by_platform": by_platform,
    }


# ── one-time seeding from existing logs ──────────────────────────
def seed_from_existing(verbose: bool = True) -> dict:
    """
    Import jobs already sitting in your logs into the store:
      1. manual_digest.json  → richest (has cover letter + summary)
      2. applications.json 'Manual' rows → historical manual-apply jobs
      3. applications.json 'Applied' rows → auto-mark those URLs as applied
    Safe to run repeatedly (deduped by URL, never resets status).
    """
    added = 0

    if os.path.exists(DIGEST_FILE):
        try:
            digest = json.load(open(DIGEST_FILE, "r", encoding="utf-8"))
            for platform, jobs in digest.items():
                for j in jobs:
                    before = _load()
                    add_job(
                        platform=platform,
                        title=j.get("title", ""),
                        company=j.get("company", ""),
                        url=j.get("url", ""),
                        score=j.get("score", 0),
                        cover_letter=j.get("cover_letter", ""),
                        summary=j.get("summary", ""),
                        notes="",
                    )
                    if j.get("url") and j.get("url") not in before:
                        added += 1
        except Exception as e:
            if verbose:
                print("digest seed skipped:", e)

    if os.path.exists(APPS_FILE):
        try:
            apps = json.load(open(APPS_FILE, "r", encoding="utf-8"))
            for row in apps:
                status = row.get("status", "")
                url = row.get("job_url", "")
                if not url:
                    continue
                # Manual = "apply on company website" jobs (LinkedIn/Naukri).
                # Hirist Failed = matched jobs the bot couldn't auto-apply to →
                # they belong in the manual dashboard so you can apply by hand.
                is_manual = (status == "Manual")
                is_hirist_failed = (status == "Failed"
                                    and row.get("platform") == "hirist")
                if is_manual or is_hirist_failed:
                    before = _load()
                    add_job(
                        platform=row.get("platform", ""),
                        title=row.get("job_title", ""),
                        company=row.get("company", ""),
                        url=url,
                        score=row.get("match_score", 0),
                        notes=row.get("notes", ""),
                    )
                    if url not in before:
                        added += 1
            applied_urls = {r.get("job_url") for r in apps
                            if r.get("status") == "Applied" and r.get("job_url")}
            data = _load()
            for url in applied_urls:
                if url in data and data[url]["status"] != "applied":
                    data[url]["status"] = "applied"
                    data[url]["applied_at"] = data[url].get("applied_at") or "auto (bot log)"
            _save(data)
        except Exception as e:
            if verbose:
                print("applications seed skipped:", e)

    s = stats()
    if verbose:
        print(f"Seed complete. Added ~{added} new. "
              f"Total {s['total']} | pending {s['pending']} | applied {s['applied']}")
    return s


if __name__ == "__main__":
    removed = purge_junk()
    print(f"Purged {removed} junk records.")
    seed_from_existing()
