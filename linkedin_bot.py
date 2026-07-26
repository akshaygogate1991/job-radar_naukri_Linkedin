"""
linkedin_bot.py — Search-panel approach
────────────────────────────────────────
Stay on search results page. Click each card. Right panel opens.
Click '...more' to expand JD. Read everything from the panel.
"""

import time, random, sys, os, json
from playwright.sync_api import sync_playwright

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.profile import CANDIDATE, SEARCH, PLATFORMS, EASY_APPLY_ANSWERS
from resume_tailor import tailor_resume, should_apply
from tracker import already_applied, log_application
from notifier import send_email, send_error_alert, add_manual_job
from pdf_generator import generate_tailored_resume

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "logs", "linkedin_session.json")


def human_delay(a=2, b=5):
    time.sleep(random.uniform(a, b))


def find_answer(q):
    for kw, ans in EASY_APPLY_ANSWERS.items():
        if kw in q.lower():
            return ans
    return None


def save_session(context):
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump(context.cookies(), f)


def load_session(context):
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE) as f:
                context.add_cookies(json.load(f))
            return True
        except Exception:
            pass
    return False


def run_linkedin_bot():
    creds = PLATFORMS["linkedin"]
    if not creds["enabled"]:
        print("LinkedIn disabled in profile.py")
        return 0

    applied_count = 0
    max_apply     = SEARCH["max_per_day_linkedin"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        load_session(context)
        page = context.new_page()

        # ── Check session ─────────────────────────────────────
        print("Checking LinkedIn session...")
        page.goto("https://www.linkedin.com/feed/",
                  wait_until="domcontentloaded", timeout=30000)
        human_delay(3, 5)

        if "login" in page.url or "authwall" in page.url:
            print("Session expired. Run linkedin_manual_login.py first.")
            browser.close()
            return 0

        print("  Session valid!")
        save_session(context)

        # ── Search jobs ───────────────────────────────────────
        for role in SEARCH["roles"]:
            if applied_count >= max_apply:
                break
            for location in SEARCH["locations"]:
                if applied_count >= max_apply:
                    break

                print(f"\nSearching: '{role}' in '{location}'...")

                keywords = role.replace(' ', '%20')
                loc      = location.replace(' ', '%20')
                # No f_AL filter = all jobs, f_TPR=r604800 = past week
                # geoId=102713980 = India, ensures Indian jobs only
                search_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={keywords}&location={loc}"
                    f"&geoId=102713980&f_TPR=r604800&sortBy=DD&start=0"
                )
                page.goto(search_url, wait_until="domcontentloaded", timeout=40000)
                human_delay(5, 8)

                # Scroll to load all cards
                for _ in range(5):
                    page.evaluate("window.scrollBy(0, 500)")
                    human_delay(0.5, 1)
                page.evaluate("window.scrollTo(0, 0)")
                human_delay(2, 3)

                # Get all job cards
                cards = page.locator("li.jobs-search-results__list-item").all()
                if not cards:
                    cards = page.locator("div.job-card-container").all()

                print(f"  Found {len(cards)} jobs")
                if not cards:
                    continue

                for i, card in enumerate(cards):
                    if applied_count >= max_apply:
                        break
                    try:
                        # Click card to open right panel
                        card.scroll_into_view_if_needed()
                        human_delay(1, 2)
                        card.click()
                        human_delay(3, 5)

                        # ── Read job title ────────────────────
                        job_title = ""
                        for sel in [
                            "div.job-details-jobs-unified-top-card__job-title h1",
                            "h1.t-24.t-bold.inline",
                            "h1.t-24",
                            ".jobs-unified-top-card__job-title h1",
                            "h2.top-card-layout__title",
                            "h1",
                        ]:
                            try:
                                el = page.locator(sel).first
                                if el.count() > 0 and el.is_visible():
                                    txt = el.inner_text(timeout=4000).strip()
                                    if txt and len(txt) > 2:
                                        job_title = txt
                                        break
                            except Exception:
                                continue

                        # ── Read company name ─────────────────
                        company = ""
                        for sel in [
                            "div.job-details-jobs-unified-top-card__company-name a",
                            "span.job-details-jobs-unified-top-card__company-name",
                            ".jobs-unified-top-card__company-name a",
                            ".jobs-unified-top-card__subtitle-primary-grouping a",
                            "a.ember-view.t-black.t-normal",
                        ]:
                            try:
                                el = page.locator(sel).first
                                if el.count() > 0 and el.is_visible():
                                    txt = el.inner_text(timeout=3000).strip()
                                    if txt and len(txt) > 1:
                                        company = txt
                                        break
                            except Exception:
                                continue

                        # Fallback: page title
                        if not job_title or not company:
                            try:
                                t = page.title().replace(" | LinkedIn", "").strip()
                                if " hiring " in t.lower():
                                    idx = t.lower().find(" hiring ")
                                    company   = t[:idx].strip()
                                    job_title = t[idx+8:].split(" in ")[0].strip()
                                elif " at " in t:
                                    parts = t.split(" at ")
                                    job_title = job_title or parts[0].strip()
                                    company   = company or parts[-1].strip()
                            except Exception:
                                pass

                        if not job_title or not company:
                            print(f"  Card {i+1}: could not read title/company")
                            continue

                        print(f"\n→ {job_title} at {company}")

                        job_url = page.url

                        if already_applied(company, job_title):
                            print("  Already applied. Skipping.")
                            continue

                        # ── Expand full JD ────────────────────
                        # Click "...more" or "Show more" in About the job section
                        for more_sel in [
                            "button.jobs-description__footer-button",
                            "button[aria-label*='more']",
                            "button.show-more-less-html__button--more",
                            "footer.jobs-description__footer button",
                            "button:has-text('more')",
                        ]:
                            try:
                                btn = page.locator(more_sel).first
                                if btn.count() > 0 and btn.is_visible():
                                    btn.click(timeout=3000)
                                    human_delay(1, 2)
                                    print("  JD expanded.")
                                    break
                            except Exception:
                                continue

                        # ── Read JD text ──────────────────────
                        jd_text = ""
                        for sel in [
                            "div.jobs-description-content__text",
                            "div#job-details",
                            "div.jobs-description__content",
                            "article.jobs-description__container",
                            "div.show-more-less-html__markup",
                            "div.description__text",
                        ]:
                            try:
                                el = page.locator(sel).first
                                if el.count() > 0:
                                    txt = el.inner_text(timeout=5000).strip()
                                    if len(txt) > 100:
                                        jd_text = txt
                                        break
                            except Exception:
                                continue

                        if not jd_text:
                            print("  No JD text found. Skipping.")
                            continue

                        print(f"  JD length: {len(jd_text)} chars")

                        # ── Read apply button ─────────────────
                        apply_btn_text = ""
                        for sel in [
                            "div.jobs-apply-button--top-card button",
                            "button.jobs-apply-button",
                            ".jobs-apply-button",
                        ]:
                            try:
                                el = page.locator(sel).first
                                if el.count() > 0:
                                    apply_btn_text = el.inner_text(timeout=3000).strip().lower()
                                    if apply_btn_text:
                                        break
                            except Exception:
                                continue

                        print(f"  Button: '{apply_btn_text}'")

                        # ── Claude scoring ────────────────────
                        print("  Sending to Claude...")
                        result = tailor_resume(job_title, company, jd_text)

                        if not should_apply(result):
                            print(f"  Match {result['match_score']}% — skip.")
                            log_application("linkedin", company, job_title,
                                            job_url, result['match_score'],
                                            status="Skipped",
                                            notes=result['match_reason'])
                            continue

                        print(f"  Match {result['match_score']}% — applying!")

                        # Generate tailored PDF
                        pdf_path = generate_tailored_resume(
                            job_title, company,
                            result['summary'], result['skills']
                        )

                        # ── External website ──────────────────
                        if apply_btn_text and "easy apply" not in apply_btn_text:
                            # Click Apply and capture the REAL company URL from
                            # the new tab (fresh URLs work; stored ones expire).
                            external_url = job_url
                            ext_tab = None
                            try:
                                with page.context.expect_page(timeout=12000) as _tab:
                                    page.locator(
                                        "div.jobs-apply-button--top-card button,"
                                        "button.jobs-apply-button"
                                    ).first.click()
                                ext_tab = _tab.value
                                ext_tab.wait_for_load_state("domcontentloaded", timeout=15000)
                                human_delay(3, 5)
                                if ext_tab.url and "linkedin.com" not in ext_tab.url:
                                    external_url = ext_tab.url
                                    print(f"  Captured company URL: {external_url[:60]}")
                            except Exception as _e:
                                print(f"  Could not capture external URL: {_e}")

                            # Workday? → auto-apply right now on the live tab
                            if ext_tab and "myworkdayjobs.com" in external_url.lower():
                                print("  Workday site — attempting auto-apply now...")
                                try:
                                    from workday_bot import apply_via_workday, notify_unknown_questions
                                    ok, note = apply_via_workday(ext_tab, {
                                        "url": external_url,
                                        "title": job_title, "company": company,
                                        "summary": result.get("summary", ""),
                                    })
                                    if ok:
                                        log_application("linkedin", company, job_title,
                                                        external_url, result['match_score'],
                                                        status="Applied",
                                                        notes="Auto-applied on company Workday site")
                                        print(f"  ✅ [Applied on Workday] {company} — {job_title}")
                                        try:
                                            ext_tab.close()
                                        except Exception:
                                            pass
                                        human_delay(2, 4)
                                        continue
                                    if "manual answer" in note.lower():
                                        notify_unknown_questions("linkedin-workday", job_title,
                                                                 company, external_url, note)
                                    print(f"  Workday auto-apply incomplete ({note}) — to dashboard.")
                                except Exception as _wde:
                                    print(f"  Workday attempt error: {_wde} — to dashboard.")
                            try:
                                if ext_tab:
                                    ext_tab.close()
                            except Exception:
                                pass

                            print(f"  [DIGEST EMAIL] {job_title} at {company} — link will be emailed to you")
                            add_manual_job(
                                platform="linkedin",
                                job_title=job_title,
                                company=company,
                                job_url=external_url,
                                match_score=result['match_score'],
                                cover_letter=result.get('cover_letter', ''),
                                summary=result['summary']
                            )
                            log_application("linkedin", company, job_title,
                                            job_url, result['match_score'],
                                            status="Manual",
                                            notes="External — digest")
                            # External jobs go to digest only — not counted as applied
                            human_delay(2, 4)
                            continue

                        # ── Easy Apply ────────────────────────
                        try:
                            easy_btn = page.locator(
                                "div.jobs-apply-button--top-card button,"
                                "button.jobs-apply-button"
                            ).first
                            easy_btn.click()
                            human_delay(2, 4)
                        except Exception as e:
                            print(f"  Could not click Easy Apply: {e}")
                            continue

                        applied = False
                        for step in range(7):
                            human_delay(1, 2)

                            # ── Upload resume ─────────────────
                            file_input = page.locator("input[type='file']")
                            if file_input.count() > 0:
                                try:
                                    file_input.first.set_input_files(pdf_path)
                                    human_delay(1, 2)
                                except Exception:
                                    pass

                            skip_job = False

                            # ── Fill text / number inputs ──────
                            inputs = page.locator(
                                "div.jobs-easy-apply-form-section__grouping input[type='text'],"
                                "div.jobs-easy-apply-form-section__grouping input[type='number']"
                            )
                            for j in range(inputs.count()):
                                inp = inputs.nth(j)
                                try:
                                    label = inp.locator(
                                        "xpath=ancestor::div[contains(@class,'form-element')][1]"
                                    ).inner_text(timeout=2000)
                                except Exception:
                                    label = ""
                                if inp.input_value() == "":
                                    ans = find_answer(label)
                                    if ans:
                                        inp.fill(str(ans))
                                    else:
                                        send_error_alert("linkedin",
                                            f"Unknown Q: '{label[:60]}' for {job_title} @ {company}")
                                        skip_job = True
                                        break

                            # ── Handle dropdowns (select) ──────
                            if not skip_job:
                                dropdowns = page.locator(
                                    "div.jobs-easy-apply-form-section__grouping select"
                                )
                                for j in range(dropdowns.count()):
                                    dd = dropdowns.nth(j)
                                    try:
                                        label = dd.locator(
                                            "xpath=ancestor::div[contains(@class,'form-element')][1]"
                                        ).inner_text(timeout=2000)
                                    except Exception:
                                        label = ""
                                    current_val = dd.evaluate("el => el.value")
                                    if not current_val or current_val == "":
                                        ans = find_answer(label)
                                        if ans:
                                            # Try to select by value or label text
                                            try:
                                                dd.select_option(label=ans)
                                            except Exception:
                                                try:
                                                    dd.select_option(value=ans)
                                                except Exception:
                                                    pass

                            # ── Handle radio buttons ───────────
                            if not skip_job:
                                # Get all fieldsets (radio groups)
                                fieldsets = page.locator(
                                    "div.jobs-easy-apply-form-section__grouping fieldset"
                                )
                                for j in range(fieldsets.count()):
                                    fs = fieldsets.nth(j)
                                    try:
                                        legend = fs.locator("legend").inner_text(timeout=2000)
                                    except Exception:
                                        legend = ""
                                    # Check if any radio already selected
                                    checked = fs.locator("input[type='radio']:checked")
                                    if checked.count() > 0:
                                        continue  # already answered
                                    ans = find_answer(legend)
                                    if ans:
                                        # Find radio button with matching label
                                        radios = fs.locator("input[type='radio']")
                                        for k in range(radios.count()):
                                            radio = radios.nth(k)
                                            try:
                                                radio_label = radio.locator(
                                                    "xpath=following-sibling::label[1]"
                                                ).inner_text(timeout=1000)
                                            except Exception:
                                                radio_label = ""
                                            if radio_label.strip().lower() == ans.lower():
                                                radio.click()
                                                human_delay(0.5, 1)
                                                break
                                    else:
                                        send_error_alert("linkedin",
                                            f"Unknown radio Q: '{legend[:60]}' for {job_title} @ {company}")
                                        skip_job = True
                                        break

                            if skip_job:
                                # Close modal and move on
                                for d in ["button[aria-label='Dismiss']", "button[aria-label='Cancel']"]:
                                    btn = page.locator(d)
                                    if btn.count() > 0:
                                        btn.first.click()
                                        break
                                human_delay(1, 2)
                                dis = page.locator("button:has-text('Discard')")
                                if dis.count() > 0:
                                    dis.first.click()
                                break

                            human_delay(1, 2)

                            # ── Submit ─────────────────────────
                            submit = page.locator("button[aria-label='Submit application']")
                            if submit.count() > 0:
                                submit.first.click()
                                human_delay(2, 4)
                                done = page.locator("button[aria-label='Dismiss']")
                                if done.count() > 0:
                                    done.first.click()
                                applied = True
                                break

                            # ── Next / Review ──────────────────
                            nxt = page.locator(
                                "button[aria-label='Continue to next step'],"
                                "button[aria-label='Review your application']"
                            )
                            if nxt.count() > 0:
                                nxt.first.click()
                                human_delay(2, 4)
                            else:
                                break

                        if applied:
                            log_application("linkedin", company, job_title,
                                            job_url, result['match_score'],
                                            status="Applied")
                            applied_count += 1
                            print(f"  [Applied] ✓")

                        # Close any open modal before moving to next card
                        for dismiss_sel in [
                            "button[aria-label='Dismiss']",
                            "button[data-test-modal-close-btn]",
                            "button[aria-label='Cancel']",
                        ]:
                            try:
                                btn = page.locator(dismiss_sel)
                                if btn.count() > 0 and btn.first.is_visible():
                                    btn.first.click()
                                    human_delay(1, 2)
                                    break
                            except Exception:
                                pass
                        # Press Escape to close any remaining modal
                        try:
                            page.keyboard.press("Escape")
                            human_delay(1, 2)
                        except Exception:
                            pass

                        human_delay(5, 10)

                    except Exception as e:
                        print(f"  Error on card {i+1}: {e}")
                        human_delay(3, 6)
                        continue

        browser.close()

    print(f"\nLinkedIn done. Applied to {applied_count} jobs.")
    return applied_count


if __name__ == "__main__":
    run_linkedin_bot()
