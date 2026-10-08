# LyteSnap AI

A YouTube feed reshaper that uses browser automation to shift YouTube's recommendation algorithm toward topics you choose — and away from ones you don't.

## How it works

LyteSnap simulates realistic human browsing sessions using Playwright to train YouTube's recommendation engine. It runs a 7-day phased treatment protocol:

- **Days 1–3 (Intensive):** Sessions every ~3 hours
- **Days 4–7 (Maintenance):** One session per day
- **Day 8+:** Protocol stops automatically

### Two phases

- **Phase 1 — Unaddict:** Floods the feed with topics you find boring or off-putting. Makes the feed unappealing so you put the phone down.
- **Phase 2 — Enjoy:** Fills the feed with content you actually want to watch. Builds new habits naturally.

## Tech stack

- **Electron** — Desktop app shell
- **React** — UI
- **Playwright (Python)** — Browser automation
- **Claude Haiku** — Subtopic generation and feed classification

## Setup

1. Install dependencies:
   ```bash
   npm install
   pip install -r requirements.txt
   playwright install chromium
   ```

2. Add your Anthropic API key to `.env`:
   ```
   ANTHROPIC_API_KEY=sk-...
   ```

3. Log in to YouTube and save the session:
   ```bash
   python engine/setup_auth.py
   ```

4. Run the app:
   ```bash
   npm start
   ```

## Configuration

Edit `config.json` to tune session behavior:

| Key | Description |
|-----|-------------|
| `session_duration_minutes` | Total session length (default: 45) |
| `max_homepage_watches_per_cycle` | Homepage videos watched per visit |
| `watch_pct_min/max` | Fraction of each video to watch |
| `watch_cap_seconds` | Max watch time per video |

## Notes

- `auth.json` stores your YouTube session cookies — keep it out of version control
- Scheduled sessions only run while the Electron app is open
- Running logs are stored in `running_logs/` (gitignored)
