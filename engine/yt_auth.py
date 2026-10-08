"""
yt_auth.py - desktop YouTube authentication / cookie flow
=========================================================

Why this module exists
----------------------
Every entry point in this project used to do the same thing: launch Chrome,
hand it `storage_state=auth.json`, browse, throw the context away. That has two
problems on a real Google account:

  1. Google rotates short-lived cookies (`__Secure-1PSIDRTS`, `__Secure-3PSIDRTS`,
     `ST-*`, `GPS`) on practically every visit. A thrown-away context takes those
     refreshed values with it, so auth.json keeps serving values Google has
     already moved past. The snapshot can only decay.
  2. "auth.json exists" was treated as "logged in". An expired or revoked
     session looks identical on disk, so a measurement run would open a
     signed-out feed and score it as if it were the account's feed.

So: a persistent Chrome profile is the source of truth (cookies rotate in place,
the way a real browser works), and auth.json becomes an exported snapshot kept
in sync for the rest of the project, which still reads it.

Layout
------
    chrome_profile/   persistent Chrome user-data dir (gitignored) - source of truth
    auth.json         exported Playwright storage_state (gitignored) - compat snapshot

Both are already in .gitignore. Neither should ever be committed.

API
---
    open_context(pw, logger)        -> (context, close_fn), profile-backed
    export_state(context, logger)   -> refresh auth.json from the live context
    verify_live(page, logger)       -> {"logged_in": bool, "account": str|None}
    inspect_auth_file()             -> offline cookie health, no browser
    login(logger)                   -> interactive login into the profile
    seed_profile_from_auth(logger)  -> one-time migration of auth.json -> profile
"""

import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import session_store
from session_store import SessionStoreError

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Both stores hang off one data dir so several accounts can run side by side on
# one machine, each with its own session and its own Chrome profile. Matches the
# --data-dir convention already used by youtube_reshaper.py and setup_auth.py.
DATA_DIR = PROJECT_DIR
AUTH_FILE = DATA_DIR / "auth.json"
PROFILE_DIR = DATA_DIR / "chrome_profile"


def set_data_dir(path) -> Path:
    """Point auth.json and chrome_profile at `path`. Call before any auth work."""
    global DATA_DIR, AUTH_FILE, PROFILE_DIR
    DATA_DIR = Path(path).resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_FILE = DATA_DIR / "auth.json"
    PROFILE_DIR = DATA_DIR / "chrome_profile"
    return DATA_DIR

VIEWPORT = {"width": 1280, "height": 800}
YOUTUBE = "https://www.youtube.com"

# Cookies that actually carry the session. If these are gone or expired the
# account is not signed in, whatever else the file contains.
CRITICAL_COOKIES = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO",
}

# Short-lived cookies Google re-issues on nearly every visit. Expired copies of
# these are the normal signature of a stale snapshot, not of a dead session.
ROTATING_COOKIES = {
    "__Secure-1PSIDRTS", "__Secure-3PSIDRTS", "GPS",
    "__Secure-1PSIDCC", "__Secure-3PSIDCC", "SIDCC",
}

CHROME_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--window-size=1280,800",
    "--mute-audio",
]

CHROME_REQUIRED_EXIT = 2


# ---------------------------------------------------------------------------
# Offline inspection - answers "is this session usable?" without a browser
# ---------------------------------------------------------------------------

def inspect_auth_file(path: Path = None) -> dict:
    """Cookie health of a storage_state file. No browser, no network."""
    path = Path(path) if path else AUTH_FILE
    out = {
        "path": str(path),
        "exists": path.exists() or session_store.enc_path(DATA_DIR).exists(),
        "encrypted": False,
        "usable": False,
        "cookies": 0,
        "expired": [],
        "expired_rotating": [],
        "expired_critical": [],
        "missing_critical": [],
        "soonest_critical_days": None,
        "local_storage_keys": 0,
        "age_days": None,
        "problems": [],
    }
    enc = session_store.enc_path(DATA_DIR)
    if not path.exists() and not enc.exists():
        out["problems"].append("no stored session - run: measure_feed.py auth --login")
        return out

    try:
        data = session_store.load(DATA_DIR) or {}
    except SessionStoreError as e:
        out["problems"].append(str(e))
        return out
    if not data:
        out["problems"].append("the stored session is empty")
        return out

    newest = enc if enc.exists() else path
    out["path"] = str(newest)
    out["encrypted"] = enc.exists()
    out["age_days"] = round((time.time() - newest.stat().st_mtime) / 86400, 2)
    cookies = data.get("cookies") or []
    out["cookies"] = len(cookies)
    if not cookies:
        out["problems"].append("auth.json contains no cookies")
        return out

    now = time.time()
    present = set()
    critical_days = []
    for c in cookies:
        name = c.get("name", "")
        present.add(name)
        expires = c.get("expires", -1)
        if expires and expires > 0:
            days = (expires - now) / 86400
            if days < 0:
                out["expired"].append(name)
                if name in ROTATING_COOKIES:
                    out["expired_rotating"].append(name)
                elif name in CRITICAL_COOKIES:
                    out["expired_critical"].append(name)
            elif name in CRITICAL_COOKIES:
                critical_days.append(days)

    out["missing_critical"] = sorted(CRITICAL_COOKIES - present)
    if critical_days:
        out["soonest_critical_days"] = round(min(critical_days), 1)

    for origin in data.get("origins") or []:
        out["local_storage_keys"] += len(origin.get("localStorage") or [])

    if out["missing_critical"]:
        out["problems"].append("missing session cookies: " + ", ".join(out["missing_critical"]))
    if out["expired_critical"]:
        out["problems"].append("EXPIRED session cookies: " + ", ".join(sorted(set(out["expired_critical"]))))
    if out["expired_rotating"]:
        out["problems"].append(
            "stale rotating cookies (%s) - snapshot is behind Google; "
            "'auth --live' or any measurement run will refresh them"
            % ", ".join(sorted(set(out["expired_rotating"])))
        )

    out["usable"] = not out["missing_critical"] and not out["expired_critical"]
    return out


def format_inspection(info: dict) -> str:
    lines = ["  auth file:  " + info["path"]]
    if not info["exists"]:
        lines.append("  status:     MISSING")
        for p in info["problems"]:
            lines.append("  ! " + p)
        return "\n".join(lines)
    lines.append("  status:     " + ("usable" if info["usable"] else "NOT usable"))
    lines.append("  storage:    " + ("encrypted" if info.get("encrypted") else "PLAINTEXT"))
    lines.append("  cookies:    %d (%d expired)" % (info["cookies"], len(info["expired"])))
    if info["soonest_critical_days"] is not None:
        lines.append("  session cookies expire in: %.1f days" % info["soonest_critical_days"])
    lines.append("  localStorage keys: %d" % info["local_storage_keys"])
    lines.append("  last written: %.2f days ago" % (info["age_days"] or 0))
    for p in info["problems"]:
        lines.append("  ! " + p)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Profile-backed context
# ---------------------------------------------------------------------------

def profile_is_populated() -> bool:
    """True if chrome_profile looks like a real Chrome user-data dir."""
    if not PROFILE_DIR.exists():
        return False
    for marker in ("Default/Cookies", "Default/Preferences", "Local State"):
        if (PROFILE_DIR / marker).exists():
            return True
    return False


def _launch_persistent(pw, logger, headless: bool = False):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=headless,
            viewport=VIEWPORT,
            locale="en-US",
            args=CHROME_LAUNCH_ARGS,
        )
        return context
    except Exception as e:
        msg = str(e).lower()
        if "profile" in msg or "singletonlock" in msg or "in use" in msg:
            raise SystemExit(
                "Chrome profile at %s is locked - another Chrome or another run is "
                "using it. Close it and retry." % PROFILE_DIR
            )
        if any(k in msg for k in ("channel", "executable", "chrome")):
            logger.error("Google Chrome is required for YouTube sign-in. "
                         "Install it from https://www.google.com/chrome/")
            sys.exit(CHROME_REQUIRED_EXIT)
        raise


def load_session() -> dict:
    """The stored session as a dict, decrypted if needed. {} when absent."""
    try:
        return session_store.load(DATA_DIR) or {}
    except SessionStoreError as e:
        raise SystemExit("Cannot read the stored session: %s" % e)


def _storage_state_cookies(path: Path = None) -> list:
    if path:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8")).get("cookies") or []
        except Exception:
            return []
    return load_session().get("cookies") or []


def _storage_state_local(path: Path = None) -> dict:
    """{origin: [items]} of localStorage, from the stored session."""
    if path:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return {}
    else:
        data = load_session()
    return {o["origin"]: (o.get("localStorage") or [])
            for o in (data.get("origins") or []) if o.get("origin")}


def _drop_expired(cookies: list) -> list:
    """Never inject already-expired cookies - Chrome rejects the batch."""
    now = time.time()
    keep = []
    for c in cookies:
        e = c.get("expires", -1)
        if e and e > 0 and e <= now:
            continue
        keep.append(c)
    return keep


def seed_profile_from_auth(logger, headless: bool = False) -> bool:
    """One-time migration: push auth.json's cookies into a fresh profile.

    Saves re-doing 2FA when switching from snapshot auth to profile auth.
    """
    from playwright.sync_api import sync_playwright

    if not load_session():
        logger.error("No stored session to seed from - run: measure_feed.py auth --login")
        return False

    info = inspect_auth_file()
    if not info["usable"]:
        logger.error("the stored session is not usable, refusing to seed from it:")
        for p in info["problems"]:
            logger.error("  ! " + p)
        return False

    cookies = _drop_expired(_storage_state_cookies())
    local = _storage_state_local()
    logger.info("Seeding %s with %d cookies from the stored session ..."
                % (PROFILE_DIR.name, len(cookies)))

    with sync_playwright() as pw:
        context = _launch_persistent(pw, logger, headless=headless)
        try:
            context.add_cookies(cookies)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(YOUTUBE, wait_until="domcontentloaded", timeout=30000)
            _restore_local_storage(page, local, logger)
            state = verify_with_retry(page, logger)
            if state["logged_in"]:
                logger.info("Profile seeded and signed in%s."
                            % (" as " + state["account"] if state["account"] else ""))
                return True
            logger.error("Profile seeded but YouTube reports signed out - "
                         "run: measure_feed.py auth --login")
            return False
        finally:
            try:
                context.close()
            except Exception:
                pass


def _restore_local_storage(page, local_by_origin: dict, logger) -> None:
    """Replay saved localStorage for the origin currently loaded."""
    items = local_by_origin.get(YOUTUBE) or local_by_origin.get("https://youtube.com")
    if not items:
        return
    try:
        page.evaluate(
            "(items) => { for (const it of items) {"
            " try { localStorage.setItem(it.name, it.value); } catch (e) {} } }",
            items,
        )
        logger.debug("Restored %d localStorage keys" % len(items))
    except Exception as e:
        logger.debug("localStorage restore skipped: %s" % e)


def open_context(pw, logger, headless: bool = False, allow_snapshot: bool = True):
    """Open an authenticated context. Returns (context, close_fn).

    Prefers the persistent profile so rotating cookies refresh in place. Falls
    back to the auth.json snapshot when no profile exists yet, which keeps this
    drop-in compatible with how the rest of the project authenticates.
    """
    if profile_is_populated():
        logger.info("Auth: persistent profile (%s)" % PROFILE_DIR.name)
        context = _launch_persistent(pw, logger, headless=headless)

        def close():
            try:
                context.close()
            except Exception:
                pass

        return context, close

    if not allow_snapshot:
        raise SystemExit(
            "No Chrome profile at %s - run: measure_feed.py auth --login" % PROFILE_DIR
        )

    info = inspect_auth_file()
    if not info["exists"] or not info["usable"]:
        logger.error("Cannot authenticate:")
        logger.error(format_inspection(info))
        raise SystemExit("Authentication unavailable - run: measure_feed.py auth --login")

    logger.warning("Auth: auth.json snapshot (no persistent profile yet). "
                   "Rotating cookies will NOT refresh in place - consider: "
                   "measure_feed.py auth --migrate")
    browser = pw.chromium.launch(channel="chrome", headless=headless, args=CHROME_LAUNCH_ARGS)
    # Hand Playwright the decrypted dict, not a path: with an encrypted store
    # the plaintext session never exists as a file.
    context = browser.new_context(
        viewport=VIEWPORT,
        locale="en-US",
        storage_state=load_session(),
    )

    def close():
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass

    return context, close


# ---------------------------------------------------------------------------
# Live verification
# ---------------------------------------------------------------------------

def verify_live(page, logger) -> dict:
    """Ask YouTube itself whether this context is signed in, and as whom."""
    result = {"logged_in": False, "account": None, "source": None}

    try:
        logged_in = page.evaluate(
            "() => { try { return !!(window.ytcfg && ytcfg.get"
            " && ytcfg.get('LOGGED_IN')); } catch (e) { return null; } }"
        )
        if logged_in is True:
            result["logged_in"] = True
            result["source"] = "ytcfg.LOGGED_IN"
        elif logged_in is False:
            result["source"] = "ytcfg.LOGGED_IN"
    except Exception as e:
        logger.debug("ytcfg probe failed: %s" % e)

    # Account label is a nicety - never let it decide logged_in.
    try:
        label = page.evaluate(
            "() => { const b = document.querySelector('#avatar-btn, button#avatar-btn,"
            " ytd-topbar-menu-button-renderer button');"
            " return b ? (b.getAttribute('aria-label') || null) : null; }"
        )
        if label:
            result["account"] = label.strip()
    except Exception:
        pass

    if not result["logged_in"] and result["source"] is None:
        # ytcfg unavailable (consent interstitial, slow render): fall back to DOM.
        try:
            avatar = page.locator("#avatar-btn, button#avatar-btn, yt-img-shadow#avatar img").first
            if avatar.is_visible(timeout=4000):
                result["logged_in"] = True
                result["source"] = "avatar-dom"
        except Exception:
            pass

    return result


def verify_with_retry(page, logger, attempts: int = 3, settle_s: float = 3.0) -> dict:
    """verify_live, but reload between attempts.

    Cookies injected into a fresh profile often miss the first paint: YouTube
    renders the anonymous page, so ytcfg.LOGGED_IN comes back false even though
    the jar is now correct. A reload settles it.
    """
    state = {"logged_in": False, "account": None, "source": None}
    for attempt in range(1, attempts + 1):
        time.sleep(settle_s)
        state = verify_live(page, logger)
        if state["logged_in"]:
            if attempt > 1:
                logger.debug("Signed-in confirmed on attempt %d" % attempt)
            return state
        if attempt < attempts:
            logger.debug("Signed-out on attempt %d - reloading" % attempt)
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.debug("reload failed: %s" % e)
    return state


def check_live(logger, headless: bool = False) -> dict:
    """Open the authenticated context and report what YouTube says."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context, close = open_context(pw, logger, headless=headless)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(YOUTUBE, wait_until="domcontentloaded", timeout=30000)
            state = verify_with_retry(page, logger, attempts=2)
            if state["logged_in"]:
                logger.info("Signed IN%s (via %s)"
                            % (" - " + state["account"] if state["account"] else "",
                               state["source"]))
                # A successful check is also the cheapest chance to refresh.
                export_state(context, logger, verified=True)
            else:
                logger.error("Signed OUT (via %s) - run: measure_feed.py auth --login"
                             % state["source"])
            return state
        finally:
            close()


# ---------------------------------------------------------------------------
# Export - keep auth.json in sync with the live session
# ---------------------------------------------------------------------------

def export_state(context, logger, path: Path = None, verified: bool = False) -> bool:
    """Write the live context's cookies back to auth.json, atomically.

    This is the step whose absence let auth.json decay. Called at the end of
    every phase so rotating cookies stay current and the Electron app's
    auth.json keeps working.

    `verified` must be True: the caller has to have confirmed a signed-in
    session in THIS context. A revoked session still carries cookies named SID,
    __Secure-1PSID and friends, so the name check below cannot tell a live
    session from a dead one - without this gate an aborted signed-out run would
    overwrite a good snapshot with a dead one.
    """
    if not verified:
        logger.debug("Skipping auth.json export - sign-in was not verified")
        return False
    try:
        state = context.storage_state()
    except Exception as e:
        logger.warning("Could not read storage_state (%s) - auth.json left as is" % e)
        return False

    cookies = state.get("cookies") or []
    names = {c.get("name") for c in cookies}
    if not (names & CRITICAL_COOKIES):
        logger.warning("Live context has no session cookies - refusing to overwrite "
                       "auth.json with a signed-out state")
        return False

    try:
        # Keep writing to whichever store is already in use: a run must never
        # silently decrypt an encrypted session back onto disk.
        backend = "none"
        if session_store.enc_path(DATA_DIR).exists():
            backend = (session_store.status(DATA_DIR).get("backend")
                       or session_store.default_backend())
        written = session_store.save(state, DATA_DIR, backend)
        logger.info("Refreshed %s (%d cookies, %s) at %s"
                    % (written.name, len(cookies),
                       "encrypted" if backend != "none" else "plaintext",
                       datetime.now().strftime("%H:%M:%S")))
        return True
    except Exception as e:
        logger.warning("Failed to write the session: %s" % e)
        return False


# ---------------------------------------------------------------------------
# End-to-end self test
# ---------------------------------------------------------------------------

def selftest(logger, headless: bool = False) -> dict:
    """Walk the whole login chain and report each step.

    Offline steps run always. The live steps need a working session, so this
    doubles as the check to run straight after signing in.
    """
    steps = []

    def record(name, ok, detail=""):
        steps.append({"step": name, "ok": ok, "detail": detail})
        logger.info("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                                     "  -- " + detail if detail else ""))
        return ok

    logger.info("=" * 64)
    logger.info("  AUTH SELF TEST  data dir: %s" % DATA_DIR)
    logger.info("=" * 64)

    st = session_store.status(DATA_DIR)
    storage = ("encrypted" if st["encrypted"]
               else "plaintext" if st["plaintext"] else "none")
    record("a session is stored", st["encrypted"] or st["plaintext"], storage)
    record("storage is encrypted", st["encrypted"],
           "plaintext - run: auth --encrypt" if not st["encrypted"]
           else str(st["backend"]))

    try:
        state = session_store.load(DATA_DIR) or {}
        readable = bool(state.get("cookies"))
    except SessionStoreError as e:
        state, readable = {}, False
        record("session decrypts", False, str(e))
    if state or readable:
        record("session decrypts", readable, "%d cookies" % len(state.get("cookies") or []))

    info = inspect_auth_file()
    record("cookie health", info["usable"],
           "; ".join(info["problems"]) if info["problems"] else "no missing or expired session cookies")

    if st["encrypted"] and st["plaintext"]:
        record("no plaintext copy left behind", False,
               "auth.json still grants account access")
    else:
        record("no plaintext copy left behind", not st["plaintext"] or not st["encrypted"],
               "plaintext only" if st["plaintext"] and not st["encrypted"] else "")

    if not readable:
        logger.error("  Stopping: no readable session, so the live steps cannot run.")
        return {"steps": steps, "live": False,
                "ok": all(s["ok"] for s in steps)}

    # ---- live steps ----
    from playwright.sync_api import sync_playwright
    logged_in = False
    refreshed = False
    before = [c.get("value") for c in state.get("cookies") or []
              if c.get("name") in ("__Secure-1PSIDRTS", "SIDCC", "__Secure-1PSIDCC")]

    with sync_playwright() as pw:
        context, close = open_context(pw, logger, headless=headless)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(YOUTUBE, wait_until="domcontentloaded", timeout=30000)
            live = verify_with_retry(page, logger, attempts=2)
            logged_in = record(
                "YouTube says signed in", live["logged_in"],
                (live["account"] or "") if live["logged_in"]
                else "signed out (probe: %s) - run: auth --login" % live["source"])
            if logged_in:
                refreshed = record("refreshed session written back",
                                   export_state(context, logger, verified=True))
        finally:
            close()

    if refreshed:
        after_state = session_store.load(DATA_DIR) or {}
        after = [c.get("value") for c in after_state.get("cookies") or []
                 if c.get("name") in ("__Secure-1PSIDRTS", "SIDCC", "__Secure-1PSIDCC")]
        record("rotating cookies actually changed", bool(after) and after != before,
               "this is what stops the session decaying")
        record("stored session still decrypts after the run",
               bool((after_state.get("cookies") or [])))

    ok = all(s["ok"] for s in steps)
    logger.info("-" * 64)
    logger.info("  %d of %d steps passed" % (sum(1 for s in steps if s["ok"]), len(steps)))
    return {"steps": steps, "live": True, "ok": ok}


# ---------------------------------------------------------------------------
# Interactive login
# ---------------------------------------------------------------------------

def login(logger, headless: bool = False, timeout_s: int = 300) -> bool:
    """Log in by hand once, into the persistent profile.

    Waits for YouTube to report a signed-in session rather than for a DOM id,
    then exports auth.json for the rest of the project.
    """
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        context = _launch_persistent(pw, logger, headless=headless)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(YOUTUBE, wait_until="domcontentloaded", timeout=30000)

            print("\n" + "=" * 64)
            print("  Sign into YouTube in the Chrome window.")
            print("  Take your time - finish any 2FA / device verification.")
            print("  Waiting up to %d minutes; detection is automatic." % (timeout_s // 60))
            print("=" * 64)
            sys.stdout.flush()

            deadline = time.time() + timeout_s
            state = {"logged_in": False, "account": None, "source": None}
            while time.time() < deadline:
                time.sleep(3.0)
                try:
                    state = verify_live(page, logger)
                except Exception:
                    continue
                if state["logged_in"]:
                    break

            if not state["logged_in"]:
                logger.error("Timed out waiting for sign-in.")
                return False

            logger.info("Signed in%s. Profile saved at %s"
                        % (" as " + state["account"] if state["account"] else "",
                           PROFILE_DIR))
            time.sleep(2.0)
            export_state(context, logger, verified=True)
            return True
        finally:
            try:
                context.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI - usable standalone, and wired into measure_feed.py auth
# ---------------------------------------------------------------------------

def _cli_logger():
    import logging
    logger = logging.getLogger("yt_auth")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                          datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(ch)
    return logger


def main():
    import argparse

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Desktop YouTube auth / cookie flow")
    ap.add_argument("--check", action="store_true",
                    help="offline cookie health (add --live to confirm with YouTube)")
    ap.add_argument("--live", action="store_true", help="open Chrome and ask YouTube")
    ap.add_argument("--login", action="store_true", help="interactive login into the profile")
    ap.add_argument("--migrate", action="store_true", help="seed the profile from auth.json")
    ap.add_argument("--export", action="store_true", help="refresh auth.json from the profile")
    args = ap.parse_args()

    logger = _cli_logger()

    if args.login:
        sys.exit(0 if login(logger) else 1)
    if args.migrate:
        sys.exit(0 if seed_profile_from_auth(logger) else 1)
    if args.export or args.live:
        state = check_live(logger)
        sys.exit(0 if state["logged_in"] else 1)

    info = inspect_auth_file()
    print()
    print(format_inspection(info))
    print("  profile:    %s" % (str(PROFILE_DIR) if profile_is_populated()
                                else "(none - snapshot auth only)"))
    print()
    sys.exit(0 if info["usable"] else 1)


if __name__ == "__main__":
    main()
