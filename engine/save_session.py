"""
One-time auth setup.
Opens Chrome, lets you log into YouTube manually, then saves the
browser session (cookies + localStorage) to auth.json so the main
script can reuse it without ever logging in again.
"""

from playwright.sync_api import sync_playwright
from pathlib import Path
import time

AUTH_FILE = "auth.json"

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )

        # No user_agent override - see engine/yt_auth.py: cookies minted under a
        # spoofed UA are replayed by runs using real Chrome, which Google may
        # treat as a stolen session.
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )

        page = context.new_page()
        page.goto("https://www.youtube.com", wait_until="domcontentloaded")

        print("\n" + "=" * 60)
        print("  Log into your Google / YouTube account in the browser.")
        print("  Take your time — complete any 2FA or verification steps.")
        print("  Once you can see your YouTube homepage feed,")
        print("  come back here and press ENTER.")
        print("=" * 60)
        input("  >> Press ENTER when logged in ... ")

        # Save the full session state
        context.storage_state(path=AUTH_FILE)
        print(f"\n  Session saved to '{AUTH_FILE}'.")
        print("  You won't need to log in again. Run the main script with:")
        print("  python3 youtube_reshaper.py\n")

        browser.close()

if __name__ == "__main__":
    main()
