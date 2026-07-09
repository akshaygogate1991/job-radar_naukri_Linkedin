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


# ── ensure store is seeded on first ever load ────────────────────
if not store.all_jobs():
    with st.spinner("Setting up your job list from existing logs…"):
        store.seed_from_existing(verbose=False)


# ── sidebar controls ─────────────────────────────────────────────
st.sidebar.title("🎯 Filters")

if st.sidebar.button("🔄 Refresh from bot logs"):
    store.purge_junk()
    store.seed_from_existing(verbose=False)
    st.rerun()

if st.sidebar.button("🧹 Clean test/duplicate junk"):
    removed = store.purge_junk()
    st.sidebar.success(f"Removed {removed} junk records.")
    st.rerun()

all_jobs = store.all_jobs()
platforms = sorted({j.get("platform", "other") for j in all_jobs})
sel_platforms = st.sidebar.multiselect("Platform", platforms, default=platforms)

min_score = st.sidebar.slider("Minimum match score", 0, 100, 0, 5)
search = st.sidebar.text_input("Search title / company").strip().lower()
sort_by = st.sidebar.radio("Sort by", ["Match score (high→low)", "Newest first"])

st.sidebar.markdown("---")
st.sidebar.caption(
    "Tick **Mark Applied** after you apply on the site. "
    "Applied jobs move to the ✅ tab and won't show here again."
)


# ── header + metrics ─────────────────────────────────────────────
s = store.stats()
st.title("Job Apply Dashboard")
_src = "☁️ Supabase (live on all devices)" if DATA_SOURCE == "cloud" else "💻 local file"
st.caption(f"For {CANDIDATE['name']} · data source: {_src}")

m1, m2, m3, m4 = st.columns(4)
m1.metric("To apply", s["pending"])
m2.metric("Applied", s["applied"])
m3.metric("Total tracked", s["total"])
m4.metric("Platforms", len(s["by_platform"]))
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


tab_apply, tab_done = st.tabs(["📋 To Apply", "✅ Applied"])


# signatures (company + role) of everything already applied to —
# used to hide near-duplicate listings of a job you've already applied for
def _sig(j):
    return (j.get("company", "").strip().lower(),
            j.get("title", "").strip().lower())

applied_sigs = {_sig(j) for j in all_jobs if j.get("status") == "applied"}


# ── TO APPLY ─────────────────────────────────────────────────────
with tab_apply:
    raw_pending = [j for j in all_jobs
                   if j.get("status") == "pending"
                   and _sig(j) not in applied_sigs
                   and matches_filters(j)]

    # collapse repeat listings of the same company + role → keep the best one
    best_by_sig = {}
    for j in raw_pending:
        sig = _sig(j)
        cur = best_by_sig.get(sig)
        better = (cur is None
                  or int(j.get("score", 0) or 0) > int(cur.get("score", 0) or 0)
                  or (j.get("cover_letter") and not cur.get("cover_letter")))
        if better:
            best_by_sig[sig] = j
    pending = sort_jobs(list(best_by_sig.values()))

    if not pending:
        st.success("Nothing to apply to with these filters. 🎉")
    else:
        st.write(f"**{len(pending)} jobs** to apply to.")

    for j in pending:
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
                if st.button("✅ Mark Applied", key=key_for(url, "apply"),
                             type="primary", use_container_width=True):
                    store.mark_applied(url)
                    st.rerun()

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

            # tailored resume
            with st.expander("📄 Tailored resume"):
                existing = find_existing_resume(j.get("company", ""), j.get("title", ""))
                if existing:
                    with open(existing, "rb") as f:
                        st.download_button(
                            "⬇️ Download tailored resume (already made)",
                            data=f.read(),
                            file_name=os.path.basename(existing),
                            mime="application/pdf",
                            key=key_for(url, "dl"),
                        )
                    st.caption(os.path.basename(existing))
                else:
                    if st.button("⚙️ Generate resume for this job",
                                 key=key_for(url, "gen")):
                        path = build_resume(j)
                        if path:
                            with open(path, "rb") as f:
                                st.download_button(
                                    "⬇️ Download generated resume",
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


# ── APPLIED ──────────────────────────────────────────────────────
with tab_done:
    applied = sort_jobs([j for j in all_jobs if j.get("status") == "applied"])
    st.write(f"**{len(applied)}** jobs marked applied.")
    for j in applied:
        url = j.get("url", "")
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.markdown(f"**{j.get('title','')}** — {j.get('company','')} "
                    f"(`{j.get('platform','')}`, {j.get('score',0)}%)")
        if url:
            c2.markdown(f"[open job]({url})")
        if c3.button("↩ Undo", key=key_for(url, "undo")):
            store.mark_pending(url)
            st.rerun()
