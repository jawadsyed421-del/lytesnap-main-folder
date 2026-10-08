# LYTESNAP Autoresearch: YouTube Feed Reshaping Strategy Optimization

## Goal

Optimize the YouTube feed reshaping script to maximize **weighted topic match score** — a position-weighted proportion of homepage videos matching the target topic, where position 1 carries the most weight and position N the least (linear decay). The primary metric comes from running `score_feed_weighted.py`. The unweighted `score_feed.py` is kept for backward compatibility but is no longer the primary metric.

## The Loop

1. Read `experiment_log.csv` and `best_score.txt` to understand what has and hasn't worked
2. Propose ONE change — either a `config.json` parameter OR a behavioral change to `youtube_reshaper.py` (not both unless tightly coupled)
3. Apply the change
4. Score the feed BEFORE the session: `python score_feed_weighted.py --topic "<main_topic>" --output-json` → save as `before_score`
5. Run a session: `python youtube_reshaper.py`
6. Score the feed AFTER: `python score_feed_weighted.py --topic "<main_topic>" --output-json` → save as `after_score`
7. If `after_score` > `best_score.txt` → **keep** the change, update `best_score.txt`
8. If not → **revert** the change (restore previous `config.json` and/or `youtube_reshaper.py`)
9. Append a row to `experiment_log.csv`
10. Rotate `main_topic` / `narrow_topics` to the next pair in the topic rotation table
11. Repeat indefinitely

## Modifying youtube_reshaper.py

You are allowed and encouraged to modify `/Users/jasonngo/Documents/lytesnap-ai/youtube_reshaper.py` as part of the autoresearch loop. Treat it as a first-class experiment variable alongside `config.json`.

### Things you can change in youtube_reshaper.py

- **`LONG_VIDEO_THRESHOLD`** — currently 15min. Try 10min or 20min.
- **Sidebar depth in search fallback** — currently fixed at 1. Try 0 (skip entirely) or 2.
- **Homepage sample size in `get_homepage_matches`** — currently 10 cards. Try 15 or 20.
- **Post-search strategy ratio** — currently 50/50 autoplay/sidebar. Try 80/20 or 100% sidebar.
- **Per-cycle time budget** — add a max time per homepage match (e.g. skip remaining matches if cycle exceeds X minutes) to guarantee multiple cycles per session.
- **Watch behavior** — e.g. occasional scroll to comments during watch, mouse movement to simulate engagement.
- **Subtopic generation prompt** — change the Claude prompt in `generate_subtopics()` to produce different query styles (broader, narrower, question-format, etc.).
- **Homepage scroll depth** — currently 3 scrolls before classification. Try 5 or 2.
- **Sidebar wait time** — currently `human_sleep(10, 13)` before scanning sidebar. Try shorter (5-8s).

### Rules when modifying youtube_reshaper.py

- Always run `python3 -m py_compile youtube_reshaper.py` after any edit — do not run a broken script
- Never modify `save_session.py`
- Never add social actions (like, comment, subscribe, share)
- Never navigate outside youtube.com
- Never run headless
- Never remove timing jitter from any action (detection risk)
- Never reduce minimum action delay below 300ms
- Keep `--disable-blink-features=AutomationControlled` intact
- One variable at a time — if you change sidebar depth, don't also change watch_pct

## Topic Rotation

Each experiment uses a **main topic** (broad — used for homepage scoring) and a **narrow_topics list** (2-3 specific topics — used for subtopic generation and search, interleaved). Rotate through these pairs. Never use the same main_topic twice in a row.

| main_topic   | narrow_topics                                      |
|--------------|----------------------------------------------------|
| Republican   | ["Donald Trump", "MAGA movement", "GOP Senate"]    |
| Democrat     | ["AOC", "Bernie Sanders", "Elizabeth Warren"]      |
| Immigration  | ["US border policy", "DACA", "ICE enforcement"]    |
| Gun rights   | ["Second Amendment", "NRA", "gun control debate"]  |
| Religion     | ["Christian faith", "evangelical politics", "megachurch"] |
| Fitness      | ["weight loss", "gym motivation", "bodybuilding"]  |
| Finance      | ["stock market", "index funds", "personal finance"]|
| Sports       | ["NFL football", "NBA highlights", "sports betting"]|

### How narrow_topics works

- Claude generates `num_subtopics` search phrases for **each** narrow topic
- Subtopics are **interleaved** across all narrow topics before being used in search
- Example with `["AOC", "Bernie Sanders", "Elizabeth Warren"]` and `num_subtopics=8`: produces 24 total subtopics, cycling AOC → Bernie → Warren → AOC → Bernie → Warren...
- In `config.json`, always use the `narrow_topics` key (list), never the old `narrow_topic` key (string)

## Config Reference (config.json)

| Key | Description | Current Best |
|-----|-------------|-------------|
| `main_topic` | Broad topic — homepage classification and scoring | "Republican" |
| `narrow_topics` | List of 2-3 specific topics — subtopic generation and search, interleaved | ["Donald Trump", "MAGA movement", "GOP Senate"] |
| `num_subtopics` | Claude-generated subtopics for search | 8 |
| `session_duration_minutes` | Total session length | 30 |
| `videos_per_topic` | Videos to watch per subtopic search | 4 |
| `max_homepage_watches_per_cycle` | Max homepage matches to rabbit-hole per cycle | 10 |
| `homepage_rabbit_hole_depth` | Sidebar depth from each homepage match | 2 |
| `watch_pct_min` / `watch_pct_max` | % of video to watch | 0.85–0.95 |

## Architecture (as of exp18+)

### Homepage-First Loop
Every cycle:
1. Go to homepage
2. Classify up to 10 cards with Claude against `main_topic`
3. **If matches exist**: click each match → watch it → sidebar rabbit hole (`homepage_rabbit_hole_depth` levels deep) → return to homepage
4. **If no matches**: search a `narrow_topic` subtopic → watch `videos_per_topic` videos → sidebar depth=1 per video

### Subtopic Generation
Claude Haiku generates `num_subtopics` search phrases from `narrow_topic`. These are used exclusively in search (fallback path). Homepage matching uses `main_topic`.

### Sidebar Dedup
Seen hrefs are tracked within a sidebar chain — the script will never re-watch the same video at consecutive levels.

### Post-Search Strategy (fallback only)
50/50 split: autoplay chain (depth=1) vs sidebar navigation (depth=1). Deeper chains are reserved for homepage rabbit holes.

### Autoplay
Autoplay is turned OFF on every video via `ensure_autoplay_off()`. The autoplay chain logic (`accept_autoplay_chain`) still exists in code but is not the primary strategy — sidebar carries the load.

## Experiment Log Format

After each experiment, append a row to `experiment_log.csv`:

```
timestamp,main_topic,narrow_topics,before_score,after_score,delta,kept,description
```

- `main_topic` = broad topic from config
- `narrow_topics` = comma-separated list of narrow topics used
- `before_score` = score_feed.py run BEFORE the session
- `score` = score_feed.py run AFTER the session
- `kept` = true if after_score > best_score.txt, false otherwise
- `description` = what changed and why

## Confirmed Optimal Settings (17 experiments through exp17)

- `num_subtopics=8` (4 hurts −9.5%, 12 no gain)
- `videos_per_topic=4` (2 and 6 both worse)
- `watch_pct=0.85-0.95` (sweet spot — 0.3-0.5 much worse, 0.95-1.0 also worse)
- `session_duration=30min` (45min no gain, diminishing returns real)
- `max_homepage_watches=10` (homepage is main priority — higher is better now that architecture is homepage-first)
- `homepage_rabbit_hole_depth=2` (3 consumes full session on a single chain)
- Sidebar depth=1 for search fallback (deep chains from search kill homepage cycle frequency)
- 50/50 autoplay/sidebar in search fallback
- Noun-phrase subtopics (question-format underperformed)
- Long video threshold=30min (bounce at 8-12s above that)

## Key Insights

- **Homepage confirmation dominates.** Watching a video YouTube already recommended is a stronger signal than finding one via search.
- **Warm feed compounds.** Best score (0.4286) came from a warm starting feed (before=0.2857). Multiple sessions on the same topic stack gains significantly.
- **Viral/political topics move faster.** Republican/Donald Trump hit 28.6%→48.0% in a single cold session — far faster than niche topics.
- **main/narrow split matters.** Broad `main_topic` for scoring catches related content (Giuliani, election) that a narrow classifier misses. Narrow `narrow_topic` for search keeps queries focused.
- **Autoplay never fires reliably.** Seek+play() doesn't trigger YouTube's autoplay countdown. Not worth debugging — sidebar carries the load.

## What You Can Still Modify

### config.json parameters
- `session_duration_minutes` — confirmed 30min optimal, but test with warm feeds
- `homepage_rabbit_hole_depth` — currently 2; test 1 vs 3 on warm feeds
- `max_homepage_watches_per_cycle` — currently 10; test higher on warm feeds where homepage always matches
- `watch_pct_min/max` — confirmed 0.85-0.95 optimal

### Strategy logic
- **Sidebar depth in search fallback** — currently fixed 1; try 0 (skip sidebar on search entirely)
- **Homepage sample size** — currently 10 cards; try 15 or 20
- **Search fallback behavior** — try skipping sidebar entirely on search (pure search → homepage loop)
- **Session chaining** — run 2-3 sessions back-to-back on same topic; warm feed compounding is the biggest untested lever

## What You CANNOT Modify

- **DO NOT** modify `save_session.py` or `auth.json`
- **DO NOT** modify `save_session.py` or `auth.json`
- **DO NOT** add commenting, posting, sharing, or social engagement
- **DO NOT** add liking or subscribing
- **DO NOT** navigate outside youtube.com
- **DO NOT** interact with ads beyond skipping them
- **DO NOT** click purchase or payment flows
- **DO NOT** reduce minimum action pause below 300ms (detection risk)
- **DO NOT** remove random jitter from any timing (detection risk)
- **DO NOT** run in headless mode (detection risk)
- **DO NOT** modify the `--disable-blink-features=AutomationControlled` browser flag

## File Structure

```
lytesnap-ai/
├── program.md                  # This file
├── config.json                 # Session configuration (YOU EDIT THIS)
├── youtube_reshaper.py         # Feed reshaping script (YOU EDIT THIS)
├── score_feed.py               # Unweighted scorer (modifiable)
├── score_feed_weighted.py      # Primary metric — linear position decay (YOU CAN READ, do not modify score_feed.py)
├── save_session.py             # Login helper (read-only)
├── auth.json                   # Saved browser session (read-only)
├── .env                        # ANTHROPIC_API_KEY (read-only)
├── best_score.txt              # Current best score (auto-updated)
├── experiment_log.csv          # Log of all experiments (auto-appended)
├── logs/                       # Session logs
├── recordings/                 # Playwright video recordings (gitignored)
└── reports/                    # Before/after reports
```
