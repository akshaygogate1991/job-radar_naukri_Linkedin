"""
linkedin_manual_login.py  (NO PROXY — run on your LAPTOP)
──────────────────────────────────────────────────────────
Logs in over your normal home internet (fast + reliable).
  * Chrome opens
  * Log in manually
  * Wait until you see your FEED, then press ENTER
  * Session saves to logs/linkedin_session.json
Then upload logs/linkedin_session.json to the VPS.
"""

import json, os, time
from playwright.sync_api import sync_playwright

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "logs", "linkedin_session.json")

# Fingerprint identical to linkedin_bot.py's context
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def save_session_manually():
    print("=" * 55)
    print("  LinkedIn Session Saver  (home connection)")
    print("=" * 55)
    print()
    print("  1. Chrome opens")
    print("  2. Log into LinkedIn manually")
    print("  3. Wait until you SEE YOUR FEED (with posts)")
    print("  4. Come back here and press ENTER")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            no_viewport=True,
            user_agent=USER_AGENT,
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        print("Browser opened! Log in now...")
        print()
        input(">>> Press ENTER only AFTER you see your LinkedIn FEED (with posts)... ")

        time.sleep(3)

        try:
            current_url = page.url
        except Exception:
            current_url = ""
        print(f"\nDetected URL: {current_url}")

        # Safety check: warn if we're clearly still on a login/auth page
        if "login" in current_url or "checkpoint" in current_url or "authwall" in current_url:
            print("\n  !! You appear to still be on a login/verify page.")
            print("  !! Do NOT trust this session. Finish logging in and run again.")

        try:
            os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
            cookies = context.cookies()
            has_li_at = any(c.get("name") == "li_at" for c in cookies)
            with open(SESSION_FILE, "w") as f:
                json.dump(cookies, f)

            print()
            print("=" * 55)
            print(f"  Cookies saved: {len(cookies)}")
            print(f"  li_at (login token) present: {'YES' if has_li_at else 'NO'}")
            if has_li_at and len(cookies) > 5:
                print("  SESSION LOOKS GOOD! Upload it to the VPS now.")
            else:
                print("  SESSION LOOKS BAD. li_at missing = not logged in.")
                print("  Make sure you reached your feed, then run again.")
            print("=" * 55)
        except Exception as e:
            print("Error saving session: " + str(e))

        input("\nPress ENTER to close browser...")
        browser.close()


if __name__ == "__main__":
    save_session_manually()
