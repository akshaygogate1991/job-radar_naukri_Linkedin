"""
hirist_bot.py
─────────────
Automates Hirist.tech applications:
  1. Logs in
  2. Searches for target roles (India-wide, no location filter)
  3. For each job:
       - Opens job detail in new tab
       - Clicks "Read More" to expand full JD
       - Scrapes JD text
       - Sends to Claude (resume_tailor.py) for match score + tailored resume
       - If match_score >= threshold:
           a. Generates tailored PDF
           b. Goes to profile page → uploads new resume
           c. Goes back to job page → clicks Apply
           d. Handles any post-apply modals
       - Only logs Applied if confirmed
  4. Stops after max_per_day_hirist applications

FLOW (matches Naukri pattern):
  Login → Search → Job detail → Read More → JD scrape → Claude tailor →
  PDF gen → Upload to profile → Apply → Handle gate → Confirm

Hirist is a React SPA — need longer waits + JS-heavy interactions.
"""

import time
import random
import sys
import os

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.profile import CANDIDATE, SEARCH, PLATFORMS, EASY_APPLY_ANSWERS
from resume_tailor import tailor_resume, should_apply
from tracker import already_applied, log_application
from notifier import send_error_alert, add_manual_job
from pdf_generator import generate_tailored_resume


def human_delay(min_s=2, max_s=5):
    time.sleep(random.uniform(min_s, max_s))


def send_to_dashboard(job_title, company, url, result):
    """
    Route a relevant Hirist job that the bot could NOT auto-apply to
    into the manual-apply dashboard (with its cover letter + summary),
    so it shows up alongside LinkedIn/Naukri jobs.
    """
    try:
        add_manual_job(
            platform="hirist",
            job_title=job_title,
            company=company,
            job_url=url,
            match_score=result.get("match_score", 0),
            cover_letter=result.get("cover_letter", ""),
            summary=result.get("summary", ""),
        )
        print("  → Sent to dashboard for manual apply.")
    except Exception as _e:
        print(f"  → Dashboard push skipped: {_e}")


def find_answer_for_question(question_text: str):
    q = question_text.lower()
    for keyword, answer in EASY_APPLY_ANSWERS.items():
        if keyword in q:
            return answer
    return None


def _hirist_q_text(page, el):
    """Best-effort: recover the question / label text for a form field."""
    try:
        for attr in ("aria-label", "placeholder"):
            v = el.get_attribute(attr)
            if v and len(v.strip()) > 1:
                return v.strip()
    except Exception:
        pass
    try:
        _id = el.get_attribute("id")
        if _id:
            lab = page.locator(f"label[for='{_id}']")
            if lab.count() > 0:
                t = lab.first.inner_text(timeout=1000).strip()
                if t:
                    return t
    except Exception:
        pass
    for xp in ("xpath=ancestor::*[self::div or self::label or self::li][1]",
               "xpath=ancestor::*[self::div or self::li][2]"):
        try:
            t = el.locator(xp).inner_text(timeout=1000).strip()
            if t and len(t) < 400:
                return t
        except Exception:
            continue
    try:
        v = el.get_attribute("name")
        if v:
            return v.strip()
    except Exception:
        pass
    return ""


def _hirist_radio_label(page, radio):
    """Text label for a single radio/checkbox option."""
    for xp in ("xpath=following-sibling::label[1]",
               "xpath=parent::label",
               "xpath=ancestor::label[1]"):
        try:
            t = radio.locator(xp).inner_text(timeout=800).strip()
            if t:
                return t
        except Exception:
            continue
    try:
        _id = radio.get_attribute("id")
        if _id:
            lab = page.locator(f"label[for='{_id}']")
            if lab.count() > 0:
                return lab.first.inner_text(timeout=800).strip()
    except Exception:
        pass
    return (radio.get_attribute("value") or "").strip()


def answer_hirist_screening(page, job_result=None):
    """
    Smart screening-form handler for Hirist.

    Answers each question using the details saved in config/profile.py
    (EASY_APPLY_ANSWERS, via find_answer_for_question). Known CTC / notice
    fields are handled explicitly; a genuine Yes/No with no keyword match
    defaults to "Yes". Any question it truly cannot answer is recorded in
    'unknowns', so the caller can hand you the job (with its screening URL)
    on the dashboard instead of submitting a half-wrong form.

    Returns: {"screen": bool, "unknowns": [str], "submitted": bool}
    """
    out = {"screen": False, "unknowns": [], "submitted": False}
    cover = ""
    if isinstance(job_result, dict):
        cover = job_result.get("cover_letter", "") or ""
    try:
        # wait briefly for a screening form / modal to render
        for _ in range(6):
            has_form = ("screening" in page.url.lower()
                        or page.locator("text=Submit a Form").count() > 0
                        or page.locator("form input, form textarea, form select").count() > 0)
            if has_form:
                break
            time.sleep(1)

        try:
            visible_fields = page.locator(
                "input[type='text'], input[type='number'], input:not([type]), "
                "textarea, select, input[type='radio']"
            ).count()
        except Exception:
            visible_fields = 0
        if "screening" not in page.url.lower() and visible_fields == 0:
            return out          # no screening step — direct apply worked

        out["screen"] = True
        print("  Screening form detected — answering with your saved details...")
        time.sleep(random.uniform(1.5, 2.5))

        # load all questions into view
        try:
            for _ in range(4):
                page.evaluate("window.scrollBy(0, 400)")
                time.sleep(0.4)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.6)
        except Exception:
            pass

        # ── TEXT / NUMBER INPUTS ──
        try:
            inputs = page.locator("input[type='text'], input[type='number'], input:not([type])")
            for i in range(inputs.count()):
                inp = inputs.nth(i)
                try:
                    if not inp.is_visible() or inp.input_value() != "":
                        continue
                except Exception:
                    continue
                q = _hirist_q_text(page, inp)
                ql = q.lower()
                if any(k in ql for k in ("email", "phone", "mobile")):
                    continue    # contact fields come prefilled from profile
                if "notice" in ql:
                    ans = "Immediate"
                elif any(k in ql for k in ("ctc", "salary", "lpa", "compensation")):
                    ans = "12" if "expect" in ql else "9.4"
                else:
                    ans = find_answer_for_question(q)
                if ans:
                    try:
                        inp.fill(str(ans))
                        time.sleep(random.uniform(0.2, 0.5))
                    except Exception:
                        pass
                else:
                    out["unknowns"].append(q or "(unlabeled question)")
        except Exception:
            pass

        # ── RADIO GROUPS ──
        try:
            radios = page.locator("input[type='radio']")
            groups = {}
            for i in range(radios.count()):
                r = radios.nth(i)
                try:
                    if not r.is_visible():
                        continue
                    name = r.get_attribute("name") or f"__g{i}"
                except Exception:
                    continue
                groups.setdefault(name, []).append(r)
            for name, rlist in groups.items():
                already = False
                for r in rlist:
                    try:
                        if r.is_checked():
                            already = True
                            break
                    except Exception:
                        pass
                if already:
                    continue
                q = _hirist_q_text(page, rlist[0])
                ans = find_answer_for_question(q)
                target = (ans if ans else "Yes").lower()
                picked = False
                for r in rlist:
                    lbl = _hirist_radio_label(page, r).strip().lower()
                    val = (r.get_attribute("value") or "").strip().lower()
                    if target in (lbl, val) or (lbl and target in lbl):
                        try:
                            r.click()
                            picked = True
                            time.sleep(random.uniform(0.2, 0.5))
                            break
                        except Exception:
                            pass
                if not picked and not ans:
                    out["unknowns"].append(q or "(choice question)")
        except Exception:
            pass

        # ── DROPDOWNS ──
        try:
            selects = page.locator("select")
            for i in range(selects.count()):
                dd = selects.nth(i)
                try:
                    if not dd.is_visible():
                        continue
                    cur = dd.evaluate("el => el.value")
                except Exception:
                    continue
                if cur:
                    continue
                q = _hirist_q_text(page, dd)
                ans = find_answer_for_question(q)
                if ans:
                    ok = False
                    for how in ("label", "value"):
                        try:
                            dd.select_option(**{how: ans})
                            ok = True
                            break
                        except Exception:
                            continue
                    if not ok:
                        out["unknowns"].append(q or "(dropdown question)")
                else:
                    try:
                        dd.select_option(label="Yes")
                    except Exception:
                        out["unknowns"].append(q or "(dropdown question)")
        except Exception:
            pass

        # ── TEXTAREAS ── (use the cover letter when we have it)
        try:
            tas = page.locator("textarea")
            for i in range(tas.count()):
                ta = tas.nth(i)
                try:
                    if not ta.is_visible() or ta.input_value() != "":
                        continue
                    ta.fill(cover if cover else "Yes")
                    time.sleep(random.uniform(0.2, 0.5))
                except Exception:
                    continue
        except Exception:
            pass

        # If we hit questions we couldn't answer, DON'T submit a half-wrong
        # form — let the caller send you the URL to finish by hand.
        if out["unknowns"]:
            print(f"    ⚠ {len(out['unknowns'])} question(s) I can't answer — routing to dashboard.")
            return out

        # ── SUBMIT ──
        try:
            for _ in range(4):
                page.evaluate("window.scrollBy(0, 500)")
                time.sleep(0.4)
        except Exception:
            pass
        time.sleep(random.uniform(1.5, 2.5))
        for sel in ("button:has-text('Submit Application')",
                    "button:has-text('Submit')",
                    "button:has-text('Apply')",
                    "button:has-text('Continue')",
                    "button:has-text('Next')",
                    "button[type='submit']"):
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.scroll_into_view_if_needed(timeout=3000)
                    btn.click()
                    out["submitted"] = True
                    print("    ✓ Screening submitted.")
                    time.sleep(random.uniform(4, 6))
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"  Screening handler note: {e}")
    return out


def handle_hirist_gate(page):
    """
    Handle Hirist's multi-step application screening form.
    URL pattern: hirist.tech/job/XXXXX/screening?...
    
    Answers:
      - Notice Period → "Immediately Available" / "Immediate" / "0"
      - Location questions → "Yes"
      - Current CTC → "9.4" (LPA)
      - Expected CTC → "12" (LPA)
      - Relocation → "Yes"
      - Any other Yes/No → "Yes"
      - Experience Y/N questions → "Yes"
    
    Then clicks Submit / Apply / Continue.
    """
    try:
        # Wait for screening form to appear (URL contains 'screening')
        for _ in range(6):
            if "screening" in page.url.lower() or page.locator("text=Submit a Form").count() > 0:
                break
            time.sleep(1)
        else:
            # No screening form appeared — maybe direct apply worked
            return

        print("  Screening form detected. Answering questions...")
        time.sleep(random.uniform(2, 3))

        # Scroll through the whole form first to load all questions
        try:
            for _ in range(4):
                page.evaluate("window.scrollBy(0, 400)")
                time.sleep(0.5)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
        except:
            pass

        # ── 1. NOTICE PERIOD → "Immediately Available" ──
        # Try multiple button/label variants
        notice_variants = [
            "Immediately Available",
            "Immediate",
            "Available Immediately",
            "0 days",
            "0-15 days",
            "Less than 15 days",
        ]
        notice_clicked = False
        for variant in notice_variants:
            try:
                btn = page.locator(f"button:has-text('{variant}'), label:has-text('{variant}'), div[role='button']:has-text('{variant}')").first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    time.sleep(random.uniform(0.5, 1))
                    print(f"    ✓ Notice: {variant}")
                    notice_clicked = True
                    break
            except:
                continue

        # ── 2. NOTICE PERIOD in text field (some jobs use text input) ──
        try:
            notice_inputs = page.locator(
                "input[placeholder*='notice' i], "
                "input[name*='notice' i]"
            )
            for i in range(notice_inputs.count()):
                try:
                    inp = notice_inputs.nth(i)
                    if inp.is_visible() and inp.input_value() == "":
                        inp.fill("Immediate")
                        time.sleep(random.uniform(0.3, 0.7))
                        print(f"    ✓ Notice text: Immediate")
                except:
                    continue
        except:
            pass

        # ── 3. CURRENT CTC → "9.4" ──
        try:
            # Look for inputs labeled "Current CTC"
            ctc_current = page.locator(
                "input[placeholder*='current' i][placeholder*='CTC' i], "
                "input[placeholder*='current' i][placeholder*='salary' i], "
                "input[name*='current' i][name*='CTC' i]"
            )
            for i in range(ctc_current.count()):
                try:
                    inp = ctc_current.nth(i)
                    if inp.is_visible():
                        inp.fill("9.4")
                        time.sleep(random.uniform(0.3, 0.7))
                        print(f"    ✓ Current CTC: 9.4")
                except:
                    continue

            # Look for inputs labeled "Expected CTC"
            ctc_expected = page.locator(
                "input[placeholder*='expected' i][placeholder*='CTC' i], "
                "input[placeholder*='expected' i][placeholder*='salary' i]"
            )
            for i in range(ctc_expected.count()):
                try:
                    inp = ctc_expected.nth(i)
                    if inp.is_visible():
                        inp.fill("12")
                        time.sleep(random.uniform(0.3, 0.7))
                        print(f"    ✓ Expected CTC: 12")
                except:
                    continue

            # Fallback: any remaining CTC/salary/LPA field
            ctc_any = page.locator(
                "input[placeholder*='CTC' i], "
                "input[placeholder*='salary' i], "
                "input[placeholder*='LPA' i]"
            )
            for i in range(ctc_any.count()):
                try:
                    inp = ctc_any.nth(i)
                    if inp.is_visible() and inp.input_value() == "":
                        inp.fill("9.4")
                        time.sleep(random.uniform(0.3, 0.7))
                except:
                    continue
        except:
            pass

        # ── 4. RADIO BUTTONS → Yes ──
        try:
            # For questions like "Are you currently living in Bangalore?"
            yes_radios = page.locator("input[type='radio']")
            count = yes_radios.count()
            answered = 0
            for i in range(count):
                try:
                    radio = yes_radios.nth(i)
                    if radio.is_visible():
                        # Check the value / associated label
                        value = radio.get_attribute("value") or ""
                        if value.lower() in ("yes", "true", "1", "y"):
                            radio.click()
                            time.sleep(random.uniform(0.3, 0.7))
                            answered += 1
                except:
                    continue

            if answered > 0:
                print(f"    ✓ Radio Yes clicked: {answered}")
        except:
            pass

        # ── 5. Yes BUTTONS/LABELS (for non-radio Yes/No questions) ──
        try:
            yes_labels = page.locator("label:has-text('Yes'), button:has-text('Yes'):not(:has-text('Years'))")
            count = yes_labels.count()
            clicked = 0
            for i in range(min(count, 8)):
                try:
                    lbl = yes_labels.nth(i)
                    if lbl.is_visible():
                        lbl.click()
                        time.sleep(random.uniform(0.3, 0.7))
                        clicked += 1
                except:
                    continue
            if clicked > 0:
                print(f"    ✓ Yes labels clicked: {clicked}")
        except:
            pass

        # ── 6. TEXT INPUTS THAT ARE STILL EMPTY → "Yes" ──
        try:
            text_inputs = page.locator("input[type='text']:not([disabled])")
            for i in range(text_inputs.count()):
                try:
                    inp = text_inputs.nth(i)
                    if inp.is_visible() and inp.input_value() == "":
                        placeholder = (inp.get_attribute("placeholder") or "").lower()
                        # Skip if this is a known field we already handled
                        if any(kw in placeholder for kw in ["ctc", "salary", "lpa", "notice"]):
                            continue
                        # Skip email/phone/number fields
                        if any(kw in placeholder for kw in ["email", "phone", "number"]):
                            continue
                        inp.fill("Yes")
                        time.sleep(random.uniform(0.3, 0.5))
                except:
                    continue
        except:
            pass

        # ── 7. DROPDOWNS → select second option (first is placeholder) ──
        try:
            dropdowns = page.locator("select")
            for i in range(dropdowns.count()):
                try:
                    dd = dropdowns.nth(i)
                    if dd.is_visible():
                        options = dd.locator("option").all()
                        if len(options) > 1:
                            dd.select_option(index=1)
                            time.sleep(random.uniform(0.3, 0.7))
                except:
                    continue
        except:
            pass

        # ── 8. TEXTAREAS → "Yes" ──
        try:
            text_areas = page.locator("textarea")
            for i in range(text_areas.count()):
                try:
                    ta = text_areas.nth(i)
                    if ta.is_visible() and ta.input_value() == "":
                        ta.fill("Yes")
                        time.sleep(random.uniform(0.3, 0.7))
                except:
                    continue
        except:
            pass

        # Scroll to reveal Submit button
        try:
            for _ in range(4):
                page.evaluate("window.scrollBy(0, 500)")
                time.sleep(0.5)
        except:
            pass

        time.sleep(random.uniform(2, 3))

        # ── 9. CLICK SUBMIT / APPLY ──
        submit_selectors = [
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Continue')",
            "button:has-text('Next')",
            "button[type='submit']",
        ]
        submitted = False
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.scroll_into_view_if_needed(timeout=3000)
                    btn.click()
                    time.sleep(random.uniform(4, 6))  # extra wait for server
                    print("    ✓ Submit clicked.")
                    submitted = True
                    break
            except:
                continue

        if not submitted:
            print("    ⚠ Submit button not found on screening form.")

    except Exception as e:
        print(f"  Screening form handler note: {e}")


def update_hirist_resume(page, pdf_path: str) -> bool:
    """Go to Hirist profile page and upload new resume."""
    try:
        # Navigate to profile / personal details page
        page.goto("https://www.hirist.tech/registration/addPersonalDetails?pref=sp_prm",
                  wait_until="domcontentloaded")
        human_delay(5, 7)

        # Scroll down to make sure Attach Resume section is loaded
        page.evaluate("window.scrollBy(0, 200)")
        human_delay(1, 2)

        # Method 1: Look for any file input (may be hidden but accessible)
        try:
            file_inputs = page.locator("input[type='file']")
            if file_inputs.count() > 0:
                file_inputs.first.set_input_files(pdf_path)
                human_delay(5, 8)
                print("  Profile resume updated on Hirist (direct file input).")
                return True
        except Exception as e:
            print(f"  Direct file input attempt: {e}")

        # Method 2: Click "Upload new resume" link first
        try:
            upload_link = page.locator("text=Upload new resume").first
            if upload_link.count() > 0:
                upload_link.scroll_into_view_if_needed(timeout=3000)
                # Use file chooser pattern — Playwright waits for the dialog
                with page.expect_file_chooser() as fc_info:
                    upload_link.click()
                file_chooser = fc_info.value
                file_chooser.set_files(pdf_path)
                human_delay(5, 8)
                print("  Profile resume updated on Hirist (via upload link).")
                return True
        except Exception as e:
            print(f"  Upload link method: {e}")

        # Method 3: Click any button with 'Upload' text
        try:
            upload_btn = page.locator("button:has-text('Upload'), a:has-text('Upload')").first
            if upload_btn.count() > 0:
                upload_btn.scroll_into_view_if_needed(timeout=3000)
                with page.expect_file_chooser() as fc_info:
                    upload_btn.click()
                file_chooser = fc_info.value
                file_chooser.set_files(pdf_path)
                human_delay(5, 8)
                print("  Profile resume updated on Hirist (via upload button).")
                return True
        except Exception as e:
            print(f"  Upload button method: {e}")

        print("  Could not find resume upload field on Hirist.")
        return False

    except Exception as e:
        print(f"  Hirist resume update failed: {e}")
        return False


def run_hirist_bot():
    creds = PLATFORMS.get("hirist", {})
    if not creds.get("enabled"):
        print("Hirist disabled in profile.py")
        return

    applied_count = 0
    max_apply = SEARCH.get("max_per_day_hirist", 10)
    resume_updates_today = 0
    max_resume_updates = 12

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # ── 1. LOGIN ──────────────────────────────────────────
        print("Logging into Hirist...")
        page.goto("https://www.hirist.tech/", wait_until="domcontentloaded")
        human_delay(4, 6)

        # Dismiss cookie banner if present
        try:
            cookie_btn = page.locator("button:has-text('Got it'), button:has-text('Accept'), button:has-text('OK')").first
            if cookie_btn.count() > 0:
                cookie_btn.click()
                human_delay(1, 2)
                print("  Cookie banner dismissed.")
        except:
            pass

        # Click Login button (top-right) — force if hidden
        try:
            # Multiple selectors to find the Login button
            login_selectors = [
                "button:has-text('Login'):not(:has-text('Recruiter'))",
                "a:has-text('Login'):not(:has-text('Recruiter'))",
                "button:has-text('Login')",
                "a:has-text('Login')",
            ]
            clicked = False
            for sel in login_selectors:
                btns = page.locator(sel)
                count = btns.count()
                if count > 0:
                    # Try each match, prefer visible ones
                    for i in range(count):
                        btn = btns.nth(i)
                        try:
                            btn.scroll_into_view_if_needed(timeout=3000)
                            btn.click(timeout=5000)
                            clicked = True
                            break
                        except:
                            try:
                                # Force click if normal click fails
                                btn.click(force=True, timeout=3000)
                                clicked = True
                                break
                            except:
                                continue
                    if clicked:
                        break

            if not clicked:
                print("  Could not click any Login button. Trying direct URL...")
                page.goto("https://www.hirist.tech/login", wait_until="domcontentloaded")

            human_delay(3, 5)
        except Exception as e:
            print(f"  Login button navigation failed: {e}")
            browser.close()
            return

        # Fill login form
        try:
            # Email field
            email_input = page.locator("input[type='email'], input[placeholder*='Email' i], input[name*='email' i]").first
            email_input.fill(creds["email"])
            human_delay(1, 2)

            # Password field
            password_input = page.locator("input[type='password']").first
            password_input.fill(creds["password"])
            human_delay(1, 2)

            # Click "Login →" button
            login_submit = page.locator("button:has-text('Login')").last  # last one on form
            login_submit.click()
            human_delay(5, 8)

        except Exception as e:
            print(f"  Login form failed: {e}")
            browser.close()
            return

        # Check if login worked (should redirect to /jobfeed or dashboard)
        if "login" in page.url.lower() and "jobfeed" not in page.url.lower():
            print("  Hirist login may have failed. Current URL:", page.url)
            send_error_alert("hirist", "Login failed. Check credentials or CAPTCHA.")
            browser.close()
            return

        print("  Logged into Hirist successfully.")

        # Wait for post-login auto-redirect to /jobfeed to settle
        # Otherwise the first search navigation gets interrupted
        try:
            page.wait_for_url("**/jobfeed**", timeout=15000)
            print("  Redirected to jobfeed.")
        except:
            pass  # Already on some other page

        # Extra settle time so no navigation is in-flight
        human_delay(3, 5)

        # ── 2. SEARCH FOR EACH ROLE — LOCATION-AGNOSTIC ───────
        for role in SEARCH["roles"]:
            if applied_count >= max_apply:
                break

            print(f"\nSearching Hirist: '{role}' (India-wide)...")

            # Build Hirist search URL
            role_slug = role.lower().replace(' ', '-')
            search_url = f"https://www.hirist.tech/search/{role_slug}-jobs?loc=&minexp=2&maxexp=10&posting=&category=&searchType=&method="

            # Try navigation with retry on redirect interruption
            nav_success = False
            for attempt in range(3):
                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    nav_success = True
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    if "interrupted" in err_msg or "navigation" in err_msg:
                        print(f"  Nav interrupted (attempt {attempt+1}/3), retrying...")
                        human_delay(3, 5)
                        continue
                    else:
                        raise

            if not nav_success:
                print(f"  Failed to navigate to search after 3 attempts. Skipping role.")
                continue

            human_delay(4, 6)

            # Scroll to load more cards (React SPA lazy loads)
            for _ in range(4):
                page.evaluate("window.scrollBy(0, 600)")
                human_delay(1, 2)
            page.evaluate("window.scrollTo(0, 0)")
            human_delay(1, 2)

            # ── COLLECT ALL JOB URLs DIRECTLY FROM PAGE ──
            # Much more reliable than parsing card structures
            job_urls = []
            try:
                all_job_links = page.locator("a[href*='/j/']").all()
                seen_urls = set()
                for link in all_job_links:
                    try:
                        href = link.get_attribute("href")
                        if href and "/j/" in href:
                            if not href.startswith("http"):
                                full_url = f"https://www.hirist.tech{href}"
                            else:
                                full_url = href
                            # Remove query string for dedup
                            base_url = full_url.split("?")[0]
                            if base_url not in seen_urls:
                                seen_urls.add(base_url)
                                job_urls.append(full_url)
                    except:
                        continue
            except Exception as e:
                print(f"  Could not collect job URLs: {e}")
                continue

            print(f"Found {len(job_urls)} unique job URLs")

            for url_idx, job_url in enumerate(job_urls):
                if applied_count >= max_apply:
                    break

                try:
                    # Placeholder values — will be updated from job page header
                    job_title = f"Job_{url_idx}"
                    company = "Unknown"

                    print(f"\n→ Opening: {job_url}")

                    # ── OPEN JOB DETAIL IN NEW TAB ──
                    new_page = context.new_page()
                    new_page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                    human_delay(4, 6)

                    # ── EXTRACT REAL COMPANY NAME FROM JOB DETAIL PAGE HEADER ──
                    # Structure: h1 = job title, then subtitle like "Phenom • 5-10 Years • Hyderabad"
                    try:
                        # Refresh job title from detail page (h1 tag)
                        h1_title = new_page.locator("h1").first
                        if h1_title.count() > 0:
                            new_title = h1_title.inner_text(timeout=3000).strip()
                            if new_title and "Search For" not in new_title:
                                job_title = new_title

                        # Get ONLY the header area (not full page) to find company
                        # Look right after the h1 for the subtitle
                        header_text = ""
                        try:
                            # Try to get parent of h1 which contains title + subtitle
                            header_area = new_page.locator("h1").first
                            if header_area.count() > 0:
                                # Get text of the parent container
                                parent_text = header_area.evaluate(
                                    "el => el.parentElement ? el.parentElement.innerText : ''"
                                )
                                header_text = parent_text[:500] if parent_text else ""
                        except:
                            pass

                        # Look for "Company • X-Y Years • Location" pattern in HEADER only
                        import re
                        # Match: capture text before " • X-Y Years" or " • X Years"
                        subtitle_match = re.search(
                            r"([\w\s\.\-&,]+?)\s*[•·]\s*\d+\s*-?\s*\d*\s*(Years?|yrs?|Yrs?)",
                            header_text
                        )
                        if subtitle_match:
                            extracted_company = subtitle_match.group(1).strip()
                            # Remove title if it got included
                            if job_title in extracted_company:
                                extracted_company = extracted_company.replace(job_title, "").strip()
                            # Sanity check — must be short and not contain "Search"
                            if (extracted_company and
                                len(extracted_company) < 60 and
                                "Search" not in extracted_company and
                                "Jobs" not in extracted_company):
                                company = extracted_company

                        print(f"  Detected: {job_title} @ {company}")
                    except Exception as e:
                        print(f"  Header extraction note: {e}")

                    # ── CHECK IF ALREADY APPLIED (using real title/company) ──
                    if already_applied(company, job_title):
                        print(f"  Already applied to {job_title} at {company}. Skipping.")
                        if new_page != page:
                            new_page.close()
                        continue

                    # Scroll down to reveal JD content and Read More button
                    for _ in range(5):
                        new_page.evaluate("window.scrollBy(0, 400)")
                        human_delay(0.5, 1)

                    # Click "Read More" to expand JD (only if truncated)
                    try:
                        read_more = new_page.locator("a:has-text('Read More'), button:has-text('Read More'), span:has-text('Read More')").first
                        if read_more.count() > 0:
                            read_more.scroll_into_view_if_needed(timeout=3000)
                            read_more.click()
                            human_delay(2, 3)
                    except:
                        pass  # No Read More — JD is already full

                    # Scrape JD
                    try:
                        jd_container = new_page.locator("div[class*='job-desc'], div[class*='JobDesc'], div[class*='description'], main").first
                        jd_text = jd_container.inner_text(timeout=8000)
                    except:
                        jd_text = new_page.locator("body").inner_text(timeout=8000)[:5000]

                    if len(jd_text) < 200:
                        print("  JD too short, skipping.")
                        if new_page != page:
                            new_page.close()
                        continue

                    print(f"  JD length: {len(jd_text)} chars")

                    # ── 3. CLAUDE TAILORING ──
                    print("  Sending to Claude for tailoring...")
                    result = tailor_resume(job_title, company, jd_text)

                    if not should_apply(result):
                        print(f"  Match {result['match_score']}% - below threshold. Skipping.")
                        log_application("hirist", company, job_title, job_url or new_page.url,
                                         result['match_score'], status="Skipped",
                                         notes=result['match_reason'])
                        if new_page != page:
                            new_page.close()
                        continue

                    print(f"  Match {result['match_score']}% - proceeding!")

                    # ── 4. GENERATE TAILORED PDF ──
                    pdf_path = generate_tailored_resume(
                        job_title=job_title,
                        company=company,
                        summary=result['summary'],
                        skills=result['skills']
                    )

                    # ── 5. UPDATE HIRIST PROFILE RESUME ──
                    if resume_updates_today < max_resume_updates:
                        updated = update_hirist_resume(new_page, pdf_path)
                        if updated:
                            resume_updates_today += 1
                        human_delay(3, 5)

                        # CRITICAL: Navigate BACK to the exact job URL (not go_back)
                        # go_back can land on search page or wrong URL
                        print(f"  Navigating back to job: {job_url}")
                        new_page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                        human_delay(4, 6)

                        # Verify we're actually on the job page (URL contains /j/)
                        if "/j/" not in new_page.url:
                            print(f"  Not on job page after nav. URL: {new_page.url}. Skipping.")
                            log_application("hirist", company, job_title, job_url,
                                             result['match_score'], status="Failed",
                                             notes="Failed to return to job page after resume upload")
                            send_to_dashboard(job_title, company, job_url, result)
                            if new_page != page:
                                new_page.close()
                            continue

                    # ── 6. CLICK APPLY ──
                    # Scroll to bottom of page to reveal Apply button
                    print("  Scrolling to Apply button...")
                    try:
                        new_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        human_delay(2, 3)
                        # Sometimes need to scroll up slightly to reach the button
                        new_page.evaluate("window.scrollBy(0, -300)")
                        human_delay(1, 2)
                    except:
                        pass

                    # Look for Apply button (specifically, not "Applied" which means done)
                    apply_btn_selectors = [
                        "button:has-text('Apply'):not(:has-text('Applied'))",
                        "a:has-text('Apply'):not(:has-text('Applied'))",
                        "button:text-is('Apply')",
                        "button[class*='apply']:not([disabled])",
                    ]
                    apply_btn = None
                    for sel in apply_btn_selectors:
                        try:
                            btn = new_page.locator(sel).first
                            if btn.count() > 0 and btn.is_visible():
                                apply_btn = btn
                                break
                        except:
                            continue

                    if not apply_btn:
                        print("  Apply button not found or not visible.")
                        log_application("hirist", company, job_title, job_url or new_page.url,
                                         result['match_score'], status="Failed",
                                         notes="Apply button not found")
                        send_to_dashboard(job_title, company, job_url or new_page.url, result)
                        if new_page != page:
                            new_page.close()
                        continue

                    try:
                        apply_btn.scroll_into_view_if_needed(timeout=3000)
                        human_delay(1, 2)
                        apply_btn.click()
                        print("  Apply clicked.")
                        human_delay(4, 6)  # give time for response
                    except Exception as e:
                        print(f"  Apply click failed: {e}")
                        log_application("hirist", company, job_title, job_url or new_page.url,
                                         result['match_score'], status="Failed",
                                         notes=f"Apply click failed: {e}")
                        send_to_dashboard(job_title, company, job_url or new_page.url, result)
                        if new_page != page:
                            new_page.close()
                        continue

                    # Handle any modal/screening form — answer with saved details
                    gate = answer_hirist_screening(new_page, result)
                    if gate.get("unknowns"):
                        screening_url = new_page.url
                        qs = "; ".join(gate["unknowns"][:3])
                        log_application("hirist", company, job_title, screening_url,
                                         result['match_score'], status="Manual",
                                         notes="Screening needs manual answer: " + qs)
                        send_to_dashboard(job_title, company, screening_url, result)
                        print(f"  → Screening question I can't answer; sent URL to dashboard.")
                        if new_page != page:
                            new_page.close()
                        continue
                    human_delay(4, 5)

                    # ── 7. CONFIRMATION CHECK ──
                    # Truth source: Hirist's UI state
                    confirmed = False

                    # Give Hirist extra time to process
                    human_delay(3, 5)

                    try:
                        # Method 1 (STRONGEST): URL changes to /job/applied
                        current_url = new_page.url.lower()
                        if "/job/applied" in current_url or "/applied" in current_url:
                            confirmed = True
                            print(f"  Confirmed via URL: {current_url}")

                        # Method 2: Success message on page
                        if not confirmed:
                            success_selectors = [
                                "text=Your application has been submitted successfully",
                                "text=application has been submitted",
                                "text=Application Submitted",
                                "text=successfully applied",
                                "text=Applied successfully",
                                "text=Application Received",
                                "text=Job Applied",
                            ]
                            for sel in success_selectors:
                                try:
                                    if new_page.locator(sel).count() > 0:
                                        confirmed = True
                                        print(f"  Confirmed via message: {sel}")
                                        break
                                except:
                                    pass

                        # Method 3: "Applied" button state
                        if not confirmed:
                            applied_btn = new_page.locator(
                                "button:has-text('Applied'):not(:has-text('Apply Now'))"
                            )
                            if applied_btn.count() > 0:
                                confirmed = True
                                print("  Confirmed via 'Applied' button state")

                    except Exception as e:
                        print(f"  Confirmation check error: {e}")

                    if confirmed:
                        log_application("hirist", company, job_title, job_url or new_page.url,
                                         result['match_score'], status="Applied")
                        applied_count += 1
                        print(f"  [Applied] {company} — {job_title} (score: {result['match_score']})")
                    else:
                        log_application("hirist", company, job_title, job_url or new_page.url,
                                         result['match_score'], status="Failed",
                                         notes="Apply clicked but confirmation not detected")
                        send_to_dashboard(job_title, company, job_url or new_page.url, result)
                        print(f"  [Not confirmed] {company} — {job_title} — will retry later")

                    if new_page != page:
                        new_page.close()
                    human_delay(8, 15)

                except Exception as e:
                    print(f"  Error on this job: {e}")
                    try:
                        if 'new_page' in locals() and new_page != page:
                            new_page.close()
                    except:
                        pass
                    human_delay(3, 5)
                    continue

        browser.close()

    print(f"\nHirist done. Applied to {applied_count} jobs today. "
          f"Profile resume updated {resume_updates_today} times.")
    return applied_count


if __name__ == "__main__":
    run_hirist_bot()
