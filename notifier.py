"""
notifier.py
───────────
All notifications via Gmail only (Telegram blocked in India).

Emails sent ONLY at end of run:
  1. send_daily_summary()  — applied/skipped counts + top matches
  2. send_manual_digest()  — LinkedIn + Naukri external apply links

During run:
  - send_error_alert()  — saves to file only, included in final summary
  - add_manual_job()    — saves to digest file, sent at end
"""

import smtplib, os, sys, json as _json, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.profile import CANDIDATE, GMAIL_APP_PASSWORD
from tracker import get_todays_summary, get_all_stats

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
LOG_DIR     = os.path.join(BASE_DIR, "logs")
FALLBACK    = os.path.join(LOG_DIR, "run_log.txt")
DIGEST_FILE = os.path.join(LOG_DIR, "manual_digest.json")
ERRORS_FILE = os.path.join(LOG_DIR, "run_errors.txt")

# ── Gmail config ──────────────────────────────────────────────
EMAIL_CONFIG = {
    "enabled":         True,
    "sender_email":    CANDIDATE["email"],
    "sender_password": GMAIL_APP_PASSWORD,  # loaded from secret_config.py / env
    "receiver_email":  CANDIDATE["email"],
    "smtp_host":       "smtp.gmail.com",
    "smtp_port":       587,
}


# ── Internal helpers ──────────────────────────────────────────
def _log(text: str):
    """Save any message to local log file."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(FALLBACK, "a", encoding="utf-8") as f:
            f.write("\n" + "="*50 + "\n")
            f.write(datetime.now().strftime("%d %b %Y %I:%M %p") + "\n")
            f.write(text + "\n")
    except Exception:
        pass


def _log_error(platform: str, msg: str):
    """Save error to errors file — included in final summary email."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(ERRORS_FILE, "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%H:%M") + " | " + platform.upper() + " | " + msg + "\n")
    except Exception:
        pass


def _read_errors() -> str:
    """Read all errors collected during this run."""
    try:
        if os.path.exists(ERRORS_FILE):
            with open(ERRORS_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _clear_errors():
    """Clear errors file at start of run."""
    try:
        if os.path.exists(ERRORS_FILE):
            os.remove(ERRORS_FILE)
    except Exception:
        pass


# ── Gmail sender ──────────────────────────────────────────────
def send_email(subject: str, body: str) -> bool:
    """Send email via Gmail SMTP."""
    if not EMAIL_CONFIG["enabled"]:
        return False
    if "YOUR_GMAIL_APP_PASSWORD" in EMAIL_CONFIG["sender_password"]:
        print("  Gmail not configured — open notifier.py and add your App Password.")
        _log(subject + "\n" + body)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_CONFIG["sender_email"]
        msg["To"]      = EMAIL_CONFIG["receiver_email"]
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(EMAIL_CONFIG["smtp_host"], EMAIL_CONFIG["smtp_port"], timeout=20) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
            server.sendmail(EMAIL_CONFIG["sender_email"],
                            EMAIL_CONFIG["receiver_email"], msg.as_string())
        print("  Email sent: " + subject[:50])
        return True
    except Exception as e:
        print(f"  Email failed: {e}")
        _log(subject + "\n" + body)
        return False


# ── Public functions ──────────────────────────────────────────

def send_error_alert(platform: str, error_msg: str):
    """
    Called DURING run when something goes wrong.
    Does NOT send email immediately — saves to file.
    Errors are included in the final summary email at end of run.
    """
    _log_error(platform, error_msg)
    print(f"  [{platform.upper()}] Issue noted: {error_msg[:80]}")


def send_telegram_message(text: str) -> bool:
    """Legacy function — redirects to log only. No email during run."""
    _log(text)
    return True


def send_daily_summary():
    """
    Called ONCE at end of run.
    Sends one Gmail with full report: counts, top matches, skipped, errors.
    """
    today    = get_todays_summary()
    all_time = get_all_stats()
    date_str = datetime.now().strftime("%d %b %Y")
    errors   = _read_errors()

    body  = "JOB AGENT DAILY REPORT\n"
    body += "=" * 50 + "\n"
    body += "Date    : " + date_str + "\n"
    body += "LinkedIn: " + str(today['linkedin']) + " applied\n"
    body += "Naukri  : " + str(today['naukri']) + " applied\n"
    body += "Total   : " + str(today['total']) + " applied today\n"
    body += "Skipped : " + str(today['skipped']) + " (low match / already applied)\n"
    body += "All-time: " + str(all_time['total_applied']) + " total applications\n\n"

    if today["applied"]:
        top = sorted(today["applied"], key=lambda x: x["score"], reverse=True)[:5]
        body += "TOP MATCHES TODAY:\n"
        body += "-" * 40 + "\n"
        for j in top:
            body += "  " + j['job_title'] + " at " + j['company']
            body += " (" + str(j['score']) + "%)\n"
            body += "  " + j['url'] + "\n\n"

    if errors:
        body += "\nISSUES DURING RUN:\n"
        body += "-" * 40 + "\n"
        body += errors + "\n"

    body += "\nFull log: logs/applications.csv"

    subject = "Job Agent: " + str(today['total']) + " applied | " + date_str
    _log(body)
    return send_email(subject, body)


def send_manual_digest():
    """
    Called ONCE at end of run.
    Sends one Gmail with all external apply jobs grouped by platform.
    LinkedIn jobs first, then Naukri jobs.
    """
    data          = _load_digest()
    linkedin_jobs = data.get("linkedin", [])
    naukri_jobs   = data.get("naukri",   [])
    total         = len(linkedin_jobs) + len(naukri_jobs)

    if total == 0:
        print("  No external apply jobs today.")
        return True

    date_str = datetime.now().strftime("%d %b %Y")
    body  = "MANUAL APPLY DIGEST — " + date_str + "\n"
    body += "These jobs need YOU to apply on company website.\n"
    body += "Cover letter is ready — copy, open link, paste, submit.\n"
    body += "=" * 55 + "\n\n"

    if linkedin_jobs:
        body += "FROM LINKEDIN (" + str(len(linkedin_jobs)) + " jobs)\n"
        body += "-" * 40 + "\n\n"
        for i, j in enumerate(linkedin_jobs, 1):
            body += str(i) + ". " + j["title"] + " at " + j["company"] + "\n"
            body += "   Match : " + str(j["score"]) + "%\n"
            body += "   Link  : " + j["url"] + "\n"
            if j.get("cover_letter"):
                body += "\n   COVER LETTER:\n"
                for line in j["cover_letter"].split("\n"):
                    body += "   " + line + "\n"
            body += "\n" + "-"*30 + "\n\n"

    if naukri_jobs:
        body += "FROM NAUKRI (" + str(len(naukri_jobs)) + " jobs)\n"
        body += "-" * 40 + "\n\n"
        for i, j in enumerate(naukri_jobs, 1):
            body += str(i) + ". " + j["title"] + " at " + j["company"] + "\n"
            body += "   Match : " + str(j["score"]) + "%\n"
            body += "   Link  : " + j["url"] + "\n"
            if j.get("cover_letter"):
                body += "\n   COVER LETTER:\n"
                for line in j["cover_letter"].split("\n"):
                    body += "   " + line + "\n"
            body += "\n" + "-"*30 + "\n\n"

    subject = "Apply Now: " + str(total) + " jobs waiting — " + date_str
    _log(body)
    success = send_email(subject, body)
    if success:
        print("  Digest email sent — " + str(total) + " external jobs.")
    return success


# ── Digest file helpers ───────────────────────────────────────
def _load_digest() -> dict:
    try:
        if os.path.exists(DIGEST_FILE):
            with open(DIGEST_FILE, "r") as f:
                return _json.load(f)
    except Exception:
        pass
    return {"linkedin": [], "naukri": []}


def _save_digest(data: dict):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(DIGEST_FILE, "w") as f:
        _json.dump(data, f, indent=2)


def clear_digest():
    """Call at start of each run to reset."""
    _save_digest({"linkedin": [], "naukri": []})
    _clear_errors()


def add_manual_job(platform: str, job_title: str, company: str,
                   job_url: str, match_score: int,
                   cover_letter: str = "", summary: str = ""):
    """Add external job to digest — sent at end of run."""
    data = _load_digest()
    if platform not in data:
        data[platform] = []
    data[platform].append({
        "title":        job_title,
        "company":      company,
        "url":          job_url,
        "score":        match_score,
        "cover_letter": cover_letter,
        "summary":      summary,
    })
    _save_digest(data)

    # ── Also feed the persistent dashboard store (safe, non-breaking) ──
    # manual_digest.json is wiped each run; this store keeps every job
    # across runs so the Streamlit dashboard never loses history.
    try:
        import dashboard_store
        dashboard_store.add_job(
            platform=platform, title=job_title, company=company,
            url=job_url, score=match_score,
            cover_letter=cover_letter, summary=summary,
        )
    except Exception:
        pass  # dashboard is optional; never break the bot run


if __name__ == "__main__":
    print("Testing Gmail connection...")
    send_email("Job Agent Test", "Gmail is working correctly!")
