#!/bin/bash
# run_sessions.sh — Run 3 reshaping sessions with 30min gaps, scoring between each.

set -o pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
PYTHON=".venv/bin/python3"

TOPIC=$($PYTHON -c "import json; c=json.load(open('config.json')); print(c['main_topic'])")
NARROW=$($PYTHON -c "import json; c=json.load(open('config.json')); v=c.get('narrow_topics', c.get('narrow_topic', c['main_topic'])); print(','.join(v) if isinstance(v,list) else v)")
LOG="metrics/experiment_log.csv"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "========================================"
echo "  LyteSnap — 3-Session Reinforcement Run"
echo "  main_topic:   $TOPIC"
echo "  narrow_topic: $NARROW"
echo "  Started:      $TIMESTAMP"
echo "========================================"

# Ensure CSV header exists
if [ ! -f "$LOG" ]; then
  echo "timestamp,main_topic,narrow_topic,before_score,after_score,delta,description" > "$LOG"
fi

# Helper to score feed, returns 0.0 on failure
score_feed() {
  $PYTHON engine/score_feed_weighted.py --topic "$TOPIC" --output-json 2>/dev/null | $PYTHON -c "
import sys, json
data = sys.stdin.read().strip()
try:
    print(json.loads(data)['weighted_score'])
except:
    print('0.0')
" || echo "0.0"
}

# --- Before score ---
echo ""
echo "[Score] Measuring baseline before session 1..."
BEFORE=$(score_feed)
echo "[Score] Baseline: $BEFORE"

for SESSION in 1 2 3; do
  echo ""
  echo "========================================"
  echo "  Session $SESSION / 3"
  echo "========================================"

  # Run session
  $PYTHON engine/youtube_reshaper.py > logs/session_${SESSION}.log 2>&1
  echo "[Session $SESSION] Complete."

  # Score after
  echo "[Score] Measuring after session $SESSION..."
  AFTER=$(score_feed)
  DELTA=$($PYTHON -c "print(round($AFTER - $BEFORE, 4))")
  TS=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[Score] Session $SESSION — before=$BEFORE after=$AFTER delta=$DELTA"

  # Log to CSV
  echo "$TS,$TOPIC,$NARROW,$BEFORE,$AFTER,$DELTA,reinforcement_session_${SESSION}_of_3" >> "$LOG"

  # Update before for next session delta
  BEFORE=$AFTER

  # Update best_score if improved
  BEST=$(cat metrics/best_score.txt 2>/dev/null || echo "0.0")
  IS_BEST=$($PYTHON -c "print('yes' if $AFTER > $BEST else 'no')")
  if [ "$IS_BEST" = "yes" ]; then
    echo "$AFTER" > metrics/best_score.txt
    echo "[Best] New best score: $AFTER"
  fi

  # Wait 30 min between sessions (skip after last)
  if [ $SESSION -lt 3 ]; then
    echo ""
    echo "[Wait] Pausing 30 minutes before session $((SESSION + 1))..."
    sleep 1800
    echo "[Wait] Done."
  fi
done

echo ""
echo "========================================"
echo "  All 3 sessions complete."
echo "  Final score: $AFTER"
echo "  Check experiment_log.csv for full curve."
echo "========================================"
