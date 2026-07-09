"""
naukri_bot.py
─────────────
Automates Naukri.com applications:
  1. Logs in
  2. Searches for target roles (from profile.py)
  3. For each job:
       - Reads JD
       - Sends to Claude (resume_tailor.py) for match score + tailored resume
       - If match_score >= threshold:
           a. Generates tailored PDF
           b. Goes to profile -> uploads new resume (overwrites old one)
           c. Goes back to the job, clicks Apply
       - Logs result via tracker.py
  4. Stops after max_per_day_naukri applications
  5. Sends Telegram alert for unknown chatbot questions or errors

NOTE: Naukri uses the PROFILE resume for every apply - so the bot
updates the profile resume FIRST, then applies. This means applies
happen sequentially (cannot batch).

SAFETY:
  - Random delays between every action (8-20 sec)
  - Real (non-headless) browser
  - Stops immediately on CAPTCHA and alerts via Telegram
  - Limits profile resume updates to avoid suspicion
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


def update_naukri_resume(page, pdf_path: str) -> bool:
    """Go to profile page and upload new resume, replacing the old one."""
    try:
        page.goto("https://www.naukri.com/mnjuser/profile")
        human_delay(3, 5)

        # Naukri profile resume upload button
        upload_input = page.locator("input#attachCV, input[type='file'][name='file']")
        if upload_input.count() == 0:
            # Sometimes hidden behind a button
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
    max_resume_updates = 12  # safety cap per day

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

        # ── 2. SEARCH FOR EACH ROLE ──────────────────────────
        for role in SEARCH["roles"]:
            if applied_count >= max_apply:
                break

            for location in SEARCH["locations"]:
                if applied_count >= max_apply:
                    break

                naukri_location = "" if location.lower() == "remote" else location
                print(f"\nSearching: '{role}' in '{location}'...")

                # Build Naukri search URL with freshness filter
                role_slug = role.lower().replace(' ', '-')
                search_url = f"https://www.naukri.com/{role_slug}-jobs"
                if naukri_location:
                    loc_slug = naukri_location.lower().replace(' ', '-')
                    search_url += f"-in-{loc_slug}"
                # Add experience and freshness filters
                search_url += "?jobAge=3&experience=7"  # last 3 days, 7+ years exp

                page.goto(search_url)
                human_delay(3, 6)

                job_cards = page.locator("div.srp-jobtuple-wrapper, article.jobTuple").all()
                print(f"Found {len(job_cards)} job listings")

                for card in job_cards:
                    if applied_count >= max_apply:
                        break

                    try:
                        # Open job in new tab to keep search results intact
                        job_link = card.locator("a.title, a.title.fw500").first
                        job_title = job_link.inner_text(timeout=5000).strip()
                        job_url = job_link.get_attribute("href")

                        company_locator = card.locator("a.comp-name, .companyInfo a")
                        company = company_locator.first.inner_text(timeout=5000).strip() if company_locator.count() > 0 else "Unknown"

                        print(f"\n→ {job_title} at {company}")

                        if already_applied(company, job_title):
                            print("  Already applied recently. Skipping.")
                            continue

                        # Open job detail page
                        new_page = context.new_page()
                        new_page.goto(job_url)
                        human_delay(3, 5)

                        # Get JD text
                        jd_text = new_page.locator("div.styles_JDC__dang-inner-html__h0K4t, div.job-desc").first.inner_text(timeout=8000)

                        # ── 3. CLAUDE TAILORING ──────────────
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

                        # ── 4. GENERATE TAILORED PDF ─────────
                        pdf_path = generate_tailored_resume(
                            job_title=job_title,
                            company=company,
                            summary=result['summary'],
                            skills=result['skills']
                        )

                        # ── 5. UPDATE PROFILE RESUME (Naukri-specific!) ──
                        if resume_updates_today < max_resume_updates:
                            updated = update_naukri_resume(new_page, pdf_path)
                            if updated:
                                resume_updates_today += 1
                            human_delay(3, 6)
                            # Go back to job page
                            new_page.goto(job_url)
                            human_delay(2, 4)
                        else:
                            print("  Daily resume update cap reached - applying with current profile resume.")

                        # ── 6. READ APPLY BUTTON & DECIDE ────
                        # Check what the apply button says
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

                        # Detect "Apply on company site" variants
                        site_keywords = ["company site", "company website", "external",
                                         "apply on", "visit site", "apply now on"]
                        if any(kw in apply_btn_text for kw in site_keywords):
                            apply_on_site = True

                        if apply_on_site:
                            # Click to get company URL then send email
                            print(f"  Apply on company website — opening link...")
                            try:
                                with new_page.context.expect_page() as new_tab_info:
                                    new_page.locator(f"button:has-text('{apply_btn_text[:20]}')").first.click()
                                    human_delay(2, 3)
                                company_page = new_tab_info.value
                                company_apply_url = company_page.url
                                company_page.close()
                            except Exception:
                                company_apply_url = job_url

                            # Send email with link
                            from notifier import send_email
                            # Send email with link
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
                            # Log as Manual so it won't be revisited
                            log_application("naukri", company, job_title, job_url,
                                             result['match_score'], status="Manual",
                                             notes="Apply on company website — email sent")
                            new_page.close()
                            human_delay(3, 5)
                            continue

                        # Normal Naukri apply — click the button
                        apply_btn = new_page.locator("button#apply-button, button:has-text('Apply')").first
                        apply_btn.click()
                        human_delay(2, 4)

                        # Handle chatbot questions if they appear
                        for step in range(8):
                            chatbot_input = new_page.locator("div.chatbot_InputContainer input, div.chatbot_DivContainer input")
                            if chatbot_input.count() > 0:
                                # Get question text
                                question_el = new_page.locator("div.botMsg, div.chatbot_botMsg").last
                                question_text = question_el.inner_text(timeout=3000) if question_el.count() > 0 else ""

                                answer = find_answer_for_question(question_text)
                                if answer:
                                    chatbot_input.first.fill(str(answer))
                                    new_page.keyboard.press("Enter")
                                    human_delay(2, 3)
                                else:
                                    send_error_alert(
                                        "naukri",
                                        f"Unknown chatbot question for '{job_title}' at '{company}': \"{question_text.strip()}\". Job skipped."
                                    )
                                    raise Exception("UNKNOWN_QUESTION_SKIP")
                            else:
                                break

                        # Check confirmation
                        success_msg = new_page.locator("text=successfully applied, text=Application sent")
                        if success_msg.count() > 0:
                            log_application("naukri", company, job_title, job_url,
                                             result['match_score'], status="Applied")
                            applied_count += 1
                        else:
                            log_application("naukri", company, job_title, job_url,
                                             result['match_score'], status="Applied",
                                             notes="Apply clicked, confirmation not detected")
                            applied_count += 1

                        new_page.close()
                        human_delay(8, 20)

                    except Exception as e:
                        if "UNKNOWN_QUESTION_SKIP" in str(e):
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
