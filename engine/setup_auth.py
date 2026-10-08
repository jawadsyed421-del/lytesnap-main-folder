"""
setup_auth.py — Opens Chrome, navigates to YouTube, waits for the user to log
in, then auto-saves the session to auth.json.

Unlike save_session.py this script never calls input() so it can be safely
spawned from Electron without blocking on stdin.
"""

from playwright.sync_api import sync_playwright
from pathlib import Path
import sys
import argparse

TIMEOUT_MS = 300_000  # 5 minutes
CHROME_REQUIRED_EXIT = 2


def _launch_chrome(pw):
    """Launch Google Chrome; exit with CHROME_REQUIRED_EXIT if Chrome is missing."""
    try:
        return pw.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1280,800"],
        )
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("channel", "chrome", "executable", "browser")):
            print("[auth] Google Chrome is required for YouTube sign-in.")
            print("[auth] Install Chrome from https://www.google.com/chrome/ then try again.")
            sys.stdout.flush()
            sys.exit(CHROME_REQUIRED_EXIT)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None, help="Writable directory to save auth.json into")
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).parent.parent
    data_dir.mkdir(parents=True, exist_ok=True)
    AUTH_FILE = str(data_dir / "auth.json")

    print("[auth] Opening Chrome — please sign into YouTube...")
    sys.stdout.flush()

    with sync_playwright() as pw:
        browser = _launch_chrome(pw)

        # No user_agent override: cookies must be minted under the same UA that
        # later replays them. This used to claim macOS/Chrome 124 while every
        # measurement run used real Windows Chrome - a device-signal mismatch
        # Google can treat as session theft.
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )

        page = context.new_page()
        page.goto("https://www.youtube.com", wait_until="domcontentloaded")

        print("[auth] Waiting for YouTube login (up to 5 minutes)...")
        sys.stdout.flush()

        # Wait for the signed-in avatar button — appears once login is complete
        try:
            page.wait_for_selector("button#avatar-btn", timeout=TIMEOUT_MS)
        except Exception:
            print("[auth] Timed out waiting for login. Please try again.")
            sys.stdout.flush()
            browser.close()
            sys.exit(1)

        context.storage_state(path=AUTH_FILE)
        print(f"[auth] Session saved to {AUTH_FILE}. You're all set.")
        sys.stdout.flush()

        browser.close()

if __name__ == "__main__":
    main()
