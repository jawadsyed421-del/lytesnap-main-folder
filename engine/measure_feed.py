"""
LYTESNAP Desktop Lift Test
==========================
Measures whether a watch-only YouTube session moves the Home feed toward a
topic, using a fixed recipe so runs are comparable:

  1. auth      - persistent Chrome profile, auth.json kept in sync (yt_auth.py)
  2. score     - 12 Home feed titles, classified, repeated 3x   (phase=before)
  3. watch     - watch only (no likes/subs/comments/not-interested), 30 min
  4. cooldown  - browser closed, wait 10 min
  5. score     - 12 titles again, 3x                            (phase=after)
  6. report    - lift = after mean % - before mean %

The classifier is imported from score_feed.py, so the prompt is identical to
the fixed measurement function and is never re-worded here.

Usage:
    python engine/measure_feed.py auth --check      # offline cookie health
    python engine/measure_feed.py auth --live       # ask YouTube, refresh cookies
    python engine/measure_feed.py auth --login      # sign in (persistent profile)
    python engine/measure_feed.py auth --migrate    # auth.json -> profile, no re-2FA
    python engine/measure_feed.py run --topic "Marine Biology"

    # individual phases (pass the same --run-dir to tie them together)
    python engine/measure_feed.py score    --topic "..." --phase before --run-dir <dir>
    python engine/measure_feed.py watch    --topic "..." --minutes 30   --run-dir <dir>
    python engine/measure_feed.py cooldown --minutes 10                 --run-dir <dir>
    python engine/measure_feed.py score    --topic "..." --phase after  --run-dir <dir>
    python engine/measure_feed.py report                                --run-dir <dir>

    # phone feed: the mobile app cannot be scraped, so capture titles by hand
    python engine/measure_feed.py mobile --topic "..." --phase before \
        --titles-file phone_before.txt --run-dir <dir>
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ENGINE_DIR.parent
sys.path.insert(0, str(ENGINE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
except Exception:
    pass

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# The fixed measurement function - classifier prompt comes from here, unchanged.
from score_feed import classify, CLASSIFIER

# Desktop auth / cookie flow: persistent Chrome profile as source of truth,
# auth.json kept in sync for the rest of the project.
import yt_auth
import session_store

# Browsing helpers shared with the reshaper. This is the watch-only subset:
# nothing imported here likes, subscribes, comments, or marks "not interested".
from youtube_reshaper import (
    dismiss_popups,
    skip_ads,
    ensure_autoplay_off,
    get_video_duration,
    human_sleep,
    human_scroll,
    search_topic,
    jitter,
)

# Every per-account path hangs off DATA_DIR; set_data_dir() moves them together.
DATA_DIR = PROJECT_DIR
AUTH_FILE = DATA_DIR / "auth.json"
CONFIG_FILE = DATA_DIR / "config.json"


def set_data_dir(path) -> Path:
    """Relocate this run's auth, config and metrics, and yt_auth's stores with them."""
    global DATA_DIR, AUTH_FILE, CONFIG_FILE
    DATA_DIR = Path(path).resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_FILE = DATA_DIR / "auth.json"
    CONFIG_FILE = DATA_DIR / "config.json"
    yt_auth.set_data_dir(DATA_DIR)
    return DATA_DIR
VIEWPORT = {"width": 1280, "height": 800}

DEFAULT_N_TITLES = 12
DEFAULT_REPS = 3
DEFAULT_WATCH_MINUTES = 30
DEFAULT_COOLDOWN_MINUTES = 10
REP_GAP_SECONDS = 20          # pause between the 3 scoring reps
WATCH_PCT = (0.85, 0.95)      # matches config.json defaults
WATCH_CAP_SECONDS = 600


# ---------------------------------------------------------------------------
# Logging / run dir
# ---------------------------------------------------------------------------

def get_logger(run_dir, verbose: bool = True) -> logging.Logger:
    logger = logging.getLogger("lift")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)
        if run_dir:
            run_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(run_dir / "lift_test.log", encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
    return logger


def new_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    d = DATA_DIR / "metrics" / ("desktop_test_" + stamp)
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(run_dir: Path) -> dict:
    p = run_dir / "state.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_state(run_dir: Path, state: dict) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    (run_dir / "state.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_narrow_topics(topic: str, logger) -> list:
    """Search queries for the watch phase.

    config.json may hold narrow topics for several unrelated campaigns, so keep
    only the ones the classifier calls on-topic for this test. Falls back to the
    topic itself.
    """
    # Auth is per account; config is shared settings. A per-account data dir
    # usually has no config.json of its own, so fall back to the project's.
    candidates = []
    config_path = CONFIG_FILE if CONFIG_FILE.exists() else PROJECT_DIR / "config.json"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        raw = cfg.get("narrow_topics") or []
        candidates = [raw] if isinstance(raw, str) else list(raw)
        if config_path != CONFIG_FILE:
            logger.debug("Using shared config at %s" % config_path)
    except Exception as e:
        logger.warning("Could not read narrow_topics from %s: %s" % (config_path.name, e))

    if not candidates:
        return [topic]
    try:
        flags = classify(candidates, topic, logger)
        kept = [c for c, f in zip(candidates, flags) if f]
    except Exception as e:
        logger.warning("Query filtering failed (%s) - using topic only" % e)
        kept = []
    if not kept:
        logger.info("  No on-topic narrow_topics in config - searching '%s'" % topic)
        return [topic]
    logger.info("  Search queries (%d of %d config narrow_topics on-topic): %s"
                % (len(kept), len(candidates), kept))
    return kept


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

def launch_context(pw, logger):
    """Authenticated Chrome. Returns (context, close_fn).

    Auth comes from yt_auth: the persistent profile when there is one, else the
    auth.json snapshot. Cookie health is checked before the browser opens, so a
    dead session fails here instead of silently scoring a signed-out feed.
    """
    return yt_auth.open_context(pw, logger)


def open_home(context, logger):
    """Fresh tab on the Home feed, popups dismissed.

    A persistent context starts with one blank page already open; use it rather
    than leaving an idle tab behind on every rep.
    """
    page = context.pages[0] if context.pages else context.new_page()
    for attempt in range(3):
        try:
            page.goto("https://www.youtube.com",
                      wait_until="domcontentloaded", timeout=30000)
            break
        except Exception as e:
            if attempt == 2:
                raise
            logger.warning("Home navigation failed (%s) - retry %d/3" % (e, attempt + 2))
            time.sleep(3.0)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    human_sleep(1.5, 2.5)
    dismiss_popups(page, logger)
    return page


def assert_signed_in(page, logger) -> bool:
    """Hard gate: a signed-out feed is not the account's feed, so the run aborts.

    Previously this warned and continued when the avatar selector missed, which
    could pass off an anonymous feed as a measurement.
    """
    state = yt_auth.verify_live(page, logger)
    if state["logged_in"]:
        logger.info("Signed in%s (via %s)"
                    % (" - " + state["account"] if state["account"] else "",
                       state["source"]))
        return True
    logger.error("YouTube reports SIGNED OUT (probe: %s). The feed would be "
                 "anonymous, so this measurement would be void." % state["source"])
    logger.error("Fix with: python engine/measure_feed.py auth --login")
    return False


# ---------------------------------------------------------------------------
# Title extraction - Home feed only, Shorts excluded
# ---------------------------------------------------------------------------

def collect_home_titles(page, n: int, logger) -> list:
    """First n unique non-Shorts Home feed cards, in feed order."""
    for attempt in range(3):
        try:
            page.wait_for_selector("ytd-rich-item-renderer", timeout=20000)
            break
        except PWTimeoutError:
            if attempt == 2:
                logger.error("Home feed never rendered - no titles.")
                return []
            logger.warning("Home feed slow (attempt %d/3) - reloading" % (attempt + 1))
            try:
                page.reload(wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            time.sleep(3.0)

    human_sleep(1.5, 2.5)
    cards = []
    seen = set()

    for _ in range(5):
        for link in page.locator("ytd-rich-item-renderer h3 a").all():
            try:
                title = (link.text_content(timeout=2000) or "").strip()
                href = link.get_attribute("href") or ""
                if not title or not href or "/shorts/" in href or title in seen:
                    continue
                seen.add(title)
                cards.append({"title": title, "url": href})
            except Exception:
                pass
        if len(cards) >= n:
            break
        human_scroll(page, 500, steps=6)
        human_sleep(0.6, 1.2)

    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass

    if len(cards) < n:
        logger.warning("Only %d non-Shorts cards available (wanted %d) - "
                       "scoring what loaded." % (len(cards), n))
    return cards[:n]


# ---------------------------------------------------------------------------
# Phase: score (n titles x reps)
# ---------------------------------------------------------------------------

def score_phase(topic: str, phase: str, run_dir: Path, n: int, reps: int, logger) -> dict:
    logger.info("=" * 64)
    logger.info("  SCORE [%s]  topic='%s'  n=%d  reps=%d  classifier=%s"
                % (phase, topic, n, reps, CLASSIFIER))
    logger.info("=" * 64)

    rep_results = []
    with sync_playwright() as pw:
        context, close_browser = launch_context(pw, logger)
        signed_in = False
        try:
            for rep in range(1, reps + 1):
                if rep > 1:
                    logger.info("  Waiting %ds before rep %d ..." % (REP_GAP_SECONDS, rep))
                    time.sleep(REP_GAP_SECONDS)

                page = open_home(context, logger)
                if rep == 1:
                    if not assert_signed_in(page, logger):
                        raise SystemExit("Aborting: not signed in.")
                    signed_in = True

                titles = [c["title"] for c in collect_home_titles(page, n, logger)]
                page.close()

                if not titles:
                    rep_results.append({"rep": rep, "total": 0, "matches": 0,
                                        "score": None, "titles": [], "flags": []})
                    logger.error("  rep %d: no titles - recorded as missing" % rep)
                    continue

                flags = [bool(f) for f in classify(titles, topic, logger)]
                matches = sum(flags)
                score = matches / len(titles)
                rep_results.append({
                    "rep": rep,
                    "total": len(titles),
                    "matches": matches,
                    "score": round(score, 4),
                    "titles": titles,
                    "flags": flags,
                })
                logger.info("  rep %d: %d/%d = %.1f%%"
                            % (rep, matches, len(titles), score * 100))
                for i, (t, f) in enumerate(zip(titles, flags), 1):
                    logger.info("      %s %2d. %s" % ("[YES]" if f else "[ - ]", i, t))
        finally:
            # Refresh auth.json from the live session before tearing it down -
            # this is what keeps rotating cookies from going stale. Only when the
            # session was actually signed in, never on a signed-out abort.
            yt_auth.export_state(context, logger, verified=signed_in)
            close_browser()

    valid = [r["score"] for r in rep_results if r["score"] is not None]
    mean = sum(valid) / len(valid) if valid else None
    result = {
        "phase": phase,
        "topic": topic,
        "classifier": CLASSIFIER,
        "n_requested": n,
        "reps": reps,
        "rep_results": rep_results,
        "mean_score": round(mean, 4) if mean is not None else None,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / ("score_" + phase + ".json")).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if mean is not None:
        logger.info("  %s mean = %.1f%%  (reps: %s)"
                    % (phase.upper(), mean * 100,
                       ", ".join("%.1f%%" % (s * 100) for s in valid)))
    else:
        logger.error("  %s mean = n/a (all reps failed)" % phase.upper())
    return result


# ---------------------------------------------------------------------------
# Phase: watch (watch only - no likes, subs, comments, not-interested)
# ---------------------------------------------------------------------------

def watch_video(page, title: str, deadline: float, logger) -> float:
    """Watch the currently loaded video. Returns seconds actually watched."""
    watched = 0.0
    try:
        human_sleep(1.5, 3.0)
        dismiss_popups(page, logger)
        skip_ads(page, logger)
        ensure_autoplay_off(page, logger)   # only deliberate picks count

        try:
            page.locator("video").first.wait_for(state="attached", timeout=10000)
            playing = page.evaluate(
                "() => { const v = document.querySelector('video');"
                " return v && !v.paused && !v.ended; }"
            )
            if not playing:
                page.locator("#movie_player, .html5-video-container").first.click()
                human_sleep(0.8, 1.5)
                skip_ads(page, logger)
        except Exception as e:
            logger.debug("  player start skipped: %s" % e)

        human_sleep(1.0, 2.0)
        duration = get_video_duration(page, logger)
        if duration:
            pct = jitter(*WATCH_PCT)
            target = min(duration * pct, WATCH_CAP_SECONDS)
            logger.info("  watching %.0fs of %.0fs (%.0f%%, cap %ds)"
                        % (target, duration, pct * 100, WATCH_CAP_SECONDS))
        else:
            target = jitter(90, 150)
            logger.info("  duration unknown - watching %.0fs" % target)

        target = min(target, max(0.0, deadline - time.time()))
        while watched < target:
            if time.time() >= deadline:
                logger.info("  session deadline - stopping watch early")
                break
            chunk = min(jitter(8, 20), target - watched)
            time.sleep(chunk)
            watched += chunk
            skip_ads(page, logger)
        logger.info("  watched %.0fs of '%s'" % (watched, title))
    except Exception as e:
        logger.error("  watch error on '%s': %s" % (title, e))
    return watched


def _open_card(page, card, logger) -> bool:
    """Click the card, falling back to direct navigation."""
    try:
        link = page.locator('a[href="%s"]' % card["url"]).first
        try:
            link.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        human_sleep(0.4, 0.9)
        link.click(timeout=10000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        return True
    except Exception as e:
        logger.warning("  click failed (%s) - navigating directly" % e)
        try:
            page.goto("https://www.youtube.com" + card["url"],
                      wait_until="domcontentloaded", timeout=25000)
            return True
        except Exception as e2:
            logger.error("  could not open '%s': %s" % (card["title"], e2))
            return False


def watch_phase(topic: str, run_dir: Path, minutes: int, logger) -> dict:
    logger.info("=" * 64)
    logger.info("  WATCH-ONLY SESSION  topic='%s'  %d min" % (topic, minutes))
    logger.info("  No likes, no subscribes, no comments, no not-interested.")
    logger.info("=" * 64)

    narrow_topics = load_narrow_topics(topic, logger)
    random.shuffle(narrow_topics)
    deadline = time.time() + minutes * 60
    watched_log = []
    seen_titles = set()
    topic_idx = 0

    with sync_playwright() as pw:
        context, close_browser = launch_context(pw, logger)
        page = None
        signed_in = False
        try:
            page = open_home(context, logger)
            if not assert_signed_in(page, logger):
                raise SystemExit("Aborting: not signed in.")
            signed_in = True

            while time.time() < deadline:
                logger.info("--- %.1f min left ---" % ((deadline - time.time()) / 60))

                # 1. On-topic picks from Home first.
                try:
                    page.goto("https://www.youtube.com",
                              wait_until="domcontentloaded", timeout=30000)
                    human_sleep(1.5, 3.0)
                    dismiss_popups(page, logger)
                except Exception as e:
                    logger.warning("  home nav failed: %s" % e)

                cards = [c for c in collect_home_titles(page, 15, logger)
                         if c["title"] not in seen_titles]
                picks = []
                if cards:
                    flags = classify([c["title"] for c in cards], topic, logger)
                    picks = [c for c, f in zip(cards, flags) if f]
                    logger.info("  Home: %d/%d on-topic" % (len(picks), len(cards)))

                if picks:
                    for card in picks[:2]:
                        if time.time() >= deadline:
                            break
                        seen_titles.add(card["title"])
                        if not _open_card(page, card, logger):
                            continue
                        secs = watch_video(page, card["title"], deadline, logger)
                        watched_log.append({"source": "home", "title": card["title"],
                                            "url": card["url"], "seconds": round(secs, 1)})
                    continue

                # 2. Nothing on-topic on Home - search instead.
                query = narrow_topics[topic_idx % len(narrow_topics)]
                topic_idx += 1
                logger.info("  No on-topic Home cards - searching '%s'" % query)
                search_topic(page, query, logger)
                try:
                    page.wait_for_selector("ytd-video-renderer", timeout=15000)
                except Exception:
                    logger.warning("  no search results rendered")
                    continue

                results = []
                for item in page.locator("ytd-video-renderer").all()[:10]:
                    try:
                        a = item.locator("a#video-title").first
                        t = (a.text_content(timeout=2000) or "").strip()
                        h = a.get_attribute("href") or ""
                        if t and h and "/shorts/" not in h and t not in seen_titles:
                            results.append({"title": t, "url": h})
                    except Exception:
                        pass
                if not results:
                    logger.warning("  no usable search results")
                    continue

                flags = classify([r["title"] for r in results], topic, logger)
                on_topic = [r for r, f in zip(results, flags) if f] or results[:1]
                for card in on_topic[:2]:
                    if time.time() >= deadline:
                        break
                    seen_titles.add(card["title"])
                    if not _open_card(page, card, logger):
                        continue
                    secs = watch_video(page, card["title"], deadline, logger)
                    watched_log.append({"source": "search:" + query, "title": card["title"],
                                        "url": card["url"], "seconds": round(secs, 1)})
        finally:
            # Step 4 of the recipe starts with YouTube closed.
            yt_auth.export_state(context, logger, verified=signed_in)
            try:
                if page:
                    page.close()
            except Exception:
                pass
            close_browser()
            logger.info("  Browser closed.")

    total = sum(w["seconds"] for w in watched_log)
    result = {
        "topic": topic,
        "minutes_requested": minutes,
        "videos_watched": len(watched_log),
        "total_watch_seconds": round(total, 1),
        "interactions": "watch only (no like / subscribe / comment / not-interested)",
        "watched": watched_log,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "watch_session.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("  Watched %d videos, %.1f min of playback."
                % (len(watched_log), total / 60))
    return result


# ---------------------------------------------------------------------------
# Phase: cooldown
# ---------------------------------------------------------------------------

def cooldown_phase(minutes: int, logger) -> None:
    logger.info("  COOLDOWN - YouTube closed, waiting %d min ..." % minutes)
    end = time.time() + minutes * 60
    while time.time() < end:
        time.sleep(min(60.0, max(1.0, end - time.time())))
        left = max(0.0, end - time.time())
        if left > 0:
            logger.info("    %.0f min left" % (left / 60))
    logger.info("  Cooldown done.")


# ---------------------------------------------------------------------------
# Phase: mobile (manual title capture - the phone app cannot be scraped)
# ---------------------------------------------------------------------------

def mobile_phase(topic: str, phase: str, titles_file: Path, run_dir: Path,
                 n: int, logger) -> dict:
    lines = [l.strip() for l in titles_file.read_text(encoding="utf-8").splitlines()]
    titles = [l for l in lines if l and not l.startswith("#")][:n]
    if not titles:
        raise SystemExit("No titles found in " + str(titles_file))
    logger.info("  MOBILE [%s] - %d titles from %s"
                % (phase, len(titles), titles_file.name))

    flags = [bool(f) for f in classify(titles, topic, logger)]
    matches = sum(flags)
    score = matches / len(titles)
    result = {
        "phase": "mobile_" + phase,
        "topic": topic,
        "classifier": CLASSIFIER,
        "source": "manual capture from YouTube mobile app",
        "total": len(titles),
        "matches": matches,
        "score": round(score, 4),
        "titles": titles,
        "flags": flags,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / ("mobile_" + phase + ".json")).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("  mobile %s: %d/%d = %.1f%%"
                % (phase, matches, len(titles), score * 100))
    return result


# ---------------------------------------------------------------------------
# Phase: report
# ---------------------------------------------------------------------------

def _pct(x):
    return "n/a" if x is None else "%.1f%%" % (x * 100)


def report_phase(run_dir: Path, logger) -> str:
    def read(name):
        p = run_dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    before = read("score_before.json")
    after = read("score_after.json")
    watch = read("watch_session.json")
    mob_b = read("mobile_before.json")
    mob_a = read("mobile_after.json")

    topic = (before or after or watch or mob_b or mob_a or {}).get("topic", "?")
    lines = ["=" * 64,
             "  LYTESNAP DESKTOP LIFT TEST",
             "=" * 64,
             "  Run dir:    " + run_dir.name,
             "  Topic:      " + str(topic),
             "  Classifier: " + str((before or after or {}).get("classifier", CLASSIFIER)),
             ""]

    for label, data in (("BEFORE", before), ("AFTER", after)):
        if not data:
            lines.append("  %s: missing" % label)
            continue
        reps = ", ".join(
            "rep%d %d/%d (%s)" % (r["rep"], r["matches"], r["total"], _pct(r["score"]))
            for r in data["rep_results"]
        )
        lines.append("  %s mean %s  [%s]" % (label, _pct(data["mean_score"]), reps))
    lines.append("")

    if watch:
        lines.append("  Watch session: %d videos, %.1f min playback"
                     % (watch["videos_watched"], watch["total_watch_seconds"] / 60))
        lines.append("  Interactions:  " + watch["interactions"])
        lines.append("")

    if before and after and before["mean_score"] is not None and after["mean_score"] is not None:
        lift = after["mean_score"] - before["mean_score"]
        lines.append("  DESKTOP LIFT = %s - %s = %+.1f points"
                     % (_pct(after["mean_score"]), _pct(before["mean_score"]), lift * 100))
    else:
        lines.append("  DESKTOP LIFT = n/a (need both before and after scores)")

    if mob_b or mob_a:
        lines.append("")
        lines.append("  MOBILE before %s   after %s"
                     % (_pct(mob_b["score"]) if mob_b else "missing",
                        _pct(mob_a["score"]) if mob_a else "missing"))
        if mob_b and mob_a:
            lines.append("  MOBILE LIFT  = %+.1f points (desktop watching -> phone feed)"
                         % ((mob_a["score"] - mob_b["score"]) * 100))
    lines.append("=" * 64)

    text = "\n".join(lines)
    (run_dir / "report.txt").write_text(text + "\n", encoding="utf-8")
    print("\n" + text + "\n")
    return text


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

def login_phase(logger) -> None:
    """Manual one-time login into the persistent Chrome profile."""
    ok = yt_auth.login(logger)
    if not ok:
        raise SystemExit("Login did not complete.")


def auth_phase(logger, check: bool, live: bool, do_login: bool,
               migrate: bool, export: bool, encrypt: bool = False,
               decrypt: bool = False, backend: str = None,
               keep_plaintext: bool = False, selftest: bool = False) -> None:
    """Inspect or repair the desktop auth/cookie flow."""
    if selftest:
        result = yt_auth.selftest(logger)
        raise SystemExit(0 if result["ok"] else 1)

    if encrypt:
        try:
            r = session_store.migrate(yt_auth.DATA_DIR, backend, keep_plaintext)
        except session_store.SessionStoreError as e:
            logger.error(str(e))
            raise SystemExit(1)
        logger.info("Encrypted %d cookies with %s -> %s"
                    % (r["cookies"], r["backend"], r["written"]))
        if r["plaintext_removed"]:
            logger.info("Plaintext auth.json removed (a .pre-encrypt.bak copy "
                        "remains; delete it once you have verified a run)")
        else:
            logger.warning("auth.json kept and still grants account access")
        logger.warning("score_feed.py and the Electron app read auth.json "
                       "directly and will not see the encrypted session")
        raise SystemExit(0)

    if decrypt:
        try:
            path = session_store.decrypt_to_plaintext(yt_auth.DATA_DIR)
        except session_store.SessionStoreError as e:
            logger.error(str(e))
            raise SystemExit(1)
        logger.warning("Wrote plaintext %s - it grants account access to "
                       "anyone who can read it" % path)
        raise SystemExit(0)

    if do_login:
        raise SystemExit(0 if yt_auth.login(logger) else 1)
    if migrate:
        raise SystemExit(0 if yt_auth.seed_profile_from_auth(logger) else 1)
    if live or export:
        state = yt_auth.check_live(logger)
        raise SystemExit(0 if state["logged_in"] else 1)

    info = yt_auth.inspect_auth_file()
    print()
    print(yt_auth.format_inspection(info))
    print(session_store.format_status(session_store.status(yt_auth.DATA_DIR)))
    print("  profile:    %s" % (str(yt_auth.PROFILE_DIR)
                                if yt_auth.profile_is_populated()
                                else "(none - snapshot auth only)"))
    print()
    raise SystemExit(0 if info["usable"] else 1)


# ---------------------------------------------------------------------------
# run - full recipe
# ---------------------------------------------------------------------------

def run_all(topic: str, run_dir: Path, n: int, reps: int,
            minutes: int, cooldown: int, logger) -> None:
    state = load_state(run_dir)
    state.setdefault("topic", topic)
    state.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    state["recipe"] = {"n_titles": n, "reps": reps,
                       "watch_minutes": minutes, "cooldown_minutes": cooldown}

    steps = [
        ("before", lambda: score_phase(topic, "before", run_dir, n, reps, logger)),
        ("watch", lambda: watch_phase(topic, run_dir, minutes, logger)),
        ("cooldown", lambda: cooldown_phase(cooldown, logger)),
        ("after", lambda: score_phase(topic, "after", run_dir, n, reps, logger)),
    ]
    for key, fn in steps:
        if state.get(key) == "done":
            logger.info("  %s: already done - skipping" % key)
            continue
        fn()
        state[key] = "done"
        save_state(run_dir, state)

    report_phase(run_dir, logger)
    logger.info("  Artifacts in: %s" % run_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="LyteSnap desktop feed-lift test")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, needs_topic=True):
        if needs_topic:
            p.add_argument("--topic", required=True)
        p.add_argument("--run-dir", default=None,
                       help="Experiment folder (default: new metrics/desktop_test_<ts>)")
        p.add_argument("--data-dir", default=None,
                       help="Per-account dir holding auth.json, chrome_profile/ and "
                            "metrics/ (default: the project dir)")
        p.add_argument("--n", type=int, default=DEFAULT_N_TITLES)
        p.add_argument("--reps", type=int, default=DEFAULT_REPS)

    p_login = sub.add_parser("login",
                             help="one-time manual YouTube login (alias of: auth --login)")
    p_login.add_argument("--data-dir", default=None,
                         help="Per-account dir to write auth.json / chrome_profile into")

    p_auth = sub.add_parser("auth", help="inspect or repair the auth / cookie flow")
    p_auth.add_argument("--check", action="store_true",
                        help="offline cookie health (default when no flag given)")
    p_auth.add_argument("--live", action="store_true",
                        help="open Chrome and ask YouTube whether we are signed in")
    p_auth.add_argument("--login", action="store_true",
                        help="interactive login into the persistent profile")
    p_auth.add_argument("--migrate", action="store_true",
                        help="seed the persistent profile from an existing auth.json")
    p_auth.add_argument("--export", action="store_true",
                        help="refresh auth.json from the live session")
    p_auth.add_argument("--data-dir", default=None,
                        help="Per-account dir holding the session and chrome_profile/")
    p_auth.add_argument("--encrypt", action="store_true",
                        help="encrypt a plaintext auth.json into session.enc")
    p_auth.add_argument("--decrypt", action="store_true",
                        help="write the session back out as plaintext auth.json")
    p_auth.add_argument("--backend", choices=session_store.BACKENDS, default=None,
                        help="encryption backend (default: dpapi on Windows, "
                             "aesgcm when a key is set)")
    p_auth.add_argument("--keep-plaintext", action="store_true",
                        help="with --encrypt, leave auth.json in place")
    p_auth.add_argument("--selftest", action="store_true",
                        help="walk the whole login chain and report each step")

    p_run = sub.add_parser("run", help="full recipe end to end")
    common(p_run)
    p_run.add_argument("--minutes", type=int, default=DEFAULT_WATCH_MINUTES)
    p_run.add_argument("--cooldown", type=int, default=DEFAULT_COOLDOWN_MINUTES)

    p_score = sub.add_parser("score", help="score the Home feed (n titles x reps)")
    common(p_score)
    p_score.add_argument("--phase", required=True, choices=["before", "after"])

    p_watch = sub.add_parser("watch", help="watch-only session")
    common(p_watch)
    p_watch.add_argument("--minutes", type=int, default=DEFAULT_WATCH_MINUTES)

    p_cool = sub.add_parser("cooldown", help="wait with YouTube closed")
    common(p_cool, needs_topic=False)
    p_cool.add_argument("--minutes", type=int, default=DEFAULT_COOLDOWN_MINUTES)

    p_mob = sub.add_parser("mobile", help="score phone-app titles from a text file")
    common(p_mob)
    p_mob.add_argument("--phase", required=True, choices=["before", "after"])
    p_mob.add_argument("--titles-file", required=True)

    p_rep = sub.add_parser("report", help="print/write the lift report")
    common(p_rep, needs_topic=False)

    args = ap.parse_args()

    # Must happen before any path is read: every store moves together.
    if getattr(args, "data_dir", None):
        set_data_dir(args.data_dir)

    if args.cmd == "login":
        login_phase(get_logger(None))
        return

    if args.cmd == "auth":
        auth_phase(get_logger(None), args.check, args.live,
                   args.login, args.migrate, args.export,
                   encrypt=args.encrypt, decrypt=args.decrypt,
                   backend=args.backend, keep_plaintext=args.keep_plaintext,
                   selftest=args.selftest)
        return

    run_dir = Path(args.run_dir).resolve() if args.run_dir else new_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = get_logger(run_dir)
    logger.info("Run dir: %s" % run_dir)

    if args.cmd == "run":
        run_all(args.topic, run_dir, args.n, args.reps,
                args.minutes, args.cooldown, logger)
    elif args.cmd == "score":
        score_phase(args.topic, args.phase, run_dir, args.n, args.reps, logger)
    elif args.cmd == "watch":
        watch_phase(args.topic, run_dir, args.minutes, logger)
    elif args.cmd == "cooldown":
        cooldown_phase(args.minutes, logger)
    elif args.cmd == "mobile":
        mobile_phase(args.topic, args.phase, Path(args.titles_file).resolve(),
                     run_dir, args.n, logger)
    elif args.cmd == "report":
        report_phase(run_dir, logger)


if __name__ == "__main__":
    main()
