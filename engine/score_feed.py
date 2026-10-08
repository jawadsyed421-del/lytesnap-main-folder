"""
LYTESNAP Feed Scorer
====================
Standalone scoring function for the autoresearch loop.
Navigates to YouTube homepage, extracts visible video titles,
classifies each against the target topic, and outputs a single
float between 0.0 and 1.0.

Usage:
    python score_feed.py --topic "Marine Biology"
    python score_feed.py --topic "Marine Biology" --verbose
    python score_feed.py --topic "Marine Biology" --output-json

Classifier backends:
    LYTESNAP_CLASSIFIER=claude  (default) — uses Claude Haiku API
    LYTESNAP_CLASSIFIER=local   — uses local GGUF model via llama-cpp-python
        Set LYTESNAP_LOCAL_MODEL=path/to/model.gguf

DO NOT MODIFY THIS FILE during autoresearch — it is the fixed
measurement function. Only the feed-flipping script gets optimized.
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

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_storage_state(auth_file):
    """Session for Playwright: the encrypted store if present, else the file.

    AUTH-ONLY helper. The measurement logic below is unchanged; this exists so
    the scorer keeps working once the session is encrypted.
    """
    data_dir = Path(auth_file).resolve().parent
    try:
        import session_store
        state = session_store.load(data_dir)
        if state:
            return state
    except Exception:
        pass
    return str(auth_file)


def _session_available(auth_file) -> bool:
    data_dir = Path(auth_file).resolve().parent
    if Path(auth_file).exists():
        return True
    try:
        import session_store
        return session_store.enc_path(data_dir).exists()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CLASSIFIER = os.environ.get("LYTESNAP_CLASSIFIER", "claude")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
LOCAL_MODEL_PATH = os.environ.get("LYTESNAP_LOCAL_MODEL", "")
AUTH_FILE = "auth.json"
VIEWPORT = {"width": 1280, "height": 800}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def get_logger(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("scorer")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Title extraction — mirrors flip_feed.py selectors and scroll behavior
# ---------------------------------------------------------------------------

def extract_homepage_titles(page, logger) -> list[str]:
    """Extract visible non-Shorts video titles from YouTube homepage."""
    logger.info("Extracting homepage video titles ...")

    for attempt in range(3):
        try:
            page.wait_for_selector("ytd-rich-item-renderer", timeout=20000)
            break
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

    # Scroll to load more content (matches flip_feed.py snapshot_feed)
    for _ in range(4):
        page.mouse.wheel(0, 500)
        time.sleep(0.8)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1.0)

    # Same selector as flip_feed.py: ytd-rich-item-renderer h3 a
    title_links = page.locator("ytd-rich-item-renderer h3 a").all()
    titles = []
    seen = set()

    for link in title_links:
        try:
            title = (link.text_content(timeout=2000) or "").strip()
            href = link.get_attribute("href") or ""
            if title and "/shorts/" not in href and title not in seen:
                seen.add(title)
                titles.append(title)
        except Exception:
            pass

    logger.info(f"  Extracted {len(titles)} unique titles (excluding Shorts)")
    return titles


# ---------------------------------------------------------------------------
# Classifiers — same prompt format as flip_feed.py for consistency
# ---------------------------------------------------------------------------

def classify_claude(titles: list[str], topic: str, logger) -> list[bool]:
    """Classify titles using Claude Haiku. Same prompt as flip_feed.py."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        return _classify_keyword_fallback(titles, topic)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": (
                    f"For each YouTube video title below, reply true if it is "
                    f"related to the topic '{topic}', false if not.\n\n"
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

        # Pad or truncate to match title count
        while len(flags) < len(titles):
            flags.append(False)
        return flags[:len(titles)]

    except Exception as e:
        logger.warning(f"Claude classification failed ({e}) — keyword fallback")
        return _classify_keyword_fallback(titles, topic)


def classify_local(titles: list[str], topic: str, logger) -> list[bool]:
    """
    Classify titles using a local GGUF model via llama-cpp-python.
    Drop-in replacement for classify_claude.

    To use:
        pip install llama-cpp-python
        export LYTESNAP_CLASSIFIER=local
        export LYTESNAP_LOCAL_MODEL=models/qwen3-4b-q4_k_m.gguf
    """
    if not LOCAL_MODEL_PATH or not Path(LOCAL_MODEL_PATH).exists():
        logger.error(f"Local model not found: '{LOCAL_MODEL_PATH}'")
        return _classify_keyword_fallback(titles, topic)

    try:
        from llama_cpp import Llama

        # Cache model instance across calls in same process
        if not hasattr(classify_local, "_llm"):
            logger.info(f"Loading local model: {LOCAL_MODEL_PATH}")
            classify_local._llm = Llama(
                model_path=LOCAL_MODEL_PATH,
                n_ctx=4096,
                n_gpu_layers=-1,
                verbose=False,
            )
        llm = classify_local._llm

        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        prompt = (
            f"For each YouTube video title below, reply true if it is "
            f"related to the topic '{topic}', false if not.\n\n"
            f"{numbered}\n\n"
            "Reply with ONLY a JSON array of booleans (true/false), "
            "one per title in order. No explanation.\n"
        )

        response = llm(
            prompt,
            max_tokens=256,
            temperature=0.0,
        )

        raw = response["choices"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        flags = json.loads(raw.strip())

        while len(flags) < len(titles):
            flags.append(False)
        return flags[:len(titles)]

    except ImportError:
        logger.error("llama-cpp-python not installed: pip install llama-cpp-python")
        return _classify_keyword_fallback(titles, topic)
    except Exception as e:
        logger.warning(f"Local model failed ({e}) — keyword fallback")
        return _classify_keyword_fallback(titles, topic)


def _classify_keyword_fallback(titles: list[str], topic: str) -> list[bool]:
    """Last-resort keyword matching."""
    keywords = [w.lower() for w in topic.split() if len(w) > 3]
    return [any(k in t.lower() for k in keywords) for t in titles]


def classify(titles: list[str], topic: str, logger) -> list[bool]:
    """Route to configured classifier."""
    if CLASSIFIER == "local":
        return classify_local(titles, topic, logger)
    return classify_claude(titles, topic, logger)


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_feed(topic: str, verbose: bool = False) -> dict:
    """
    Open YouTube homepage, extract titles, classify, return score.

    Returns:
        {
            "score": float,    # 0.0 - 1.0, proportion matching topic
            "total": int,      # total videos scanned
            "matches": int,    # videos classified as matching
        }
    """
    logger = get_logger(verbose)

    if not _session_available(AUTH_FILE):
        logger.error(f"No stored session ({AUTH_FILE} or session.enc) — "
                     f"run: python engine/measure_feed.py auth --login")
        return {"score": 0.0, "total": 0, "matches": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context = browser.new_context(
            viewport=VIEWPORT,
            locale="en-US",
            storage_state=_load_storage_state(AUTH_FILE),
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
                    return {"score": 0.0, "total": 0, "matches": 0}

        # Wait for full render
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        time.sleep(2.0)

        # Dismiss popups (same selectors as flip_feed.py)
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

        # Extract
        titles = extract_homepage_titles(page, logger)

        if not titles:
            logger.error("No titles found — returning 0.0")
            browser.close()
            return {"score": 0.0, "total": 0, "matches": 0}

        # Classify
        logger.info(f"Classifying {len(titles)} titles against '{topic}' using {CLASSIFIER} ...")
        flags = classify(titles, topic, logger)

        matches = sum(1 for f in flags if f)
        total = len(titles)
        score = matches / total

        if verbose:
            print(f"\n{'='*60}")
            print(f"  Topic:      {topic}")
            print(f"  Classifier: {CLASSIFIER}")
            print(f"  Total:      {total}")
            print(f"  Matches:    {matches}")
            print(f"  Score:      {score:.4f} ({score*100:.1f}%)")
            print(f"{'='*60}")
            for i, (title, flag) in enumerate(zip(titles, flags)):
                marker = "[YES]" if flag else "[ - ]"
                print(f"  {marker} {i+1}. {title}")
            print()

        browser.close()

        return {
            "score": round(score, 4),
            "total": total,
            "matches": matches,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LYTESNAP — Score YouTube homepage against a target topic"
    )
    parser.add_argument("--topic", required=True, help="Target topic")
    parser.add_argument("--verbose", action="store_true", help="Detailed output")
    parser.add_argument("--output-json", action="store_true", help="Full JSON result")
    args = parser.parse_args()

    result = score_feed(args.topic, verbose=args.verbose)

    if args.output_json:
        result["topic"] = args.topic
        result["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        result["classifier"] = CLASSIFIER
        print(json.dumps(result, indent=2))
    else:
        # Single float — this is what autoresearch parses
        print(f"{result['score']:.4f}")


if __name__ == "__main__":
    main()