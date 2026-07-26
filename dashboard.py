"""
dashboard.py
────────────
One-page control room for your manual-apply jobs.

Run it:
    streamlit run dashboard.py
(or double-click run_dashboard.bat)

What it does:
  - Shows every job your bots couldn't auto-apply to (from all runs), in one list.
  - Each job: match score, company, "Open job" link, ready cover letter,
    and its tailored resume PDF (already generated, or made on the spot).
  - Click "Mark Applied" after you apply → the job disappears and never
    comes back. No duplicate applications.

It reads from your own logs (dashboard_jobs.json, built from manual_digest.json
and applications.json). No Gmail scraping. Nothing is deleted.
"""

import os
import re
import streamlit as st

import dashboard_store as local_store
from config.profile import CANDIDATE, SKILLS, RESUME_PDF

# Use Supabase when configured (cloud / mobile), else the local JSON store.
try:
    import cloud_store
    if cloud_store.is_configured():
        store = cloud_store
        DATA_SOURCE = "cloud"
    else:
        store = local_store
        DATA_SOURCE = "local"
except Exception:
    store = local_store
    DATA_SOURCE = "local"

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(BASE_DIR, "resumes", "generated")

st.set_page_config(page_title="Job Apply Dashboard", page_icon="🎯", layout="wide")


# ── helpers ──────────────────────────────────────────────────────
def _safe_filename(text: str) -> str:
    """Same rule pdf_generator.py uses to name resumes."""
    text = re.sub(r"[^a-zA-Z0-9_\- ]", "", text or "")
    return text.strip().replace(" ", "_")[:40]


def find_existing_resume(company: str, title: str):
    """Return path to an already-generated tailored resume, if one exists."""
    name = CANDIDATE["name"].replace(" ", "_")
    exact = os.path.join(
        GENERATED_DIR,
        f"Resume_{name}_{_safe_filename(company)}_{_safe_filename(title)}.pdf",
    )
    if os.path.exists(exact):
        return exact
    # fuzzy fallback: match by company token
    if os.path.isdir(GENERATED_DIR):
        comp = _safe_filename(company).lower()
        if comp:
            for f in os.listdir(GENERATED_DIR):
                if comp and comp in f.lower():
                    return os.path.join(GENERATED_DIR, f)
    return None


def default_skills_string() -> str:
    flat = []
    for group in SKILLS.values():
        flat.extend(group)
    # de-dup, keep order, cap at 18
    seen, out = set(), []
    for s in flat:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return ", ".join(out[:18])


def build_resume(job):
    """Generate a tailored PDF on the fly from the stored summary."""
    try:
        from pdf_generator import generate_tailored_resume
        summary = job.get("summary") or (
            "Data & analytics professional transitioning from operations, "
            "skilled in Python, SQL, and Power BI for data-driven decisions."
        )
        return generate_tailored_resume(
            job_title=job.get("title", "Role"),
            company=job.get("company", "Company"),
            summary=summary,
            skills=default_skills_string(),
        )
    except Exception as e:
        st.error(f"Could not generate resume: {e}")
        return None


def key_for(url: str, prefix: str) -> str:
    return prefix + "_" + str(abs(hash(url)))


# ── cached data access (speed) ───────────────────────────────────
# Cache the job list so ordinary reruns (filtering, paging) don't re-download
# everything from Supabase. The cache key holds a version number we bump on any
# change, so mark-applied / close / remove still update instantly.
@st.cache_data(ttl=180, show_spinner=False)
def _fetch_jobs(version):
    # 'version' is part of the cache key on purpose: bumping it (on any change)
    # forces a fresh fetch, while plain reruns reuse the cached result.
    return store.all_jobs()


def load_jobs():
    return _fetch_jobs(st.session_state.get("data_version", 0))


def bump_version():
    st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1


def mutate(fn, *args, **kwargs):
    """Apply a store change, invalidate the cache, and rerun."""
    fn(*args, **kwargs)
    bump_version()
    st.rerun()


def compute_stats(jobs):
    pending = [j for j in jobs if j.get("status") == "pending"]
    applied = [j for j in jobs if j.get("status") == "applied"]
    by_platform = {}
    for j in pending:
        p = j.get("platform", "other")
        by_platform[p] = by_platform.get(p, 0) + 1
    return {"total": len(jobs), "pending": len(pending),
            "applied": len(applied), "by_platform": by_platform}


# ── ensure store is seeded on first ever load ────────────────────
if not load_jobs():
    with st.spinner("Setting up your job list from existing logs…"):
        store.seed_from_existing(verbose=False)
        bump_version()


# ── sidebar controls ─────────────────────────────────────────────
st.sidebar.title("🎯 Filters")

if st.sidebar.button("🔄 Refresh from bot logs"):
    store.purge_junk()
    store.seed_from_existing(verbose=False)
    try:
        n = store.expire_stale(21)   # auto-close jobs older than 3 weeks
        if n:
            st.sidebar.info(f"Auto-closed {n} stale jobs (>21 days old).")
    except Exception:
        pass
    bump_version()
    st.rerun()

if st.sidebar.button("🧹 Clean test/duplicate junk"):
    removed = store.purge_junk()
    bump_version()
    st.sidebar.success(f"Removed {removed} junk records.")
    st.rerun()

all_jobs = load_jobs()
platforms = sorted({j.get("platform", "other") for j in all_jobs})
sel_platforms = st.sidebar.multiselect("Platform", platforms, default=platforms)

min_score = st.sidebar.slider("Minimum match score", 0, 100, 0, 5)
search = st.sidebar.text_input("Search title / company").strip().lower()
sort_by = st.sidebar.radio("Sort by", ["Newest first", "Match score (high→low)"])

st.sidebar.markdown("---")
st.sidebar.caption(
    "Tick **Mark Applied** after you apply on the site. "
    "Applied jobs move to the ✅ tab and won't show here again."
)


# ── header + metrics ─────────────────────────────────────────────
s = compute_stats(all_jobs)
st.title("Job Apply Dashboard")
_src = "☁️ Supabase (live on all devices)" if DATA_SOURCE == "cloud" else "💻 local file"
st.caption(f"For {CANDIDATE['name']} · data source: {_src}")

m1, m2, m3, m4 = st.columns(4)
m1.metric("To apply", s["pending"])
m2.metric("Applied", s["applied"])
m3.metric("Total tracked", s["total"])
_hidden = sum(1 for j in all_jobs if j.get("status") in ("closed", "discarded"))
m4.metric("Closed / Removed", _hidden)
if s["by_platform"]:
    st.caption("Pending by platform: " +
               " · ".join(f"{k}: {v}" for k, v in s["by_platform"].items()))


def matches_filters(j) -> bool:
    if j.get("platform", "other") not in sel_platforms:
        return False
    if int(j.get("score", 0) or 0) < min_score:
        return False
    if search:
        blob = (j.get("title", "") + " " + j.get("company", "")).lower()
        if search not in blob:
            return False
    return True


def sort_jobs(jobs):
    if sort_by.startswith("Match"):
        return sorted(jobs, key=lambda x: int(x.get("score", 0) or 0), reverse=True)
    return sorted(jobs, key=lambda x: x.get("first_seen", ""), reverse=True)


tab_apply, tab_done, tab_gone = st.tabs(
    ["📋 To Apply", "✅ Applied", "🚫 Closed / Removed"])


# signatures (company + role) of everything already applied to —
# used to hide near-duplicate listings of a job you've already applied for
def _norm(t):
    t = (t or "").lower().strip()
    t = re.sub(r"\b(sr|jr)\b", lambda m: {"sr": "senior", "jr": "junior"}[m.group(0)], t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)      # drop punctuation
    t = re.sub(r"\s+", " ", t).strip()      # collapse whitespace
    return t


def _sig(j):
    return (_norm(j.get("company", "")), _norm(j.get("title", "")))


def dedup(jobs):
    """One card per company+role; keep highest score / one with a cover letter."""
    best = {}
    for j in jobs:
        sig = _sig(j)
        cur = best.get(sig)
        if (cur is None
                or int(j.get("score", 0) or 0) > int(cur.get("score", 0) or 0)
                or (j.get("cover_letter") and not cur.get("cover_letter"))):
            best[sig] = j
    return list(best.values())


# hide repeat listings of roles you've applied to OR marked as not relevant
applied_sigs = {_sig(j) for j in all_jobs
                if j.get("status") in ("applied", "discarded")}


# ── TO APPLY ─────────────────────────────────────────────────────
with tab_apply:
    raw_pending = [j for j in all_jobs
                   if j.get("status") == "pending"
                   and _sig(j) not in applied_sigs
                   and matches_filters(j)]

    pending = sort_jobs(dedup(raw_pending))

    # pagination — draw a page at a time so the browser isn't rendering
    # hundreds of cards (the main cause of the app feeling slow/stuck)
    PAGE = 25
    shown_n = st.session_state.get("show_n", PAGE)

    if not pending:
        st.success("Nothing to apply to with these filters. 🎉")
    else:
        st.write(f"**{len(pending)} jobs** to apply to "
                 f"(showing {min(shown_n, len(pending))}).")

    for j in pending[:shown_n]:
        url = j.get("url", "")
        with st.container(border=True):
            top, actions = st.columns([3, 1])

            with top:
                st.markdown(f"### {j.get('title','(no title)')}")
                st.markdown(
                    f"**{j.get('company','')}** · "
                    f"`{j.get('platform','')}` · "
                    f"match **{j.get('score',0)}%**"
                )

            with actions:
                if url:
                    try:
                        st.link_button("🔗 Open job", url, use_container_width=True)
                    except Exception:
                        st.markdown(f"[🔗 Open job]({url})")
                # dead link? one click searches the company's live openings
                from urllib.parse import quote_plus
                _q = quote_plus(f'"{j.get("title","")}" {j.get("company","")} careers apply')
                try:
                    st.link_button("🔍 Find fresh link",
                                   f"https://www.google.com/search?q={_q}",
                                   use_container_width=True,
                                   help="Old link dead? Search the live posting")
                except Exception:
                    pass
                if st.button("✅ Mark Applied", key=key_for(url, "apply"),
                             type="primary", use_container_width=True):
                    mutate(store.set_status, url, "applied")

                b1, b2 = st.columns(2)
                with b1:
                    if st.button("🚫 Closed", key=key_for(url, "closed"),
                                 use_container_width=True,
                                 help="This job opening is closed / expired"):
                        mutate(store.set_status, url, "closed")
                with b2:
                    if st.button("🗑️ Remove", key=key_for(url, "discard"),
                                 use_container_width=True,
                                 help="Not matching my profile — hide it for good"):
                        mutate(store.set_status, url, "discarded")

            # cover letter + summary
            if j.get("cover_letter") or j.get("summary"):
                with st.expander("📝 Cover letter & summary (copy-paste ready)"):
                    if j.get("summary"):
                        st.caption("Profile summary")
                        st.write(j["summary"])
                    if j.get("cover_letter"):
                        st.caption("Cover letter")
                        st.text_area("cover", value=j["cover_letter"], height=220,
                                     key=key_for(url, "cl"),
                                     label_visibility="collapsed")

            # tailored resume — regenerated fresh so it always has project links
            with st.expander("📄 Tailored resume (with project links)"):
                if st.button("⚙️ Generate resume for this job",
                             key=key_for(url, "gen")):
                    path = build_resume(j)
                    if path:
                        with open(path, "rb") as f:
                            st.download_button(
                                "⬇️ Download tailored resume",
                                data=f.read(),
                                file_name=os.path.basename(path),
                                mime="application/pdf",
                                key=key_for(url, "dlgen"),
                            )
                if os.path.exists(RESUME_PDF):
                    with open(RESUME_PDF, "rb") as f:
                        st.download_button(
                            "⬇️ Master resume (fallback)",
                            data=f.read(),
                            file_name=os.path.basename(RESUME_PDF),
                            mime="application/pdf",
                            key=key_for(url, "dlmaster"),
                        )

    # ── Show more ──
    if len(pending) > shown_n:
        if st.button(f"⬇️ Show more ({len(pending) - shown_n} left)"):
            st.session_state["show_n"] = shown_n + PAGE
            st.rerun()


# ── APPLIED ──────────────────────────────────────────────────────
with tab_done:
    applied = sort_jobs(dedup([j for j in all_jobs if j.get("status") == "applied"]))
    st.write(f"**{len(applied)}** jobs marked applied.")
    for j in applied:
        url = j.get("url", "")
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.markdown(f"**{j.get('title','')}** — {j.get('company','')} "
                    f"(`{j.get('platform','')}`, {j.get('score',0)}%)")
        if url:
            c2.markdown(f"[open job]({url})")
        if c3.button("↩ Undo", key=key_for(url, "undo")):
            mutate(store.mark_pending, url)


# ── CLOSED / REMOVED ─────────────────────────────────────────────
with tab_gone:
    closed    = sort_jobs(dedup([j for j in all_jobs if j.get("status") == "closed"]))
    discarded = sort_jobs(dedup([j for j in all_jobs if j.get("status") == "discarded"]))

    st.caption("These are hidden from your To Apply list. "
               "They're kept (not deleted) so a future sync can't bring them back. "
               "Use Restore if you hid one by mistake.")

    st.markdown(f"#### 🚫 Closed openings ({len(closed)})")
    if not closed:
        st.write("None.")
    for j in closed:
        url = j.get("url", "")
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.markdown(f"**{j.get('title','')}** — {j.get('company','')} "
                    f"(`{j.get('platform','')}`, {j.get('score',0)}%)")
        if url:
            c2.markdown(f"[open job]({url})")
        if c3.button("↩ Restore", key=key_for(url, "unclose")):
            mutate(store.set_status, url, "pending")

    st.markdown(f"#### 🗑️ Removed as not relevant ({len(discarded)})")
    if not discarded:
        st.write("None.")
    for j in discarded:
        url = j.get("url", "")
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.markdown(f"**{j.get('title','')}** — {j.get('company','')} "
                    f"(`{j.get('platform','')}`, {j.get('score',0)}%)")
        if url:
            c2.markdown(f"[open job]({url})")
        if c3.button("↩ Restore", key=key_for(url, "undiscard")):
            mutate(store.set_status, url, "pending")
