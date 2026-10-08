# LyteSnap AI — Claude Code Guide

## What this project is
YouTube feed reshaper: uses Playwright (Python) to simulate realistic human browsing and shift YouTube's recommendation algorithm toward a user-specified topic. The main script is `youtube_reshaper.py`.

## Key files
- `youtube_reshaper.py` — main script (~1000 lines)
- `config.json` — session configuration (topic, duration, video counts, watch percentages)
- `save_session.py` — one-time login tool, saves cookies to `auth.json`
- `.env` — contains `ANTHROPIC_API_KEY`
- `logs/session.log` — live session log
- `logs/feed_before.json` / `logs/feed_after.json` — homepage snapshots
- `logs/report.txt` — before/after feed classification report

## Running the script
```bash
# Kill any existing instance first
pkill -9 -f youtube_reshaper.py

# Start
nohup python3 youtube_reshaper.py > logs/session.log 2>&1 &

# Monitor
tail -f logs/session.log
```

## Always do before launching
1. `pkill -9 -f youtube_reshaper.py` — kill all existing instances
2. `python3 -m py_compile youtube_reshaper.py` — syntax check
3. Verify only one process after launch: `pgrep -f youtube_reshaper | wc -l`

## Auth
Handled by `engine/yt_auth.py`. Two stores, one of them authoritative:
- `chrome_profile/` — persistent Chrome user-data dir, **source of truth**. Cookies
  rotate in place here, the way a real browser works.
- `auth.json` — exported Playwright `storage_state` snapshot, kept in sync for the
  Electron app and the older scripts that still read it.

Session storage is handled by `engine/session_store.py`: `session.enc` (encrypted)
when enabled, `auth.json` (plaintext) otherwise. Backends: `dpapi` (Windows, OS
user is the key) and `aesgcm` (key from `LYTESNAP_SESSION_KEY`, for Linux/VM and
later a KMS).

```bash
python engine/measure_feed.py auth --check     # offline cookie health, no browser
python engine/measure_feed.py auth --live      # ask YouTube; refreshes the session
python engine/measure_feed.py auth --login     # sign in by hand (auto-detects)
python engine/measure_feed.py auth --migrate   # session -> persistent profile
python engine/measure_feed.py auth --encrypt   # auth.json -> session.enc
python engine/measure_feed.py auth --decrypt   # back to plaintext
python engine/measure_feed.py auth --selftest  # walk the whole chain, report each step
```

Every command takes `--data-dir` so several accounts can run on one machine, each
with its own session, profile and metrics. `config.json` falls back to the shared
project copy.

Rules learned the hard way:
- Google rotates `__Secure-1PSIDRTS`, `__Secure-3PSIDRTS`, `SIDCC`, `GPS` on nearly
  every visit. A context that is thrown away without exporting leaves `auth.json`
  behind Google's state; it decays until login breaks. Every phase now calls
  `yt_auth.export_state(..., verified=True)` before closing.
- `export_state` refuses to write unless the caller verified sign-in in that
  context. A **revoked** session still carries cookies named `SID`/`__Secure-1PSID`,
  so cookie names cannot distinguish live from dead — without the gate, an aborted
  signed-out run overwrites a good snapshot with a dead one.
- Never mint cookies under a spoofed user-agent and replay them under another.
  `setup_auth.py`/`save_session.py` used to claim macOS Chrome 124 while runs used
  real Windows Chrome.
- "A session file exists" ≠ signed in. `main.js` now reports what is STORED
  (`sessionStatus` in `lib/session-files.mjs`) and never claims `verified`; only
  the Python live check can confirm a session works.
- Sign-out deletes the encrypted session, the plaintext, their backups AND
  `chrome_profile/` — the profile caches the account's email in its service-worker
  cache, so removing only `auth.json` left the user's identity on disk.
- A signed-out feed is anonymous, not the account's, so any measurement taken from
  it is void. `measure_feed.py` aborts instead of scoring it.
- `auth.json`, `session.enc` and `chrome_profile/` must never be committed.
- `score_feed.py` is the frozen measurement function. Its auth-loading lines were
  changed (encrypted store support) and nothing else — no selector, prompt,
  scoring or classifier change, so measurements stay comparable.

## Architecture
- Claude Haiku (`claude-haiku-4-5-20251001`) for subtopic generation and title classification
- Sidebar chaining: 2-3 levels deep via `#secondary yt-lockup-view-model`
- Autoplay chain: seek to `duration - 5`, call `v.play()`, wait 5-8s for natural end
- Homepage matching: every `go_home()` call watches matching videos before searching
- 50/50 post-watch strategy: autoplay chain vs sidebar navigation
- Feed match rate logged on every homepage visit via `[Homepage] X/Y (Z%)`

## Key DOM selectors (as of 2026)
- Homepage cards: `ytd-rich-item-renderer h3 a`
- Search results: `ytd-video-renderer`
- Sidebar cards: `#secondary yt-lockup-view-model`
- Autoplay toggle: `.ytp-autonav-toggle-button`

## Config options (config.json)
| Key | Description |
|-----|-------------|
| `main_topic` | Primary topic to reshape toward |
| `num_subtopics` | Number of Claude-generated subtopics |
| `session_duration_minutes` | Total session length |
| `videos_per_topic` | Videos to watch per subtopic |
| `max_homepage_watches_per_cycle` | Max homepage videos to watch per visit |
| `watch_pct_min/max` | % of video to watch (0.85–0.95) |
| `watch_cap_seconds` | Max watch time per video (600s) |
