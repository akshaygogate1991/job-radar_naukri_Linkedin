"""
workday_bot.py
──────────────
Auto-applies to jobs on company career sites built on WORKDAY
(URLs like company.wdX.myworkdayjobs.com) — the flow you saw at Corpay.

What it does for each pending Workday job in your dashboard:
  1. Opens the job page → clicks Apply → "Autofill with Resume"
  2. Signs in with your email + password; creates the account if it
     doesn't exist yet (same password everywhere, from secret_config.py)
  3. Uploads the TAILORED resume generated for that exact job
  4. Steps through My Information / My Experience / Application Questions /
     Voluntary Disclosures, answering from config/profile.py
     (EASY_APPLY_ANSWERS, CANDIDATE, ADDRESS)
  5. Ticks terms & conditions, clicks Submit
  6. Marks the job "applied" in the dashboard on success

If it meets a question it can't answer, or a CAPTCHA / email-verification
wall, it STOPS that job safely — the job stays "pending" in your dashboard
with a note telling you exactly where it got stuck, so you can finish it
in 30 seconds by hand.

Run it (after run_agent has filled the dashboard):
    python workday_bot.py            # up to 10 jobs
    python workday_bot.py --max 3    # limit per run
"""

import os
import re
import sys
import time
import random
import argparse

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

from config.profile import (CANDIDATE, ADDRESS, EASY_APPLY_ANSWERS,
                            ACCOUNT_PASSWORD, SKILLS)
import dashboard_store
from pdf_generator import generate_tailored_resume

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── helpers ──────────────────────────────────────────────────────
def delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def find_answer(question: str):
    q = (question or "").lower()
    for k, v in EASY_APPLY_ANSWERS.items():
        if k in q:
            return str(v)
    return None


def default_skills():
    flat, seen, out = [], set(), []
    for g in SKILLS.values():
        flat.extend(g)
    for s in flat:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return ", ".join(out[:18])


def tailored_pdf_for(job):
    """Generate (or reuse) the tailored resume PDF for this job."""
    summary = job.get("summary") or (
        "Data & analytics professional skilled in Python, SQL, Power BI and "
        "workflow automation, with deployed ML projects and an AI job agent."
    )
    try:
        return generate_tailored_resume(
            job_title=job.get("title", "Role"),
            company=job.get("company", "Company"),
            summary=summary,
            skills=default_skills(),
        )
    except Exception as e:
        print(f"    resume generation failed ({e})")
        return None


def wd(page, automation_id):
    """Workday elements carry stable data-automation-id attributes."""
    return page.locator(f"[data-automation-id='{automation_id}']")


DEBUG_DIR = os.path.join(BASE_DIR, "logs", "workday_debug")


def debug_dump(page, tag):
    """Screenshot + visible automation-ids, so we can tune selectors."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        ts = time.strftime("%H%M%S")
        shot = os.path.join(DEBUG_DIR, f"{ts}_{tag[:20]}.png")
        page.screenshot(path=shot)
        ids = page.eval_on_selector_all(
            "[data-automation-id]",
            "els => els.slice(0, 40).map(e => e.getAttribute('data-automation-id'))")
        print(f"    [debug] screenshot: {shot}")
        print(f"    [debug] page elements: {sorted(set(ids))[:25]}")
    except Exception:
        pass


def wait_for_workday(page):
    """Workday is a slow SPA — wait for it to actually render."""
    try:
        page.wait_for_load_state("networkidle", timeout=25000)
    except Exception:
        pass
    delay(2, 4)


def pause_for_user(msg):
    """Assist mode: let Akshay do one step by hand, then continue."""
    print("\n" + "=" * 60)
    print("  🖐  YOUR TURN — " + msg)
    print("  Do it in the browser window, then come back here.")
    print("=" * 60)
    input("  Press ENTER when done... ")
    return True


def click_if(page, automation_id, timeout=4000) -> bool:
    try:
        el = wd(page, automation_id).first
        if el.count() > 0 and el.is_visible():
            el.click(timeout=timeout)
            return True
    except Exception:
        pass
    return False


# ── account / sign-in ────────────────────────────────────────────
def sign_in_or_register(page) -> str:
    """
    Returns 'in' when signed in, or a failure note.
    Tries sign-in first; if that fails, creates the account.
    """
    email, pwd = CANDIDATE["email"], ACCOUNT_PASSWORD

    for attempt in ("signin", "create"):
        try:
            if attempt == "create":
                # switch to the Create Account form
                if not (click_if(page, "createAccountLink")
                        or click_if(page, "createAccountButton")):
                    page.get_by_text(re.compile("create account", re.I)).first.click()
                delay()

            e = wd(page, "email").first
            p = wd(page, "password").first
            if e.count() == 0:
                return "in"          # no sign-in wall on this tenant
            e.fill(email)
            p.fill(pwd)

            v = wd(page, "verifyPassword").first
            if attempt == "create" and v.count() > 0:
                v.fill(pwd)
            cb = wd(page, "createAccountCheckbox").first
            if attempt == "create" and cb.count() > 0:
                try:
                    cb.check()
                except Exception:
                    cb.click()

            if attempt == "signin":
                ok = (click_if(page, "signInSubmitButton")
                      or click_if(page, "click_filter"))
            else:
                ok = click_if(page, "createAccountSubmitButton")
            if not ok:
                page.keyboard.press("Enter")
            delay(3, 5)

            # error banner? try the other mode
            err = wd(page, "errorMessage")
            if err.count() > 0 and err.first.is_visible():
                msg = err.first.inner_text(timeout=2000)[:80]
                print(f"    {attempt} said: {msg}")
                continue
            return "in"
        except Exception as ex:
            print(f"    {attempt} attempt issue: {ex}")
            continue
    return "could not sign in / register"


# ── per-page form filling ────────────────────────────────────────
def fill_current_page(page) -> list:
    """
    Fill everything answerable on the current Workday step.
    Returns a list of unknown-question texts (empty = all good).
    """
    unknowns = []

    # text inputs
    try:
        inputs = page.locator("input[type='text'], input:not([type]), input[type='tel'], textarea")
        for i in range(min(inputs.count(), 40)):
            el = inputs.nth(i)
            try:
                if not el.is_visible() or el.input_value():
                    continue
            except Exception:
                continue
            label = ""
            for how in (lambda: el.get_attribute("aria-label"),
                        lambda: el.get_attribute("placeholder"),
                        lambda: el.locator("xpath=ancestor::div[@data-automation-id][1]")
                                  .get_attribute("data-automation-id"),
                        lambda: el.locator("xpath=ancestor::*[self::div or self::li][2]")
                                  .inner_text(timeout=800)):
                try:
                    label = (how() or "").strip()
                except Exception:
                    label = ""
                if label:
                    break
            ll = label.lower()
            val = None
            if "addressline" in ll or "address line" in ll:
                val = ADDRESS["line1"]
            elif "city" in ll:
                val = ADDRESS["city"]
            elif "postal" in ll or "pin" in ll or "zip" in ll:
                val = ADDRESS["postal_code"]
            elif "phone" in ll and "extension" not in ll:
                val = CANDIDATE["phone"].replace("+91", "").strip()
            elif "given name" in ll or "first name" in ll:
                val = CANDIDATE["name"].split()[0]
            elif "family name" in ll or "last name" in ll:
                val = CANDIDATE["name"].split()[-1]
            else:
                val = find_answer(label)
            if val:
                try:
                    el.fill(str(val))
                    delay(0.2, 0.5)
                except Exception:
                    pass
            elif label and len(label) > 8 and "extension" not in ll \
                    and "local" not in ll and "preferred name" not in ll:
                unknowns.append(label[:90])
    except Exception:
        pass

    # radio groups
    try:
        radios = page.locator("input[type='radio']")
        groups = {}
        for i in range(min(radios.count(), 60)):
            r = radios.nth(i)
            try:
                if not r.is_visible():
                    continue
                name = r.get_attribute("name") or f"g{i}"
            except Exception:
                continue
            groups.setdefault(name, []).append(r)
        for name, rl in groups.items():
            if any(_safe_checked(r) for r in rl):
                continue
            q = ""
            try:
                q = rl[0].locator(
                    "xpath=ancestor::fieldset[1]").inner_text(timeout=800)
            except Exception:
                try:
                    q = rl[0].locator(
                        "xpath=ancestor::*[self::div][3]").inner_text(timeout=800)
                except Exception:
                    q = ""
            ans = find_answer(q)
            if not ans:
                unknowns.append((q or "(radio question)")[:90])
                continue
            for r in rl:
                lbl = ""
                try:
                    _id = r.get_attribute("id")
                    if _id:
                        lbl = page.locator(f"label[for='{_id}']").inner_text(timeout=600)
                except Exception:
                    pass
                if not lbl:
                    lbl = r.get_attribute("value") or ""
                if lbl.strip().lower().startswith(ans.lower()):
                    try:
                        r.click()
                        delay(0.2, 0.5)
                    except Exception:
                        pass
                    break
    except Exception:
        pass

    # dropdowns (Workday uses button-based listboxes)
    try:
        boxes = page.locator("button[aria-haspopup='listbox']")
        for i in range(min(boxes.count(), 25)):
            b = boxes.nth(i)
            try:
                if not b.is_visible():
                    continue
                current = (b.inner_text(timeout=600) or "").strip().lower()
                if current and current not in ("select one", "select", ""):
                    continue
                q = (b.get_attribute("aria-label") or "")
                if not q:
                    q = b.locator("xpath=ancestor::*[self::div][2]").inner_text(timeout=600)
            except Exception:
                continue
            ans = find_answer(q)
            if "phone device" in (q or "").lower():
                ans = ans or "Mobile"
            if "country" in (q or "").lower() and not ans:
                ans = "India"
            if not ans:
                unknowns.append((q or "(dropdown)")[:90])
                continue
            try:
                b.click()
                delay(0.4, 0.8)
                opt = page.locator(f"[role='option']:has-text('{ans}')").first
                if opt.count() > 0:
                    opt.click()
                else:
                    page.keyboard.type(ans[:15])
                    delay(0.3, 0.6)
                    page.keyboard.press("Enter")
                delay(0.3, 0.6)
            except Exception:
                pass
    except Exception:
        pass

    # checkboxes (terms & conditions, acknowledgements)
    try:
        cbs = page.locator("input[type='checkbox']")
        for i in range(min(cbs.count(), 10)):
            c = cbs.nth(i)
            try:
                if not c.is_visible() or _safe_checked(c):
                    continue
                ctx = c.locator("xpath=ancestor::*[self::div][2]").inner_text(timeout=600).lower()
            except Exception:
                ctx = ""
            if any(k in ctx for k in ("terms", "privacy", "acknowledg", "consent", "i have read")):
                try:
                    c.check()
                except Exception:
                    try:
                        c.click()
                    except Exception:
                        pass
    except Exception:
        pass

    return unknowns


def _safe_checked(el) -> bool:
    try:
        return el.is_checked()
    except Exception:
        return False


# ── main per-job flow ────────────────────────────────────────────
def apply_one(page, job, assist=False) -> tuple:
    """Returns (success: bool, note: str).
    assist=True → when stuck, pause so you can do that one step by hand."""
    url = job["url"]
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    wait_for_workday(page)

    # dead / expired posting? → tell the caller so it can auto-close it
    try:
        body = page.locator("body").inner_text(timeout=8000).lower()
        dead_markers = ("page not found", "job is no longer", "no longer available",
                        "no longer accepting", "position has been filled",
                        "cannot be found", "404")
        if any(m in body for m in dead_markers) and "apply" not in body[:2000]:
            return False, "JOB_CLOSED"
    except Exception:
        pass

    # cookie banner
    for txt in ("Accept Cookies", "Accept All", "I Accept"):
        try:
            b = page.get_by_role("button", name=re.compile(txt, re.I)).first
            if b.count() > 0 and b.is_visible():
                b.click()
                delay(0.5, 1)
                break
        except Exception:
            pass

    # Apply → Autofill with Resume (wait for the button — slow SPA)
    try:
        wd(page, "adventureButton").first.wait_for(state="visible", timeout=15000)
    except Exception:
        pass
    clicked = (click_if(page, "adventureButton") or click_if(page, "applyButton"))
    if not clicked:
        try:
            b = page.get_by_role("button", name=re.compile("^apply", re.I)).first
            if b.count() > 0:
                b.click()
                clicked = True
        except Exception:
            pass
    if not clicked:
        debug_dump(page, "no_apply_btn")
        if assist and pause_for_user("click the APPLY button on this job page"):
            pass
        else:
            return False, "Apply button not found"
    wait_for_workday(page)
    click_if(page, "autofillWithResume")
    wait_for_workday(page)

    # sign in / create account (persistent profile keeps you logged in
    # after the first time — including 'Continue with Google')
    status = sign_in_or_register(page)
    if status != "in":
        if assist and pause_for_user(
                "log in on this page (email+password, or Continue with Google). "
                "One time only — the browser remembers it for future runs"):
            wait_for_workday(page)
        else:
            return False, status
    delay(2, 4)
    # may need to re-click apply/autofill after fresh login
    click_if(page, "adventureButton")
    click_if(page, "autofillWithResume")
    wait_for_workday(page)

    # resume upload
    pdf = tailored_pdf_for(job)
    uploaded = False
    if pdf:
        try:
            fi = page.locator("input[type='file']").first
            if fi.count() > 0:
                fi.set_input_files(pdf)
                uploaded = True
                print("    tailored resume uploaded")
                delay(3, 5)
        except Exception as e:
            print(f"    resume upload issue: {e}")

    # walk the wizard (max 12 steps)
    all_unknowns = []
    for step in range(12):
        # CAPTCHA wall?
        if page.locator("iframe[src*='captcha'], iframe[title*='captcha' i]").count() > 0:
            if assist and pause_for_user("solve the CAPTCHA"):
                wait_for_workday(page)
            else:
                return False, "CAPTCHA on page — finish this one by hand"

        unknowns = fill_current_page(page)
        if unknowns:
            all_unknowns.extend(unknowns)
            if assist:
                print("    Questions I don't know yet:")
                for u in unknowns[:5]:
                    print(f"      ? {u}")
                pause_for_user("answer these question(s) in the browser "
                               "(I'll remember to ask you to add them to my brain)")
            else:
                return False, "Needs manual answer: " + "; ".join(unknowns[:3])

        # find the Next / Save and Continue / Submit button
        moved = False
        for aid in ("bottom-navigation-next-button", "pageFooterNextButton"):
            btn = wd(page, aid).first
            if btn.count() > 0 and btn.is_visible():
                label = (btn.inner_text(timeout=800) or "").strip().lower()
                btn.click()
                moved = True
                delay(3, 5)
                if "submit" in label:
                    delay(2, 4)
                    return True, "submitted"
                break
        if not moved:
            for name in ("Save and Continue", "Continue", "Next", "Submit"):
                try:
                    b = page.get_by_role("button", name=re.compile(f"^{name}$", re.I)).first
                    if b.count() > 0 and b.is_visible():
                        b.click()
                        moved = True
                        delay(3, 5)
                        if name == "Submit":
                            return True, "submitted"
                        break
                except Exception:
                    continue
        if not moved:
            # maybe we're already on a success screen
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=3000).lower()
            except Exception:
                pass
            if any(k in body for k in ("application submitted", "thank you for applying",
                                        "successfully submitted")):
                return True, "submitted (confirmation screen)"
            debug_dump(page, f"stuck_step{step + 1}")
            if assist and pause_for_user(
                    "the bot can't find the Next/Continue button — click through "
                    "this step yourself (login, popup, whatever is on screen)"):
                wait_for_workday(page)
                continue
            return False, f"Stuck on step {step + 1} — no Next button found"

    if all_unknowns:
        return True, "submitted with your help — ADD THESE TO BRAIN: " + "; ".join(all_unknowns[:5])
    return False, "Too many steps — finish by hand"


# Public alias so naukri_bot / linkedin_bot can auto-apply the moment they
# capture a FRESH Workday URL (stored URLs expire — this is the reliable path).
def apply_via_workday(page, job) -> tuple:
    return apply_one(page, job)


def is_workday_url(url: str) -> bool:
    return bool(url) and "myworkdayjobs.com" in url.lower()


def notify_unknown_questions(platform, title, company, url, note):
    """Put the unanswered questions into the daily summary email."""
    try:
        from notifier import send_error_alert
        send_error_alert(platform,
            f"NOT APPLIED — questions missing from profile brain for "
            f"'{title}' @ {company}: {note} | Finish here: {url}")
    except Exception:
        pass


PROFILE_DIR = os.path.join(BASE_DIR, "logs", "workday_browser_profile")


def run(max_jobs=10, assist=True):
    jobs = [j for j in dashboard_store.all_jobs()
            if j.get("status") == "pending"
            and "myworkdayjobs.com" in (j.get("url") or "")]
    print(f"Workday jobs pending in dashboard: {len(jobs)}")
    jobs = sorted(jobs, key=lambda x: x.get("first_seen", ""), reverse=True)[:max_jobs]
    if not jobs:
        print("Nothing to do. (Only URLs on *.myworkdayjobs.com are handled.)")
        return
    if assist:
        print("ASSIST MODE ON — when I get stuck, I'll ask you to do that one "
              "step in the browser, then press ENTER here.\n")

    applied = 0
    with sync_playwright() as pw:
        # persistent profile → logins (incl. 'Continue with Google') survive
        # between runs, so you sign in ONCE per site, ever.
        ctx = pw.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        page = ctx.new_page()
        for i, job in enumerate(jobs, 1):
            print(f"\n[{i}/{len(jobs)}] {job.get('title')} @ {job.get('company')}")
            try:
                ok, note = apply_one(page, job, assist=assist)
            except Exception as e:
                ok, note = False, f"error: {str(e)[:80]}"
            if ok:
                dashboard_store.mark_applied(job["url"])
                applied += 1
                print(f"    ✅ APPLIED — marked in dashboard")
            elif note == "JOB_CLOSED":
                dashboard_store.set_status(job["url"], "closed")
                print(f"    🚫 dead link — auto-moved to Closed tab")
            else:
                if "manual answer" in note.lower():
                    notify_unknown_questions("workday", job.get("title", ""),
                                             job.get("company", ""), job["url"], note)
                # keep pending; record why so the dashboard note shows it
                try:
                    data = dashboard_store._load()
                    if job["url"] in data:
                        data[job["url"]]["notes"] = f"[workday bot] {note}"
                        dashboard_store._save(data)
                except Exception:
                    pass
                print(f"    ⏭  left for manual: {note}")
            delay(5, 10)
        ctx.close()

    print(f"\nDone. Auto-applied {applied}/{len(jobs)} Workday jobs.")
    print("Run 'python sync_to_cloud.py' to update your phone dashboard.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--auto", action="store_true",
                    help="no pauses — skip anything that needs a human")
    args = ap.parse_args()
    run(max_jobs=args.max, assist=not args.auto)
