"""
sync_to_cloud.py
────────────────
Pushes the jobs collected on your laptop (logs/dashboard_jobs.json) up to
Supabase, so the Streamlit Cloud dashboard on your phone stays in sync.

  - New jobs are inserted (existing URLs are left untouched, so a job you
    already marked 'applied' on your phone is NOT reset to pending).
  - Jobs you marked 'applied' locally are pushed up as applied too.

Run it after a scrape:
    python sync_to_cloud.py
(run_agent.py also calls it automatically at the end of each run.)
"""

import dashboard_store as local_store
import cloud_store


def sync() -> dict:
    if not cloud_store.is_configured():
        print("Supabase not configured — add SUPABASE_URL / SUPABASE_KEY to "
              "secret_config.py. Skipping cloud sync.")
        return {"synced": 0}

    jobs = local_store.all_jobs()
    pushed = 0
    for j in jobs:
        url = j.get("url")
        if not url:
            continue
        cloud_store.add_job(
            platform=j.get("platform", ""),
            title=j.get("title", ""),
            company=j.get("company", ""),
            url=url,
            score=j.get("score", 0),
            cover_letter=j.get("cover_letter", ""),
            summary=j.get("summary", ""),
            notes=j.get("notes", ""),
        )
        if j.get("status") == "applied":
            cloud_store.mark_applied(url)
        pushed += 1

    cloud_store.purge_junk()
    s = cloud_store.stats()
    print(f"Synced {pushed} jobs to Supabase. "
          f"Cloud now: {s['pending']} pending / {s['applied']} applied.")
    return {"synced": pushed, **s}


if __name__ == "__main__":
    sync()
