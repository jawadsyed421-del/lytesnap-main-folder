"""
YouTube Feed Reshaper
Simulates realistic human browsing to shift YouTube's recommendation algorithm
toward a set of user-specified target topics.
"""

import json
import os
import random
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import time
import logging
from datetime import datetime
from pathlib import Path
from collections import Counter
from typing import Optional

import anthropic
from tqdm import tqdm
from playwright.sync_api import sync_playwright, Page, Locator, TimeoutError as PWTimeoutError


# ---------------------------------------------------------------------------
# Config & logging helpers
# ---------------------------------------------------------------------------

QUERY_SUFFIXES = [
    "", "explained", "for beginners", "amazing facts",
    "how it works", "101", "guide", "research", "facts",
]

def generate_subtopics(main_topic: str, n: int, logger: logging.Logger) -> list:
    """
    Use Claude to generate n specific, YouTube-searchable subtopics for main_topic.
    Falls back to query variations (main_topic + suffixes) if the API is unavailable.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Generate {n} specific, YouTube-searchable subtopics for the topic: '{main_topic}'.\n"
                        "Each subtopic should be a short search phrase (2-5 words) that returns "
                        "focused, educational YouTube videos ideally under 20 minutes long.\n"
                        "Avoid words like 'documentary' or 'full episode' — prefer specific questions, "
                        "facts, or concepts (e.g. 'how octopuses change color', 'coral reef food web').\n"
                        "Reply with ONLY a JSON array of strings, no explanation."
                    ),
                }],
            )
            raw = msg.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            subtopics = json.loads(raw.strip())
            logger.info(f"Generated subtopics for '{main_topic}': {subtopics}")
            return subtopics
        except Exception as e:
            logger.warning(f"Subtopic generation failed ({e}) — falling back to query variations.")

    # Fallback: build varied search queries from the main topic + suffixes
    suffixes = random.sample(QUERY_SUFFIXES, min(n, len(QUERY_SUFFIXES)))
    subtopics = [f"{main_topic} {s}".strip() for s in suffixes]
    logger.info(f"Using query variations as subtopics: {subtopics}")
    return subtopics


def load_config(path: str = "config.json") -> dict:
    with open(path, "r") as f:
        return json.load(f)


def setup_logging(log_file: str) -> logging.Logger:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("reshaper")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Human-like timing helpers
# ---------------------------------------------------------------------------

def jitter(lo: float, hi: float) -> float:
    """Return a random float in [lo, hi] with a slight gaussian nudge."""
    base = random.uniform(lo, hi)
    noise = random.gauss(0, (hi - lo) * 0.05)
    return max(lo * 0.8, min(hi * 1.2, base + noise))


def human_sleep(lo: float = 0.5, hi: float = 2.0) -> None:
    time.sleep(jitter(lo, hi))


def human_scroll(page: Page, distance: int = 600, steps: int = 8) -> None:
    """Scroll smoothly in small increments with random pauses."""
    per_step = distance // steps
    for _ in range(steps):
        page.mouse.wheel(0, per_step + random.randint(-30, 30))
        time.sleep(jitter(0.05, 0.18))


def human_type(locator: Locator, text: str) -> None:
    """Type each character with a random delay to mimic human typing."""
    locator.click()
    for char in text:
        locator.type(char, delay=random.randint(60, 180))
        if random.random() < 0.03:          # occasional brief pause mid-word
            time.sleep(jitter(0.2, 0.6))


# ---------------------------------------------------------------------------
# YouTube DOM selectors  (semantic / attribute-based to survive DOM changes)
# ---------------------------------------------------------------------------

SELECTORS = {
    # Search
    "search_input":     'input#search, input[name="search_query"]',

    # Feed video cards (homepage)
    "feed_video_title": (
        "ytd-rich-item-renderer #video-title, "
        "ytd-rich-grid-media #video-title"
    ),
    "feed_video_card":  "ytd-rich-item-renderer, ytd-rich-grid-media",

    # Search-result video cards
    "result_video_card":  "ytd-video-renderer",

    # Popups / overlays
    "dismiss_button": (
        'button[aria-label="Got it"], tp-yt-paper-button#dismiss, '
        'yt-button-renderer#dismiss-button button, '
        'button[aria-label="No thanks"], '
        'ytd-button-renderer[id="dismiss-button"] button'
    ),
    "skip_ad_button":  'button.ytp-ad-skip-button, .ytp-skip-ad-button',
    "consent_accept":  'button[aria-label*="Accept" i], button[aria-label*="agree" i]',
}


# ---------------------------------------------------------------------------
# Popup / ad helpers
# ---------------------------------------------------------------------------

def dismiss_popups(page: Page, logger: logging.Logger) -> None:
    """Silently close any consent dialogs or overlays that might be present."""
    for sel in [SELECTORS["consent_accept"], SELECTORS["dismiss_button"]]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click()
                logger.debug(f"Dismissed popup: {sel}")
                human_sleep(0.3, 0.8)
        except PWTimeoutError:
            pass
        except Exception as e:
            logger.debug(f"Popup check skipped ({sel}): {e}")


def skip_ads(page: Page, logger: logging.Logger) -> None:
    """Click 'Skip Ad' if it appears on a video."""
    for _ in range(3):
        try:
            btn = page.locator(SELECTORS["skip_ad_button"]).first
            if btn.is_visible(timeout=2000):
                btn.click()
                logger.info("Skipped ad.")
                human_sleep(0.5, 1.2)
                return
        except Exception:
            pass
        time.sleep(1)


def ensure_autoplay_off(page: Page, logger: logging.Logger) -> None:
    """Check if the autoplay toggle is on; if so, click it to disable it."""
    try:
        result = page.evaluate(
            "() => {"
            "  const btn = document.querySelector('.ytp-autonav-toggle-button');"
            "  if (!btn) return 'not_found';"
            "  if (btn.getAttribute('aria-checked') === 'true') { btn.click(); return 'clicked'; }"
            "  return 'already_off';"
            "}"
        )
        if result == 'clicked':
            human_sleep(0.3, 0.6)
            logger.info("Autoplay was ON — turned OFF.")
        elif result == 'already_off':
            logger.debug("Autoplay is already OFF.")
        else:
            logger.debug("Autoplay button not found.")
    except Exception as e:
        logger.debug(f"ensure_autoplay_off skipped: {e}")


# ---------------------------------------------------------------------------
# Core actions
# ---------------------------------------------------------------------------

def snapshot_feed(page: Page, logger: logging.Logger) -> list:
    """Extract unique video titles (+ URLs) from the homepage feed."""
    logger.info("Snapshotting homepage feed ...")
    titles = []
    seen_titles: set = set()
    try:
        # Wait for cards, scroll to populate more, then scroll back
        page.wait_for_selector("ytd-rich-item-renderer", timeout=20000)
        human_sleep(1.0, 2.0)
        for _ in range(3):
            human_scroll(page, 500, steps=6)
            human_sleep(0.6, 1.2)
        page.evaluate("window.scrollTo(0, 0)")
        human_sleep(1.0, 1.5)

        # h3 a inside each card is the clickable title link on the homepage
        title_links = page.locator("ytd-rich-item-renderer h3 a").all()
        for link in title_links:
            try:
                title = (link.text_content(timeout=2000) or "").strip()
                href = link.get_attribute("href") or ""
                if title and "/shorts/" not in href and title not in seen_titles:
                    seen_titles.add(title)
                    titles.append({"title": title, "url": href})
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Feed snapshot failed: {e}")
    titles = titles[:15]
    logger.info(f"  Captured {len(titles)} unique titles from feed.")
    return titles


def search_topic(page: Page, topic: str, logger: logging.Logger) -> None:
    """Type a search query in the YouTube search bar and submit."""
    logger.info(f"Searching for topic: '{topic}'")
    try:
        search_input = page.locator(SELECTORS["search_input"]).first
        search_input.click()
        human_sleep(0.3, 0.7)
        search_input.fill("")
        human_sleep(0.1, 0.3)
        human_type(search_input, topic)
        human_sleep(0.3, 0.7)
        search_input.press("Enter")
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        human_sleep(1.0, 2.5)
        dismiss_popups(page, logger)
    except Exception as e:
        logger.error(f"Search failed for '{topic}': {e}")


def get_video_duration(page: Page, logger: logging.Logger) -> Optional[float]:
    """Read the video duration (seconds) from the HTML5 video element."""
    try:
        duration = page.evaluate("() => document.querySelector('video')?.duration")
        if duration and duration > 0 and duration != float("inf"):
            return float(duration)
    except Exception as e:
        logger.debug(f"  Could not read video duration: {e}")
    return None


def _watch_current_page(
    page: Page,
    title: str,
    watch_pct_min: float,
    watch_pct_max: float,
    logger: logging.Logger,
    session_end: float = None,
) -> None:
    """Watch the video already loaded in the current page tab."""
    logger.info(f"  Watching: '{title}'")
    try:
        human_sleep(1.5, 3.0)
        dismiss_popups(page, logger)
        skip_ads(page, logger)
        ensure_autoplay_off(page, logger)

        # Click player only if video is not already playing
        try:
            player = page.locator("video").first
            player.wait_for(state="attached", timeout=8000)
            is_playing = page.evaluate(
                "() => { const v = document.querySelector('video'); return v && !v.paused && !v.ended; }"
            )
            if not is_playing:
                page.locator("#movie_player, .html5-video-container").first.click()
                human_sleep(0.8, 1.5)
                skip_ads(page, logger)
            else:
                logger.debug("  Video already playing — skipping player click.")
        except Exception as e:
            logger.debug(f"  Player click skipped: {e}")

        human_sleep(1.0, 2.0)
        duration = get_video_duration(page, logger)

        LONG_VIDEO_THRESHOLD = 15 * 60  # 15 minutes in seconds

        if duration:
            if duration > LONG_VIDEO_THRESHOLD:
                watch_time = jitter(8, 12)
                logger.info(f"  Video is {duration/60:.0f}min — too long, watching only {watch_time:.0f}s to signal preference for shorter content.")
            else:
                pct = jitter(watch_pct_min, watch_pct_max)
                watch_time = duration * pct
                logger.info(f"  Video is {duration:.0f}s — watching {pct*100:.0f}% = {watch_time:.0f}s")
        else:
            watch_time = jitter(60, 120)
            logger.info(f"  Duration unknown — watching {watch_time:.0f}s as fallback")

        # Cap watch time so we never run past the session deadline
        if session_end is not None:
            remaining_session = max(0.0, session_end - time.time())
            if watch_time > remaining_session:
                logger.info(f"  Capping watch time to {remaining_session:.0f}s (session ending soon)")
                watch_time = remaining_session

        if watch_time <= 0:
            return

        # Keep the video player in focus — no downward scrolling while watching
        elapsed = 0.0
        with tqdm(total=int(watch_time), desc=f"Watching", unit="s", leave=False) as bar:
            while elapsed < watch_time:
                if session_end is not None and time.time() >= session_end:
                    logger.info("  Session time reached — stopping watch early")
                    break
                chunk = jitter(8, 20)
                sleep_time = min(chunk, watch_time - elapsed)
                time.sleep(sleep_time)
                step = min(int(sleep_time), int(watch_time) - bar.n)
                bar.update(step)
                elapsed += chunk
                skip_ads(page, logger)

        human_sleep(0.5, 1.5)
    except Exception as e:
        logger.error(f"  Error while watching '{title}': {e}")


def watch_sidebar_recommendation(
    page: Page,
    main_topic: str,
    watch_pct_min: float,
    watch_pct_max: float,
    depth: int,
    logger: logging.Logger,
    session_end: float = None,
) -> int:
    """
    After watching a video, scroll just enough to reveal the sidebar, pick a
    related video, watch it, then chain up to `depth` levels deep.
    Returns the number of sidebar videos watched.
    """
    watched = 0
    seen_hrefs: set = set()

    for level in range(depth):
        try:
            # Wait for sidebar to load before scanning
            human_sleep(10, 13)
            page.evaluate("window.scrollTo(0, 400)")
            human_sleep(0.8, 1.5)

            # Wait for at least one sidebar card to appear
            try:
                page.wait_for_selector("#secondary yt-lockup-view-model", timeout=10000)
            except Exception:
                logger.debug(f"  Sidebar level {level+1}: timed out waiting for cards.")
                break

            sidebar_cards = page.locator("#secondary yt-lockup-view-model").all()
            if not sidebar_cards:
                logger.debug(f"  Sidebar level {level+1}: no cards found.")
                break

            # Collect candidates from first 15 sidebar cards, skip already-seen
            candidates = []
            for card in sidebar_cards[:15]:
                try:
                    title_el = card.locator("h3 a").first
                    title = (title_el.text_content(timeout=1500) or "").strip()
                    href = title_el.get_attribute("href") or ""
                    if title and href and "/shorts/" not in href and href not in seen_hrefs:
                        candidates.append((title, href))
                except Exception:
                    pass

            if not candidates:
                logger.debug(f"  Sidebar level {level+1}: no unseen candidates.")
                break

            # Classify with Claude or keyword fallback
            titles = [t for t, _ in candidates]
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                try:
                    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
                    client = anthropic.Anthropic(api_key=api_key)
                    msg = client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=128,
                        messages=[{
                            "role": "user",
                            "content": (
                                f"For each title, reply true if related to '{main_topic}', false if not.\n\n"
                                f"{numbered}\n\nReply with ONLY a JSON array of booleans."
                            ),
                        }],
                    )
                    raw = msg.content[0].text.strip()
                    if raw.startswith("```"):
                        raw = raw.split("```")[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                    related_flags = json.loads(raw.strip())
                except Exception as e:
                    logger.debug(f"  Sidebar Claude classification failed: {e}")
                    keywords = [w.lower() for w in main_topic.split() if len(w) > 3]
                    related_flags = [any(k in t.lower() for k in keywords) for t in titles]
            else:
                keywords = [w.lower() for w in main_topic.split() if len(w) > 3]
                related_flags = [any(k in t.lower() for k in keywords) for t in titles]

            matches = [(t, h) for (t, h), rel in zip(candidates, related_flags) if rel]
            logger.info(f"  Sidebar level {level+1}: {len(matches)} / {len(candidates)} match '{main_topic}'.")
            logger.info(f"  Sidebar candidates: {[t for t, h in candidates[:5]]}")
            logger.info(f"  Sidebar matches:    {[t for t, h in matches[:3]]}")

            if not matches:
                break

            # Re-find link fresh by href to avoid stale element reference
            title, href = matches[0]
            logger.info(f"  [Sidebar pick] '{title}'")
            seen_hrefs.add(href)
            page.evaluate("window.scrollTo(0, 0)")
            human_sleep(0.3, 0.6)
            link = page.locator(f'#secondary a[href="{href}"]').first
            link.scroll_into_view_if_needed(timeout=8000)
            human_sleep(0.5, 1.0)
            link.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            _watch_current_page(page, title, watch_pct_min, watch_pct_max, logger, session_end=session_end)
            watched += 1

        except Exception as e:
            logger.debug(f"  Sidebar level {level+1} failed: {e}")
            break

    return watched


def search_and_watch(
    page: Page,
    topic: str,
    main_topic: str,
    n_videos: int,
    watch_pct_min: float,
    watch_pct_max: float,
    logger: logging.Logger,
    sidebar_depth: int = 1,
    session_end: float = None,
) -> None:
    """
    Search for a topic, then click each result video directly from the
    search results page (no direct URL navigation).
    """
    search_topic(page, topic, logger)
    human_sleep(1.0, 2.5)

    watched = 0
    seen_titles: set = set()
    scroll_attempts = 0
    consecutive_failures = 0

    while watched < n_videos and scroll_attempts < 5 and consecutive_failures < 3:
        # Re-query cards fresh each iteration — never hold stale element refs
        cards = page.locator(SELECTORS["result_video_card"]).all()
        candidates = []
        for card in cards:
            try:
                title_el = card.locator("a#video-title, #video-title").first
                title = (title_el.text_content(timeout=2000) or "").strip()
                href = title_el.get_attribute("href") or ""
                if title and href and "/shorts/" not in href and title not in seen_titles:
                    candidates.append((title, href))
            except Exception:
                pass

        picked = next(((t, h) for t, h in candidates if t not in seen_titles), None)

        if not picked:
            human_scroll(page, 400)
            human_sleep(0.8, 1.8)
            scroll_attempts += 1
            continue

        title, href = picked
        seen_titles.add(title)
        logger.info(f"  [Search pick] '{title}' (query: '{topic}')")

        try:
            # Re-find the link fresh by href to avoid stale element errors
            clickable = page.locator(f'a#video-title[href="{href}"], a[href="{href}"]').first
            try:
                clickable.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                # Fall back to JS scroll if element isn't visible yet
                page.evaluate(f'document.querySelector(\'a[href="{href}"]\')?.scrollIntoView()')
                human_sleep(0.3, 0.6)
            human_sleep(0.4, 0.9)
            clickable.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)

            _watch_current_page(page, title, watch_pct_min, watch_pct_max, logger, session_end=session_end)
            watched += 1
            consecutive_failures = 0  # Reset on success

            if sidebar_depth == 0:
                chain_watched = 0
            else:
                chain_watched = watch_sidebar_recommendation(
                    page, main_topic, watch_pct_min, watch_pct_max,
                    depth=sidebar_depth, logger=logger, session_end=session_end,
                )
            steps_back = chain_watched + (1 if watched < n_videos else 0)

            for _ in range(steps_back):
                page.go_back()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                human_sleep(0.8, 1.5)
            # After returning to search results, wait for cards to be visible
            if watched < n_videos:
                try:
                    page.wait_for_selector(SELECTORS["result_video_card"], timeout=10000)
                    human_sleep(0.5, 1.0)
                except Exception:
                    search_topic(page, topic, logger)
        except Exception as e:
            consecutive_failures += 1
            logger.error(f"  Failed to click/watch '{title}' (failure {consecutive_failures}): {e}")
            # Re-search to get back to a clean state
            search_topic(page, topic, logger)

    logger.info(f"  Watched {watched} videos for topic '{topic}'")



def _is_clearly_unrelated(titles: list[str], main_topic: str, logger: logging.Logger) -> list[bool]:
    """
    Second-pass filter: returns True for titles that are from a completely
    different domain to main_topic. Adjacent or tangentially related content
    returns False so we don't accidentally reject it.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return [True] * len(titles)
    try:
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=128,
            messages=[{
                "role": "user",
                "content": (
                    f"For each YouTube title, reply true ONLY if it is from a completely "
                    f"different domain to '{main_topic}' (e.g. gaming, cooking, or music "
                    f"when the topic is politics). Reply false if it is adjacent, related, "
                    f"or potentially interesting to someone who follows '{main_topic}'.\n\n"
                    f"{numbered}\n\nReply with ONLY a JSON array of booleans."
                ),
            }],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        flags = json.loads(raw.strip())
        while len(flags) < len(titles):
            flags.append(False)
        return flags[:len(titles)]
    except Exception as e:
        logger.debug(f"  _is_clearly_unrelated failed ({e}) — defaulting to safe (false)")
        return [False] * len(titles)


def mark_not_interested(
    page: Page,
    non_matches: list,
    logger: logging.Logger,
    main_topic: str = "",
    max_marks: int = 2,
) -> int:
    """
    Mark up to max_marks non-matching homepage videos as 'Not interested'.
    Only marks videos that are clearly from a different domain — not adjacent
    or tangentially related content.
    Returns count of successfully marked videos.
    """
    if not non_matches:
        return 0

    # Filter to only truly unrelated content before marking
    titles = [t for t, _ in non_matches]
    unrelated_flags = _is_clearly_unrelated(titles, main_topic, logger)
    truly_unrelated = [(t, h) for (t, h), flag in zip(non_matches, unrelated_flags) if flag]

    if not truly_unrelated:
        logger.debug("  [Not interested] no clearly unrelated videos in top-6 — skipping")
        return 0

    targets = random.sample(truly_unrelated, min(max_marks, len(truly_unrelated)))
    marked = 0

    for title, href in targets:
        try:
            cards = page.locator(f'ytd-rich-item-renderer:has(a[href="{href}"])')
            if cards.count() == 0:
                logger.debug(f"  [Not interested] card not found: '{title}'")
                continue

            card = cards.first
            card.hover()
            human_sleep(0.5, 1.0)

            # Click the "More actions" menu button (force bypasses YouTube's hover-only visibility)
            menu_btn = card.locator('button[aria-label="More actions"]').first
            menu_btn.click(timeout=4000, force=True)
            human_sleep(0.5, 1.0)

            # Click "Not interested" from the dropdown
            not_interested = page.locator('tp-yt-iron-dropdown yt-list-item-view-model').filter(has_text="Not interested").locator('button').first
            not_interested.click(timeout=3000)
            human_sleep(0.8, 1.5)

            # Dismiss "Tell us why" follow-up if it appears
            try:
                close = page.locator(
                    'yt-button-shape button[aria-label="Dismiss"], button[aria-label="Dismiss"]'
                ).first
                if close.is_visible(timeout=1500):
                    close.click()
                    human_sleep(0.3, 0.6)
            except Exception:
                pass

            logger.info(f"  [Not interested] ✗ '{title}'")
            marked += 1
            human_sleep(1.5, 2.5)

        except Exception as e:
            # Press Escape to close any open menu before continuing
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            logger.debug(f"  [Not interested] skipped '{title}': {e}")

    return marked


def get_homepage_matches(
    page: Page,
    main_topic: str,
    logger: logging.Logger,
    sample_size: int = 10,
) -> list:
    """
    Scroll the homepage, collect visible video cards, classify them with Claude
    against main_topic, and return a list of (title, href) for matching videos.
    Does NOT click or watch anything — pure candidate discovery.
    """
    try:
        page.wait_for_selector("ytd-rich-item-renderer", timeout=15000)
        for _ in range(3):
            human_scroll(page, 500)
            human_sleep(0.6, 1.2)
        page.evaluate("window.scrollTo(0, 0)")
        human_sleep(0.5, 1.0)

        cards = page.locator("ytd-rich-item-renderer").all()
        entries = []
        seen_hrefs: set = set()
        for card in cards:
            try:
                link = card.locator("h3 a").first
                title = (link.text_content(timeout=1500) or "").strip()
                href = link.get_attribute("href") or ""
                if title and href and "/shorts/" not in href and href not in seen_hrefs:
                    entries.append((title, href))
                    seen_hrefs.add(href)
            except Exception:
                pass

        if not entries:
            logger.info("  get_homepage_matches: no cards found.")
            return []

        # Classify up to sample_size titles with Claude
        sample = entries[:sample_size]
        titles = [t for t, _ in sample]

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        related_flags = [False] * len(titles)
        if api_key:
            try:
                numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=256,
                    messages=[{
                        "role": "user",
                        "content": (
                            f"For each YouTube title, reply true if related to '{main_topic}', false if not.\n\n"
                            f"{numbered}\n\nReply with ONLY a JSON array of booleans."
                        ),
                    }],
                )
                raw = msg.content[0].text.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                related_flags = json.loads(raw.strip())
            except Exception as e:
                logger.debug(f"  get_homepage_matches Claude classification failed: {e}")
                keywords = [w.lower() for w in main_topic.split() if len(w) > 3]
                related_flags = [any(k in t.lower() for k in keywords) for t in titles]
        else:
            keywords = [w.lower() for w in main_topic.split() if len(w) > 3]
            related_flags = [any(k in t.lower() for k in keywords) for t in titles]

        matches     = [(t, h) for (t, h), rel in zip(sample, related_flags) if rel]
        non_matches = [(t, h) for (t, h), rel in zip(sample, related_flags) if not rel]
        logger.info(
            f"  Homepage: {len(matches)} / {len(sample)} sampled cards match '{main_topic}'"
        )
        logger.info(f"  Homepage sampled titles: {[t for t, h in sample]}")
        logger.info(f"  Homepage matched titles: {[t for t, h in matches]}")

        # Only mark "Not interested" on non-matches in the top 6 positions —
        # top slots carry the most algorithmic weight
        top_6_non_matches = [(t, h) for (t, h), rel in zip(sample[:6], related_flags[:6]) if not rel]
        marked = mark_not_interested(page, top_6_non_matches, logger, main_topic=main_topic, max_marks=2)
        if marked:
            logger.info(f"  Marked {marked} homepage video(s) as 'Not interested'")
            # Scroll back to top after menu interactions
            page.evaluate("window.scrollTo(0, 0)")
            human_sleep(0.5, 1.0)

        return matches

    except Exception as e:
        logger.error(f"get_homepage_matches failed: {e}")
        return []


def watch_matching_homepage_videos(
    page: Page,
    target_topics: list,
    main_topic: str,
    watch_pct_min: float,
    watch_pct_max: float,
    max_videos: int,
    logger: logging.Logger,
    session_end: float = None,
) -> int:
    """
    Scroll the homepage feed, use Claude to identify on-topic videos,
    then click and watch them. Logs how many feed videos match the main topic.
    Returns the count of videos watched.
    """
    topic_keywords = [t.lower() for t in target_topics]

    def _keyword_match(title: str) -> bool:
        tl = title.lower()
        return any(kw in tl for kw in topic_keywords)

    watched = 0
    seen_urls = set()

    logger.info("Scanning homepage feed for on-topic videos to watch ...")
    try:
        # Scroll down a few times to load more cards
        for _ in range(4):
            human_scroll(page, 500)
            human_sleep(0.8, 1.5)
        page.evaluate("window.scrollTo(0, 0)")
        human_sleep(0.5, 1.0)

        # Collect all feed cards with their titles
        cards = page.locator("ytd-rich-item-renderer").all()
        all_entries = []  # (title, card, href)
        for card in cards:
            try:
                link = card.locator("h3 a").first
                title = (link.text_content(timeout=2000) or "").strip()
                href = link.get_attribute("href") or ""
                if title and href and "/shorts/" not in href and href not in seen_urls:
                    all_entries.append((title, card, href))
                    seen_urls.add(href)
            except Exception:
                pass

        total_feed = len(all_entries)

        # Only classify the first 10 to keep API cost low
        all_entries = all_entries[:10]

        # Classify titles with Claude (or keyword fallback)
        title_list = [t for t, _, _ in all_entries]
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        related_flags = [False] * len(title_list)
        if api_key and title_list:
            try:
                numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(title_list))
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=512,
                    messages=[{
                        "role": "user",
                        "content": (
                            f"For each YouTube title below, reply true if it is related to '{main_topic}', false if not.\n\n"
                            f"{numbered}\n\n"
                            "Reply with ONLY a JSON array of booleans, one per title. No explanation."
                        ),
                    }],
                )
                raw = msg.content[0].text.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                related_flags = json.loads(raw.strip())
            except Exception as e:
                logger.warning(f"  Claude homepage classification failed ({e}) — using keyword fallback.")
                related_flags = [_keyword_match(t) for t in title_list]
        else:
            related_flags = [_keyword_match(t) for t in title_list]

        # Log every title + its classification result for debugging
        for title, flag in zip(title_list, related_flags):
            logger.info(f"  [Homepage classify] {'✓' if flag else '✗'} {title!r} → {flag}")

        # Store (title, href) only — never hold card element refs across navigations
        matches = [(t, h) for (t, _, h), rel in zip(all_entries, related_flags) if rel]
        match_count = len(matches)
        match_pct = match_count / total_feed * 100 if total_feed else 0
        logger.info(
            f"  Homepage feed: {match_count} / {total_feed} videos match '{main_topic}' ({match_pct:.0f}%)"
        )

        random.shuffle(matches)

        for title, href in matches[:max_videos]:
            try:
                # Re-query fresh by href to avoid stale element errors
                clickable = page.locator(f'a[href="{href}"]').first
                try:
                    clickable.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    page.evaluate(f'document.querySelector(\'a[href="{href}"]\')?.scrollIntoView()')
                    human_sleep(0.3, 0.6)
                human_sleep(0.4, 0.9)
                clickable.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                _watch_current_page(page, title, watch_pct_min, watch_pct_max, logger, session_end=session_end)
                watched += 1

                # Dive 1 level into the sidebar from this homepage recommendation —
                # "you served this, I watched it AND followed the rabbit hole"
                sidebar_watched = watch_sidebar_recommendation(
                    page, main_topic, watch_pct_min, watch_pct_max,
                    depth=1, logger=logger, session_end=session_end,
                )
                for _ in range(sidebar_watched):
                    page.go_back()
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    human_sleep(0.8, 1.5)
            except Exception as e:
                logger.error(f"  Failed to click homepage video '{title}': {e}")
            # Return to homepage for the next video
            go_home(page, logger)

    except Exception as e:
        logger.error(f"Homepage watch scan failed: {e}")

    logger.info(f"  Watched {watched} on-topic videos from homepage feed.")
    return watched


def go_home(page: Page, logger: logging.Logger, main_topic: str = "") -> None:
    """Navigate back to YouTube homepage."""
    logger.info("Navigating to YouTube homepage ...")
    try:
        page.goto("https://www.youtube.com", timeout=20000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        human_sleep(1.5, 3.0)
        dismiss_popups(page, logger)
    except Exception as e:
        logger.error(f"Failed to navigate home: {e}")


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def classify_titles_with_claude(titles: list, main_topic: str, logger: logging.Logger) -> Counter:
    """
    Use Claude to classify each feed title as related or unrelated to main_topic.
    Falls back to simple keyword matching if the API is unavailable.
    """
    if not titles:
        return Counter()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _classify_titles_keyword(titles, main_topic)

    try:
        title_list = "\n".join(f"{i+1}. {e['title']}" for i, e in enumerate(titles))
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": (
                    f"For each YouTube video title below, classify it as either "
                    f"'related' or 'unrelated' to the topic: '{main_topic}'.\n\n"
                    f"{title_list}\n\n"
                    "Reply with ONLY a JSON array of booleans (true=related, false=unrelated), "
                    "one per title in order. No explanation."
                ),
            }],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        results = json.loads(raw.strip())

        counts: Counter = Counter()
        for _, is_related in zip(titles, results):
            counts[main_topic if is_related else "Other"] += 1
        logger.info(f"  Claude classified {counts[main_topic]} / {len(titles)} titles as related to '{main_topic}'")
        return counts
    except Exception as e:
        logger.warning(f"Claude classification failed ({e}) — falling back to keyword matching.")
        return _classify_titles_keyword(titles, main_topic)


def _classify_titles_keyword(titles: list, main_topic: str) -> Counter:
    """Simple keyword fallback classifier."""
    keywords = [w.lower() for w in main_topic.split() if len(w) > 3]
    counts: Counter = Counter()
    for t in titles:
        tl = t["title"].lower()
        counts[main_topic if any(k in tl for k in keywords) else "Other"] += 1
    return counts


def generate_report(
    before: list,
    after: list,
    main_topic: str,
    report_path: str,
    logger: logging.Logger,
) -> None:
    before_counts = classify_titles_with_claude(before, main_topic, logger)
    after_counts  = classify_titles_with_claude(after,  main_topic, logger)
    total_before  = max(len(before), 1)
    total_after   = max(len(after),  1)

    lines = [
        "=" * 60,
        "  YouTube Feed Reshaping — Session Report",
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
        f"{'Category':<28} {'Before':>8} {'%':>6}   {'After':>8} {'%':>6}   {'Delta':>7}",
        "-" * 66,
    ]

    all_keys = sorted(set(list(before_counts.keys()) + list(after_counts.keys())))
    for key in all_keys:
        b  = before_counts.get(key, 0)
        a  = after_counts.get(key, 0)
        bp = b / total_before * 100
        ap = a / total_after  * 100
        delta = ap - bp
        sign  = "+" if delta >= 0 else ""
        lines.append(
            f"{key:<28} {b:>8} {bp:>5.1f}%   {a:>8} {ap:>5.1f}%   {sign}{delta:>5.1f}%"
        )

    lines += [
        "-" * 66,
        f"{'TOTAL':<28} {total_before:>8}          {total_after:>8}",
        "",
        "Main topic: " + main_topic,
        "=" * 60,
    ]

    report_text = "\n".join(lines)
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print("\n" + report_text)
    logger.info(f"Report saved to {report_path}")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run(config: dict, logger: logging.Logger) -> None:
    main_topic            = config["main_topic"]
    narrow_topics_raw     = config.get("narrow_topics", config.get("narrow_topic", main_topic))
    if isinstance(narrow_topics_raw, str):
        narrow_topics_raw = [narrow_topics_raw]
    num_subtopics         = config.get("num_subtopics", 8)

    logger.info("=" * 50)
    logger.info(f"  main_topic:     {main_topic}")
    logger.info(f"  narrow_topics:  {narrow_topics_raw}")
    logger.info("=" * 50)

    # Generate subtopics per narrow topic then interleave them
    all_subtopic_lists = [
        generate_subtopics(nt, num_subtopics, logger) for nt in narrow_topics_raw
    ]
    target_topics = [
        topic
        for subtopics in zip(*all_subtopic_lists)
        for topic in subtopics
    ]
    # Append any remainder if lists are uneven
    max_len = max(len(s) for s in all_subtopic_lists)
    for i in range(len(narrow_topics_raw)):
        if len(all_subtopic_lists[i]) > len(narrow_topics_raw):
            target_topics += all_subtopic_lists[i][max_len:]
    logger.info(f"Interleaved subtopics ({len(target_topics)} total): {target_topics}")
    session_minutes       = config["session_duration_minutes"]
    videos_per_topic      = config.get("videos_per_topic", 4)
    watch_pct_min         = config.get("watch_pct_min", 0.5)
    watch_pct_max         = config.get("watch_pct_max", 0.7)
    max_homepage_watches  = config.get("max_homepage_watches_per_cycle", 10)
    rabbit_hole_depth     = config.get("homepage_rabbit_hole_depth", 2)
    cycle_budget_seconds  = config.get("cycle_budget_seconds", 12 * 60)  # 12 min per cycle max
    search_sidebar_depth  = config.get("search_sidebar_depth", 1)  # sidebar depth in search fallback (0=skip)
    homepage_sample_size  = config.get("homepage_sample_size", 10)  # cards classified on homepage
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1280,800",
                "--mute-audio",
            ],
        )

        recording_dir = Path(config["_run_dir"]) if "_run_dir" in config else Path("recordings")
        recording_dir.mkdir(parents=True, exist_ok=True)

        auth_file = Path(config.get("_auth_file", "auth.json"))
        context_kwargs = {
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
        }
        if auth_file.exists():
            logger.info(f"Loading saved session from {auth_file} ...")
            context_kwargs["storage_state"] = str(auth_file)
        else:
            logger.warning(f"{auth_file} not found — run setup_auth.py first.")

        context = browser.new_context(**context_kwargs)

        page = context.new_page()

        # ------------------------------------------------------------------
        # Step 1 — Open YouTube
        # ------------------------------------------------------------------
        logger.info("Opening youtube.com ...")
        page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
        human_sleep(1.5, 3.0)
        dismiss_popups(page, logger)

        # ------------------------------------------------------------------
        # Step 3 — BEFORE snapshot (already on homepage from Step 1)
        # ------------------------------------------------------------------
        before_titles = snapshot_feed(page, logger)
        Path(config["before_snapshot_file"]).parent.mkdir(parents=True, exist_ok=True)
        with open(config["before_snapshot_file"], "w", encoding="utf-8") as f:
            json.dump(before_titles, f, indent=2)
        logger.info(f"Before snapshot saved: {config['before_snapshot_file']}")

        # ------------------------------------------------------------------
        # Step 4 — Reshaping loop
        # ------------------------------------------------------------------
        session_start = time.time()
        session_end   = session_start + session_minutes * 60
        cycle         = 0

        subtopic_index = 0

        while time.time() < session_end:
            cycle += 1
            remaining = (session_end - time.time()) / 60
            logger.info(f"=== Cycle {cycle} | {remaining:.1f} min remaining ===")

            cycle_start = time.time()
            cycle_end   = cycle_start + cycle_budget_seconds

            # --- Step 1: Go to homepage ---
            go_home(page, logger)
            if time.time() >= session_end:
                break

            # --- Step 2: Check for matching homepage videos ---
            homepage_matched = get_homepage_matches(page, main_topic, logger, sample_size=homepage_sample_size)

            if homepage_matched:
                # Homepage has on-topic content — click matches and go deep
                logger.info(f"  Homepage has {len(homepage_matched)} match(es) — diving into rabbit holes (budget={cycle_budget_seconds//60}min)")
                consecutive_failures = 0
                for title, href in homepage_matched[:max_homepage_watches]:
                    if time.time() >= session_end or time.time() >= cycle_end:
                        logger.info(f"  Cycle budget reached — moving to next cycle")
                        break
                    # After 2 consecutive click failures the page is likely in a broken
                    # state (ad overlay, slow load). Do a hard home navigation to reset.
                    if consecutive_failures >= 2:
                        logger.warning(f"  {consecutive_failures} consecutive click failures — hard reset to homepage")
                        try:
                            page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=20000)
                            human_sleep(2.0, 3.0)
                        except Exception:
                            pass
                        consecutive_failures = 0
                        break  # Skip remaining matches in this cycle — re-classify on next cycle
                    try:
                        clickable = page.locator(f'a[href="{href}"]').first
                        try:
                            clickable.scroll_into_view_if_needed(timeout=5000)
                        except Exception:
                            page.evaluate(f'document.querySelector(\'a[href="{href}"]\')?.scrollIntoView()')
                            human_sleep(0.3, 0.6)
                        human_sleep(0.4, 0.9)
                        clickable.click()
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                        _watch_current_page(page, title, watch_pct_min, watch_pct_max, logger, session_end=session_end)
                        consecutive_failures = 0  # Reset on success

                        if time.time() >= cycle_end:
                            logger.info(f"  Cycle budget reached after watching '{title}' — skipping rabbit hole")
                        else:
                            # Rabbit hole from homepage match
                            sidebar_watched = watch_sidebar_recommendation(
                                page, main_topic, watch_pct_min, watch_pct_max,
                                depth=rabbit_hole_depth, logger=logger, session_end=session_end,
                            )
                            for _ in range(sidebar_watched):
                                page.go_back()
                                page.wait_for_load_state("domcontentloaded", timeout=15000)
                                human_sleep(0.8, 1.5)
                    except Exception as e:
                        consecutive_failures += 1
                        logger.error(f"  Failed homepage rabbit hole for '{title}' (failure {consecutive_failures}): {e}")
                    go_home(page, logger)
                    # Homepage is fresh after each rabbit hole — fire "Not interested"
                    # on top-6 non-matches while we're here
                    get_homepage_matches(page, main_topic, logger, sample_size=homepage_sample_size)
            else:
                # No homepage matches — seed with search, 2 videos at a time,
                # checking homepage after each batch so we switch back the moment
                # the algorithm starts responding.
                search_cycles = 0
                max_search_cycles = max(1, len(target_topics))
                while time.time() < session_end and time.time() < cycle_end and search_cycles < max_search_cycles:
                    topic = target_topics[subtopic_index % len(target_topics)]
                    subtopic_index += 1
                    search_cycles += 1
                    logger.info(f"  [Search seed {search_cycles}] '{topic}'")
                    search_and_watch(
                        page, topic, main_topic, 2,
                        watch_pct_min, watch_pct_max, logger,
                        sidebar_depth=search_sidebar_depth, session_end=session_end,
                    )

                    # Return to homepage and re-check — break out as soon as
                    # the algorithm starts serving target content
                    go_home(page, logger)
                    fresh_matches = get_homepage_matches(page, main_topic, logger, sample_size=homepage_sample_size)
                    if fresh_matches:
                        logger.info(f"  Homepage now has {len(fresh_matches)} match(es) after search seed — switching to homepage mode")
                        homepage_matched = fresh_matches
                        # Watch matches now instead of looping back
                        for title, href in homepage_matched[:max_homepage_watches]:
                            if time.time() >= session_end or time.time() >= cycle_end:
                                break
                            try:
                                clickable = page.locator(f'a[href="{href}"]').first
                                try:
                                    clickable.scroll_into_view_if_needed(timeout=5000)
                                except Exception:
                                    page.evaluate(f'document.querySelector(\'a[href="{href}"]\')?.scrollIntoView()')
                                    human_sleep(0.3, 0.6)
                                human_sleep(0.4, 0.9)
                                clickable.click()
                                page.wait_for_load_state("domcontentloaded", timeout=15000)
                                _watch_current_page(page, title, watch_pct_min, watch_pct_max, logger, session_end=session_end)
                                watch_sidebar_recommendation(
                                    page, main_topic, watch_pct_min, watch_pct_max,
                                    depth=rabbit_hole_depth, logger=logger, session_end=session_end,
                                )
                            except Exception as e:
                                logger.error(f"  Failed post-seed homepage watch '{title}': {e}")
                            go_home(page, logger)
                        break

            human_sleep(
                config.get("action_delay_min", 0.5),
                config.get("action_delay_max", 2.0),
            )

        # ------------------------------------------------------------------
        # Step 5 — AFTER snapshot
        # ------------------------------------------------------------------
        go_home(page, logger)
        human_sleep(2.0, 4.0)
        after_titles = snapshot_feed(page, logger)
        with open(config["after_snapshot_file"], "w", encoding="utf-8") as f:
            json.dump(after_titles, f, indent=2)
        logger.info(f"After snapshot saved: {config['after_snapshot_file']}")

        # ------------------------------------------------------------------
        # Step 6 — Generate report
        # ------------------------------------------------------------------
        generate_report(
            before_titles, after_titles,
            main_topic, config["report_file"],
            logger,
        )

        logger.info("Session complete. Closing browser in 10 seconds ...")
        time.sleep(10)
        browser.close()
        recordings = sorted(recording_dir.glob("*.webm"))
        if recordings:
            dest = recording_dir / "recording.webm"
            recordings[-1].rename(dest)
            logger.info(f"Recording saved: {dest}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir",  default=None, help="Folder to write session.log and recording.webm into")
    parser.add_argument("--data-dir", default=None, help="Writable user data directory (auth.json, config.json, snapshots)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).parent.parent
    config_path = data_dir / "config.json"
    cfg = load_config(str(config_path))

    # Resolve auth.json and snapshot paths relative to data_dir
    cfg["_auth_file"]  = str(data_dir / "auth.json")
    cfg["before_snapshot_file"] = str(data_dir / cfg.get("before_snapshot_file", "logs/feed_before.json"))
    cfg["after_snapshot_file"]  = str(data_dir / cfg.get("after_snapshot_file",  "logs/feed_after.json"))
    cfg["report_file"]          = str(data_dir / cfg.get("report_file",           "logs/report.txt"))

    if args.run_dir:
        run_dir = Path(args.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        log_file = str(run_dir / "session.log")
        cfg["_run_dir"] = str(run_dir)
    else:
        log_file = str(data_dir / cfg.get("log_file", "logs/session.log"))

    logger = setup_logging(log_file)
    logger.info("YouTube Feed Reshaper starting ...")
    run(cfg, logger)
