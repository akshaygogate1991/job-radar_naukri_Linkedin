"""
naukri_bot.py
─────────────
Automates Naukri.com applications:
  1. Logs in
  2. Searches for target roles (from profile.py) — LOCATION-AGNOSTIC (India-wide)
  3. For each job:
       - Reads JD
       - Sends to Claude (resume_tailor.py) for match score + tailored resume
       - If match_score >= threshold:
           a. Generates tailored PDF
           b. Goes to profile -> uploads new resume
           c. Goes back to the job, clicks Apply
           d. Handles questionnaire gate (location/salary/relocation/notice)
       - Only logs Applied if Naukri confirms

UPDATED:
  - Removed location filter (searches all India)
  - Added questionnaire gate handler (Location=Mumbai, Salary=9.4, Relocation=Yes, Notice=Immediate)
  - Fixed: Only logs "Applied" when Naukri confirms; else "Failed" for retry
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
from notifier import send_telegram_message, send_error_alert, add_manual_job
from pdf_generator import generate_tailored_resume


def human_delay(min_s=2, max_s=5):
    time.sleep(random.uniform(min_s, max_s))


def find_answer_for_question(question_text: str):
    q = question_text.lower()
    for keyword, answer in EASY_APPLY_ANSWERS.items():
        if keyword in q:
            return answer
    return None


def handle_questionnaire_gate(page):
    """
    Handle Naukri's post-apply modal (questionnaire gate).
    Answers: Location=Mumbai, Salary=9.4 (LPA), Relocation=Yes, Notice=Immediate, All other Yes/No=Yes.
    Safe to call even if no modal appears.
    """
    try:
        # Wait briefly for modal to appear
        modal_found = False
        for _ in range(5):
            modal = page.locator("div.modal, div.questionnaireModal, div[class*='modal'], div[class*='questionnaire']").first
            if modal.count() > 0:
                modal_found = True
                time.sleep(random.uniform(1, 2))
                break
            time.sleep(1)

        if not modal_found:
            return

        # 1. Location field
        location_inputs = page.locator("input[placeholder*='location' i], input[placeholder*='city' i]")
        if location_inputs.count() > 0:
            try:
                location_inputs.first.fill("Mumbai")
                time.sleep(random.uniform(0.5, 1))
            except: pass

        # 2. Salary / CTC field
        salary_inputs = page.locator("input[placeholder*='salary' i], input[placeholder*='CTC' i], input[placeholder*='LPA' i]")
        if salary_inputs.count() > 0:
            try:
                salary_inputs.first.fill("9.4")
                time.sleep(random.uniform(0.5, 1))
            except: pass

        # 3. Relocation = Yes
        relocation_yes = page.locator("label:has-text('Yes'):near(:text('relocat'))")
        if relocation_yes.count() > 0:
            try:
                relocation_yes.first.click()
                time.sleep(random.uniform(0.5, 1))
            except: pass

        # 4. Notice Period = Immediate
        notice_immediate = page.locator("label:has-text('Immediate'), label:has-text('immediately')")
        if notice_immediate.count() > 0:
            try:
                notice_immediate.first.click()
                time.sleep(random.uniform(0.5, 1))
            except: pass

        # 5. Generic "Yes" for any remaining Yes/No questions (max 3)
        yes_labels = page.locator("label:has-text('Yes')")
        for i in range(min(yes_labels.count(), 3)):
            try:
                yes_labels.nth(i).click()
                time.sleep(random.uniform(0.5, 1))
            except: pass

        # 6. Click Save/Submit/Next
        save_btn = page.locator("button:has-text('Save'), button:has-text('Submit'), button:has-text('Next'), button:has-text('Continue')")
        if save_btn.count() > 0:
            try:
                save_btn.first.click()
                time.sleep(random.uniform(2, 3))
                print("  Gate answered.")
            except: pass

    except Exception as e:
        print(f"  Gate handler note: {e}")


def update_naukri_resume(page, pdf_path: str) -> bool:
    """Go to profile page and upload new resume, replacing the old one."""
    try:
        page.goto("https://www.naukri.com/mnjuser/profile")
        human_delay(3, 5)

        upload_input = page.locator("input#attachCV, input[type='file'][name='file']")
        if upload_input.count() == 0:
            change_btn = page.locator("text=Update resume, text=Upload resume")
            if change_btn.count() > 0:
                change_btn.first.click()
                human_delay(1, 2)
            upload_input = page.locator("input#attachCV, input[type='file'][name='file']")

        if upload_input.count() > 0:
            upload_input.first.set_input_files(pdf_path)
            human_delay(4, 7)
            print("  Profile resume updated.")
            return True
        else:
            print("  Could not find resume upload field.")
            return False

    except Exception as e:
        print(f"  Resume update failed: {e}")
        return False


def run_naukri_bot():
    creds = PLATFORMS["naukri"]
    if not creds["enabled"]:
        print("Naukri disabled in profile.py")
        return

    applied_count = 0
    max_apply = SEARCH["max_per_day_naukri"]
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
        print("Logging into Naukri...")
        page.goto("https://www.naukri.com/nlogin/login")
        human_delay(2, 4)

        page.fill("input#usernameField", creds["email"])
        human_delay(1, 2)
        page.fill("input#passwordField", creds["password"])
        human_delay(1, 2)
        page.click("button[type='submit']")
        human_delay(4, 7)

        if "captcha" in page.url.lower():
            send_error_alert("naukri", "CAPTCHA triggered at login. Manual login needed.")
            print("CAPTCHA detected. Stopping.")
            browser.close()
            return

        # ── 2. SEARCH FOR EACH ROLE — LOCATION-AGNOSTIC (India-wide) ──
        for role in SEARCH["roles"]:
            if applied_count >= max_apply:
                break

            print(f"\nSearching: '{role}' (India-wide)...")

            # Build Naukri search URL WITHOUT location — India-wide search
            role_slug = role.lower().replace(' ', '-')
            search_url = f"https://www.naukri.com/{role_slug}-jobs"
            search_url += "?jobAge=3&experience=7"  # last 3 days, 7+ years exp

            page.goto(search_url)
            human_delay(3, 6)

            job_cards = page.locator("div.srp-jobtuple-wrapper, article.jobTuple").all()
            print(f"Found {len(job_cards)} job listings")

            for card in job_cards:
                if applied_count >= max_apply:
                    break

                try:
                    job_link = card.locator("a.title, a.title.fw500").first
                    job_title = job_link.inner_text(timeout=5000).strip()
                    job_url = job_link.get_attribute("href")

                    company_locator = card.locator("a.comp-name, .companyInfo a")
                    company = company_locator.first.inner_text(timeout=5000).strip() if company_locator.count() > 0 else "Unknown"

                    print(f"\n→ {job_title} at {company}")

                    if already_applied(company, job_title):
                        print("  Already applied recently. Skipping.")
                        continue

                    new_page = context.new_page()
                    new_page.goto(job_url)
                    human_delay(3, 5)

                    jd_text = new_page.locator("div.styles_JDC__dang-inner-html__h0K4t, div.job-desc").first.inner_text(timeout=8000)

                    print("  Sending to Claude for tailoring...")
                    result = tailor_resume(job_title, company, jd_text)

                    if not should_apply(result):
                        print(f"  Match {result['match_score']}% - below threshold. Skipping.")
                        log_application("naukri", company, job_title, job_url,
                                         result['match_score'], status="Skipped",
                                         notes=result['match_reason'])
                        new_page.close()
                        continue

                    print(f"  Match {result['match_score']}% - proceeding!")

                    pdf_path = generate_tailored_resume(
                        job_title=job_title,
                        company=company,
                        summary=result['summary'],
                        skills=result['skills']
                    )

                    if resume_updates_today < max_resume_updates:
                        updated = update_naukri_resume(new_page, pdf_path)
                        if updated:
                            resume_updates_today += 1
                        human_delay(3, 6)
                        new_page.goto(job_url)
                        human_delay(2, 4)
                    else:
                        print("  Daily resume update cap reached - applying with current profile resume.")

                    # ── READ APPLY BUTTON & DECIDE ────
                    apply_on_site = False
                    apply_btn_text = ""
                    for sel in ["button#apply-button", "a#apply-button",
                                "button.apply-button", "button:has-text('Apply')",
                                "a:has-text('Apply')", "button:has-text('apply')"]:
                        btn = new_page.locator(sel)
                        if btn.count() > 0:
                            apply_btn_text = btn.first.inner_text(timeout=3000).strip().lower()
                            print(f"  Apply button says: '{apply_btn_text}'")
                            break

                    site_keywords = ["company site", "company website", "external",
                                     "apply on", "visit site", "apply now on"]
                    if any(kw in apply_btn_text for kw in site_keywords):
                        apply_on_site = True

                    if apply_on_site:
                        print(f"  Apply on company website — capturing real link...")
                        company_apply_url = None

                        # 1) Best: read the external href straight off the anchor
                        try:
                            for sel in ["a#apply-button", "a.apply-button",
                                        "a:has-text('Apply')", "a:has-text('Company')"]:
                                a = new_page.locator(sel)
                                if a.count() > 0:
                                    href = a.first.get_attribute("href")
                                    if href and href.startswith("http") and "naukri.com" not in href:
                                        company_apply_url = href
                                        print(f"  Got company URL from link: {href[:60]}")
                                        break
                        except Exception:
                            pass

                        # 2) Else click, wait for the new tab AND its redirects to settle
                        if not company_apply_url:
                            try:
                                with new_page.context.expect_page(timeout=15000) as new_tab_info:
                                    new_page.locator(
                                        f"button:has-text('{apply_btn_text[:20]}')"
                                    ).first.click()
                                company_page = new_tab_info.value
                                company_page.wait_for_load_state("domcontentloaded", timeout=15000)
                                human_delay(3, 5)          # let JS/meta redirects finish
                                try:
                                    company_page.wait_for_load_state("networkidle", timeout=8000)
                                except Exception:
                                    pass
                                url_now = company_page.url
                                if url_now and "naukri.com" not in url_now:
                                    company_apply_url = url_now
                                    print(f"  Got company URL from new tab: {url_now[:60]}")
                                company_page.close()
                            except Exception as e:
                                print(f"  New-tab capture failed: {e}")

                        # 3) Else the same tab may have navigated off Naukri
                        if not company_apply_url:
                            try:
                                cur = new_page.url
                                if cur and "naukri.com" not in cur:
                                    company_apply_url = cur
                            except Exception:
                                pass

                        # 4) Last resort — keep the Naukri listing so it's at least reachable
                        if not company_apply_url:
                            company_apply_url = job_url
                            print("  Could not capture external URL — using Naukri link as fallback.")

                        # ── FRESH-URL WORKDAY AUTO-APPLY ──
                        # Stored links expire; apply NOW while the URL is live.
                        if "myworkdayjobs.com" in company_apply_url.lower():
                            print("  Workday site detected — attempting auto-apply now...")
                            try:
                                from workday_bot import apply_via_workday, notify_unknown_questions
                                wd_page = new_page.context.new_page()
                                ok, note = apply_via_workday(wd_page, {
                                    "url": company_apply_url,
                                    "title": job_title, "company": company,
                                    "summary": result.get("summary", ""),
                                })
                                try:
                                    wd_page.close()
                                except Exception:
                                    pass
                                if ok:
                                    log_application("naukri", company, job_title,
                                                     company_apply_url,
                                                     result['match_score'], status="Applied",
                                                     notes="Auto-applied on company Workday site")
                                    applied_count += 1
                                    print(f"  ✅ [Applied on Workday] {company} — {job_title}")
                                    new_page.close()
                                    human_delay(3, 5)
                                    continue
                                if "manual answer" in note.lower():
                                    notify_unknown_questions("naukri-workday", job_title,
                                                             company, company_apply_url, note)
                                print(f"  Workday auto-apply incomplete ({note}) — sending to dashboard.")
                            except Exception as _wde:
                                print(f"  Workday attempt error: {_wde} — sending to dashboard.")

                        add_manual_job(
                            platform="naukri",
                            job_title=job_title,
                            company=company,
                            job_url=company_apply_url,
                            match_score=result["match_score"],
                            cover_letter=result.get("cover_letter", ""),
                            summary=result["summary"]
                        )
                        print(f"  Email sent with company apply link.")
                        log_application("naukri", company, job_title, job_url,
                                         result['match_score'], status="Manual",
                                         notes="Apply on company website — email sent")
                        new_page.close()
                        human_delay(3, 5)
                        continue

                    # Normal Naukri apply
                    apply_btn = new_page.locator("button#apply-button, button:has-text('Apply')").first
                    apply_btn.click()
                    human_delay(2, 4)

                    # ── HANDLE QUESTIONNAIRE GATE ──
                    handle_questionnaire_gate(new_page)
                    human_delay(2, 3)

                    # Handle chatbot questions if they appear
                    for step in range(8):
                        chatbot_input = new_page.locator("div.chatbot_InputContainer input, div.chatbot_DivContainer input")
                        if chatbot_input.count() > 0:
                            question_el = new_page.locator("div.botMsg, div.chatbot_botMsg").last
                            question_text = question_el.inner_text(timeout=3000) if question_el.count() > 0 else ""

                            answer = find_answer_for_question(question_text)
                            if answer:
                                chatbot_input.first.fill(str(answer))
                                new_page.keyboard.press("Enter")
                                human_delay(2, 3)
                            else:
                                # Can't answer this Naukri question → hand the job to
                                # the dashboard (with the Naukri URL) so you finish it
                                # by hand, instead of dropping it silently.
                                add_manual_job(
                                    platform="naukri", job_title=job_title, company=company,
                                    job_url=job_url, match_score=result["match_score"],
                                    cover_letter=result.get("cover_letter", ""),
                                    summary=result.get("summary", ""),
                                )
                                log_application("naukri", company, job_title, job_url,
                                                 result['match_score'], status="Manual",
                                                 notes=f"Chatbot question needs manual answer: {question_text.strip()[:60]}")
                                send_error_alert(
                                    "naukri",
                                    f"Question sent to dashboard for '{job_title}' at '{company}': \"{question_text.strip()[:80]}\""
                                )
                                print("  → Naukri question I can't answer; sent to dashboard for manual apply.")
                                raise Exception("SENT_TO_DASHBOARD")
                        else:
                            break

                    # ── CONFIRMATION CHECK: poll a few times before giving up ──
                    confirmation_selectors = [
                        "text=successfully applied",
                        "text=Application sent",
                        "text=Applied successfully",
                        "text=You have successfully applied",
                        "div.apply-status-header",
                        "div[class*='success']",
                        "span:has-text('Applied')",
                        "button:has-text('Applied')",
                    ]
                    confirmed = False
                    for _c in range(4):          # ~10-12s total
                        human_delay(2, 3)
                        for sel in confirmation_selectors:
                            try:
                                if new_page.locator(sel).count() > 0:
                                    confirmed = True
                                    break
                            except Exception:
                                pass
                        if confirmed:
                            break

                    if confirmed:
                        log_application("naukri", company, job_title, job_url,
                                         result['match_score'], status="Applied")
                        applied_count += 1
                        print(f"  [Applied] {company} — {job_title} (score: {result['match_score']})")
                    else:
                        log_application("naukri", company, job_title, job_url,
                                         result['match_score'], status="Failed",
                                         notes="Apply clicked but confirmation not detected — may need manual check")
                        print(f"  [Not confirmed] {company} — {job_title} — logged as Failed (will retry later)")

                    new_page.close()
                    human_delay(8, 20)

                except Exception as e:
                    if "SENT_TO_DASHBOARD" in str(e):
                        pass  # already logged + routed to dashboard above
                    elif "UNKNOWN_QUESTION_SKIP" in str(e):
                        print("  Skipped due to unknown chatbot question (Telegram alert sent).")
                    else:
                        print(f"  Error on this job: {e}")
                    try:
                        new_page.close()
                    except Exception:
                        pass
                    human_delay(3, 6)
                    continue

        browser.close()

    print(f"\nNaukri done. Applied to {applied_count} jobs today. "
          f"Profile resume updated {resume_updates_today} times.")
    return applied_count


if __name__ == "__main__":
    run_naukri_bot()
