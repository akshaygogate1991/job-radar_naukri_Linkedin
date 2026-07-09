"""
cloud_store.py
──────────────
Supabase-backed version of dashboard_store, so the dashboard can run on
Streamlit Cloud and be used from your phone.

Same public API as dashboard_store (all_jobs, add_job, mark_applied,
mark_pending, stats, purge_junk, seed_from_existing) — so dashboard.py can
use either backend interchangeably.

Credentials are read from (in order):
  1. Streamlit secrets   (st.secrets["SUPABASE_URL"] / ["SUPABASE_KEY"])
  2. secret_config.py    (SUPABASE_URL / SUPABASE_KEY)   ← laptop
  3. environment vars    (SUPABASE_URL / SUPABASE_KEY)

Table expected (see SETUP_CLOUD.md for the SQL):
  jobs(url pk, title, company, platform, score, cover_letter, summary,
       notes, first_seen, status, applied_at)
"""

import os
from datetime import datetime

import requests

_TEST_COMPANIES = {"spyco", "wirecheck ltd", "zz test co", "finalco", "test corp"}
_TEST_DOMAINS   = ("ex.com", "example.com")


def _cfg(name: str) -> str:
    # 1) Streamlit secrets (cloud)
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    # 2) secret_config.py (laptop)
    try:
        import secret_config as _sec
        v = getattr(_sec, name, "")
        if v:
            return str(v)
    except Exception:
        pass
    # 3) environment
    return os.getenv(name, "")


SUPABASE_URL = _cfg("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = _cfg("SUPABASE_KEY")
_TABLE = "jobs"


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _headers(extra: dict = None) -> dict:
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _rest(path: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{path}"


def _is_junk(url: str, company: str) -> bool:
    u = (url or "").lower()
    if any(d in u for d in _TEST_DOMAINS):
        return True
    return (company or "").strip().lower() in _TEST_COMPANIES


# ── public API ───────────────────────────────────────────────────
def all_jobs() -> list:
    if not is_configured():
        return []
    try:
        r = requests.get(_rest(_TABLE) + "?select=*", headers=_headers(), timeout=20)
        r.raise_for_status()
        rows = r.json()
        return [row for row in rows
                if not _is_junk(row.get("url", ""), row.get("company", ""))]
    except Exception as e:
        print("cloud_store all_jobs error:", e)
        return []


def add_job(platform: str, title: str, company: str, url: str,
            score: int = 0, cover_letter: str = "", summary: str = "",
            notes: str = "") -> None:
    """Insert a new job. Existing URLs are left untouched (status preserved)."""
    if not url or not is_configured():
        return
    row = {
        "url": url,
        "title": title,
        "company": company,
        "platform": platform,
        "score": score or 0,
        "cover_letter": cover_letter or "",
        "summary": summary or "",
        "notes": notes or "",
        "first_seen": datetime.now().isoformat(),
        "status": "pending",
        "applied_at": None,
    }
    try:
        # ignore-duplicates: don't overwrite an existing url (keeps its status)
        requests.post(
            _rest(_TABLE),
            headers=_headers({"Prefer": "resolution=ignore-duplicates,return=minimal"}),
            json=[row], timeout=20,
        )
    except Exception as e:
        print("cloud_store add_job error:", e)


def mark_applied(url: str) -> None:
    if not is_configured():
        return
    try:
        requests.patch(
            _rest(_TABLE), params={"url": f"eq.{url}"},
            headers=_headers({"Prefer": "return=minimal"}),
            json={"status": "applied", "applied_at": datetime.now().isoformat()},
            timeout=20,
        )
    except Exception as e:
        print("cloud_store mark_applied error:", e)


def mark_pending(url: str) -> None:
    if not is_configured():
        return
    try:
        requests.patch(
            _rest(_TABLE), params={"url": f"eq.{url}"},
            headers=_headers({"Prefer": "return=minimal"}),
            json={"status": "pending", "applied_at": None},
            timeout=20,
        )
    except Exception as e:
        print("cloud_store mark_pending error:", e)


def purge_junk() -> int:
    """Delete test/junk rows. Returns count removed."""
    if not is_configured():
        return 0
    jobs = []
    try:
        r = requests.get(_rest(_TABLE) + "?select=url,company", headers=_headers(), timeout=20)
        r.raise_for_status()
        jobs = r.json()
    except Exception:
        return 0
    removed = 0
    for row in jobs:
        if _is_junk(row.get("url", ""), row.get("company", "")):
            try:
                requests.delete(
                    _rest(_TABLE), params={"url": f"eq.{row['url']}"},
                    headers=_headers({"Prefer": "return=minimal"}), timeout=20,
                )
                removed += 1
            except Exception:
                pass
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
        "total": len(jobs),
        "pending": len(pending),
        "applied": len(applied),
        "by_platform": by_platform,
    }


def seed_from_existing(verbose: bool = False) -> dict:
    """No-op on cloud (data is pushed from the laptop via sync_to_cloud.py)."""
    return stats()


if __name__ == "__main__":
    print("Supabase configured:", is_configured())
    if is_configured():
        print("stats:", stats())
