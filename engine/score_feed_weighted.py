"""
LYTESNAP Weighted Feed Scorer
==============================
Position-weighted version of score_feed.py.
Uses linear decay: position 1 = weight 1.0, position N = weight 1/N.
Score = sum(weight_i * match_i) / sum(all weights)

Supports multiple topics — a title matches if it relates to ANY of the topics.

Usage:
    python score_feed_weighted.py --topic "Republican"
    python score_feed_weighted.py --topic "Sports" --topic "Beauty"
    python score_feed_weighted.py --topic "Sports" --topic "Beauty" --verbose
    python score_feed_weighted.py --topic "Sports" --topic "Beauty" --output-json

Output JSON includes both weighted_score and raw_score for comparison.

DO NOT MODIFY score_feed.py — this is the new primary metric going forward.
"""

import argparse
import json
import os
import sys
import time
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Reuse classifiers from score_feed.py — single source of truth
from score_feed import (
    get_logger,
    CLASSIFIER,
    AUTH_FILE,
    VIEWPORT,
)
import anthropic as _anthropic

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


# ---------------------------------------------------------------------------
# Multi-topic classifier
# ---------------------------------------------------------------------------

def classify_multi(titles: list[str], topics: list[str], logger) -> list[bool]:
    """
    Classify titles against multiple topics — a title matches if it relates
    to ANY of the topics. Single Claude call regardless of topic count.
    """
    topics_str = " OR ".join(f'"{t}"' for t in topics)
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    try:
        client = _anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": (
                    f"For each YouTube video title below, reply true if it is related to "
                    f"ANY of these topics: {topics_str}. Reply false if it relates to none of them.\n\n"
                    f"{numbered}\n\n"
                    "Reply with ONLY a JSON array of booleans (true/false), "
                    "one per title in order. No explanation."
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
        logger.warning(f"Multi-topic classification failed ({e}) — keyword fallback")
        keywords = [w.lower() for t in topics for w in t.split() if len(w) > 3]
        return [any(k in title.lower() for k in keywords) for title in titles]


# ---------------------------------------------------------------------------
# Title extraction — returns ordered list (position matters)
# ---------------------------------------------------------------------------

def extract_homepage_titles_ordered(page, logger, limit: int = 10) -> list[str]:
    """Extract top `limit` non-Shorts video titles in homepage order."""
    logger.info("Extracting homepage video titles (ordered) ...")

    for attempt in range(3):
        try:
            page.wait_for_selector("ytd-rich-item-renderer", timeout=20000)
            break  # Feed loaded — proceed
        except PWTimeoutError:
            if attempt < 2:
                logger.warning(f"Homepage feed did not load (attempt {attempt + 1}/3) — refreshing page ...")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=20000)
                    time.sleep(3.0)
                except Exception as reload_err:
                    logger.warning(f"Reload failed: {reload_err}")
            else:
                logger.error("Homepage feed failed to load after 3 attempts — returning empty.")
                return []

    time.sleep(2.0)

    for _ in range(4):
        page.mouse.wheel(0, 500)
        time.sleep(0.8)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1.0)

    title_links = page.locator("ytd-rich-item-renderer h3 a").all()
    titles = []
    seen = set()

    for link in title_links:
        if len(titles) >= limit:
            break
        try:
            title = (link.text_content(timeout=2000) or "").strip()
            href = link.get_attribute("href") or ""
            if title and "/shorts/" not in href and title not in seen:
                seen.add(title)
                titles.append(title)
        except Exception:
            pass

    logger.info(f"  Extracted {len(titles)} titles (top {limit}, ordered)")
    return titles


# ---------------------------------------------------------------------------
# Weighted scoring
# ---------------------------------------------------------------------------

def linear_weights(n: int) -> list[float]:
    """
    Linear decay weights for n positions.
    Position 1 = 1.0, position 2 = (n-1)/n, ..., position n = 1/n.
    Normalized so weights sum to 1.
    """
    raw = [1.0 - (i / n) for i in range(n)]  # 1.0, (n-1)/n, ..., 1/n
    total = sum(raw)
    return [w / total for w in raw]


def score_feed_weighted(topics: list[str] | str, verbose: bool = False, limit: int = 10) -> dict:
    """
    Open YouTube homepage, extract top `limit` titles in order,
    classify against one or more topics (OR logic), apply linear decay weights.

    Args:
        topics: single topic string or list of topics — title matches if it
                relates to ANY topic in the list.

    Returns:
        {
            "weighted_score": float,  # position-weighted match rate
            "raw_score": float,       # unweighted match rate
            "total": int,
            "matches": int,
            "topics": list[str],
            "positions": list[dict],
        }
    """
    if isinstance(topics, str):
        topics = [topics]
    logger = get_logger(verbose)

    if not Path(AUTH_FILE).exists():
        logger.error(f"{AUTH_FILE} not found — run save_session.py first")
        return {"weighted_score": 0.0, "raw_score": 0.0, "total": 0, "matches": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context = browser.new_context(
            viewport=VIEWPORT,
            locale="en-US",
            storage_state=_sf._load_storage_state(AUTH_FILE),
        )

        page = context.new_page()
        for nav_attempt in range(3):
            try:
                page.goto(
                    "https://www.youtube.com",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                break
            except Exception as nav_err:
                if nav_attempt < 2:
                    logger.warning(f"Navigation failed (attempt {nav_attempt + 1}/3): {nav_err} — retrying ...")
                    time.sleep(3.0)
                else:
                    logger.error("Failed to load YouTube after 3 attempts.")
                    browser.close()
                    return {"weighted_score": 0.0, "raw_score": 0.0, "total": 0, "matches": 0, "topics": topics, "positions": []}

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        time.sleep(2.0)

        # Dismiss popups
        for sel in [
            'button[aria-label*="Accept" i], button[aria-label*="agree" i]',
            'button[aria-label="Got it"], tp-yt-paper-button#dismiss',
            'yt-button-renderer#dismiss-button button',
            'button[aria-label="No thanks"]',
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    time.sleep(0.5)
            except Exception:
                pass

        time.sleep(1.0)

        titles = extract_homepage_titles_ordered(page, logger, limit=limit)

        if not titles:
            logger.error("No titles found — returning 0.0")
            browser.close()
            return {"weighted_score": 0.0, "raw_score": 0.0, "total": 0, "matches": 0}

        topics_str = " + ".join(topics)
        logger.info(f"Classifying {len(titles)} titles against [{topics_str}] using {CLASSIFIER} ...")
        flags = classify_multi(titles, topics, logger)

        n = len(titles)
        weights = linear_weights(n)

        weighted_score = sum(w for w, f in zip(weights, flags) if f)
        raw_score = sum(1 for f in flags if f) / n
        matches = sum(1 for f in flags if f)

        positions = [
            {
                "rank": i + 1,
                "title": t,
                "match": f,
                "weight": round(w, 4),
                "contribution": round(w if f else 0.0, 4),
            }
            for i, (t, f, w) in enumerate(zip(titles, flags, weights))
        ]

        if verbose:
            print(f"\n{'='*60}")
            print(f"  Topics:         {' | '.join(topics)}")
            print(f"  Classifier:     {CLASSIFIER}")
            print(f"  Total:          {n}")
            print(f"  Matches:        {matches}")
            print(f"  Raw score:      {raw_score:.4f} ({raw_score*100:.1f}%)")
            print(f"  Weighted score: {weighted_score:.4f} ({weighted_score*100:.1f}%)")
            print(f"{'='*60}")
            for pos in positions:
                marker = "\u2713" if pos["match"] else "\u2717"
                print(f"  {marker} #{pos['rank']:2d} [w={pos['weight']:.3f}] {pos['title']}")
            print()

        browser.close()

        return {
            "weighted_score": round(weighted_score, 4),
            "raw_score": round(raw_score, 4),
            "total": n,
            "matches": matches,
            "topics": topics,
            "positions": positions,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LYTESNAP — Weighted score of YouTube homepage against a target topic"
    )
    parser.add_argument("--topic", required=True, action="append", dest="topics",
                        help="Target topic (repeat for multiple: --topic Sports --topic Beauty)")
    parser.add_argument("--verbose", action="store_true", help="Detailed per-position output")
    parser.add_argument("--output-json", action="store_true", help="Full JSON result")
    parser.add_argument("--limit", type=int, default=10, help="Top N cards to score (default 10)")
    parser.add_argument("--data-dir", default=None, help="Writable user data directory (auth.json)")
    args = parser.parse_args()

    if args.data_dir:
        import score_feed as _sf
        _sf.AUTH_FILE = str(Path(args.data_dir) / "auth.json")

    result = score_feed_weighted(args.topics, verbose=args.verbose, limit=args.limit)

    if args.output_json:
        result["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        result["classifier"] = CLASSIFIER
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['weighted_score']:.4f}")


if __name__ == "__main__":
    main()
