#!/bin/bash
# run_experiments.sh — 10 overnight experiments, one variable at a time.
# Rotates through config changes and topics, scores before/after each run,
# logs to experiment_log.csv, and reverts config if score doesn't beat best.

set -o pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

LOG="metrics/experiment_log.csv"
BEST_FILE="metrics/best_score.txt"
PYTHON=".venv/bin/python3"

# Ensure CSV header
if [ ! -f "$LOG" ] || [ ! -s "$LOG" ]; then
  echo "timestamp,main_topic,narrow_topics,before_score,after_score,delta,kept,description" > "$LOG"
fi

# ── helpers ──────────────────────────────────────────────────────────────────

score_feed() {
  local topic="$1"
  $PYTHON engine/score_feed_weighted.py --topic "$topic" --output-json 2>/dev/null | $PYTHON -c "
import sys, json
try:
    print(json.loads(sys.stdin.read().strip())['weighted_score'])
except:
    print('0.0')
" || echo "0.0"
}

get_best() {
  cat "$BEST_FILE" 2>/dev/null || echo "0.0"
}

set_config() {
  # set_config <main_topic> <narrow_topics_json> [key=value ...]
  # Uses python3 -c to safely patch config.json without heredoc quoting issues.
  local main_topic="$1"
  local narrow_json="$2"
  shift 2
  $PYTHON -c "
import json, sys
c = json.load(open('config.json'))
c['main_topic'] = sys.argv[1]
c['narrow_topics'] = json.loads(sys.argv[2])
for kv in sys.argv[3:]:
    k, _, v = kv.partition('=')
    try:
        c[k.strip()] = json.loads(v.strip())
    except:
        c[k.strip()] = v.strip()
json.dump(c, open('config.json', 'w'), indent=2)
" "$main_topic" "$narrow_json" "$@"
}

revert_config_keys() {
  # Restore specific keys from backup, keep main_topic/narrow_topics
  $PYTHON -c "
import json, sys
backup = json.load(open('config.json.bak'))
current = json.load(open('config.json'))
for kv in sys.argv[1:]:
    k = kv.partition('=')[0].strip()
    if k in backup:
        current[k] = backup[k]
json.dump(current, open('config.json', 'w'), indent=2)
" "$@"
}

flush_to_democrat() {
  echo "[Flush] Running Democrat session to cold-start Republican feed..."
  set_config "Democrat" '["AOC","Bernie Sanders","Elizabeth Warren"]'
  pkill -9 -f youtube_reshaper.py 2>/dev/null
  $PYTHON engine/youtube_reshaper.py > logs/flush_democrat.log 2>&1
  echo "[Flush] Done. Republican score now: $(score_feed "Republican")"
}

run_experiment() {
  local exp_num="$1"
  local main_topic="$2"
  local narrow_json="$3"
  local description="$4"
  shift 4
  # Remaining args are key=value config patches (e.g. "cycle_budget_seconds=600")

  echo ""
  echo "════════════════════════════════════════"
  echo "  Exp $exp_num / 10 — $description"
  echo "  main_topic:    $main_topic"
  echo "  narrow_topics: $narrow_json"
  echo "════════════════════════════════════════"

  cp config.json config.json.bak
  set_config "$main_topic" "$narrow_json" "$@"

  echo "[Score] Before..."
  BEFORE=$(score_feed "$main_topic")
  echo "[Score] Before: $BEFORE"

  pkill -9 -f youtube_reshaper.py 2>/dev/null
  $PYTHON engine/youtube_reshaper.py > "logs/exp${exp_num}.log" 2>&1
  echo "[Session] Exp $exp_num complete."

  echo "[Score] After..."
  AFTER=$(score_feed "$main_topic")
  DELTA=$($PYTHON -c "print(round($AFTER - $BEFORE, 4))")
  TS=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[Score] After: $AFTER  Delta: $DELTA"

  BEST=$(get_best)
  KEPT="false"
  if $PYTHON -c "import sys; sys.exit(0 if float('$AFTER') > float('$BEST') else 1)"; then
    echo "$AFTER" > "$BEST_FILE"
    KEPT="true"
    echo "[Best] New best: $AFTER (was $BEST)"
  fi

  # Revert extra config keys if not kept and a patch was applied
  if [ "$KEPT" = "false" ] && [ "$#" -gt 0 ]; then
    revert_config_keys "$@"
    echo "[Revert] Config params reverted to baseline."
  fi

  NARROW_CSV=$($PYTHON -c "import json,sys; print(','.join(json.loads(sys.argv[1])))" "$narrow_json")
  echo "$TS,$main_topic,\"$NARROW_CSV\",$BEFORE,$AFTER,$DELTA,$KEPT,$description" >> "$LOG"

  rm -f config.json.bak
}

# ── Experiment definitions ────────────────────────────────────────────────────

# Exp 1: cycle_budget=600 (3 cycles/session) — Republican cold start
flush_to_democrat
run_experiment 1 "Republican" '["Donald Trump","MAGA movement","GOP Senate"]' \
  "cycle_budget=600 — 3 cycles/session cold start" \
  "cycle_budget_seconds=600"

# Exp 2: homepage_sample_size=15 — Republican cold start
flush_to_democrat
run_experiment 2 "Republican" '["Donald Trump","MAGA movement","GOP Senate"]' \
  "homepage_sample_size=15 — classify 15 cards vs 10 cold start" \
  "homepage_sample_size=15"

# Exp 3: search_sidebar_depth=0 — Republican cold start
flush_to_democrat
run_experiment 3 "Republican" '["Donald Trump","MAGA movement","GOP Senate"]' \
  "search_sidebar_depth=0 — skip sidebar on search fallback cold start" \
  "search_sidebar_depth=0"

# Exp 4: homepage_rabbit_hole_depth=1 — Republican cold start
flush_to_democrat
run_experiment 4 "Republican" '["Donald Trump","MAGA movement","GOP Senate"]' \
  "homepage_rabbit_hole_depth=1 — shallower rabbit hole cold start" \
  "homepage_rabbit_hole_depth=1"

# Exp 5: Immigration cold start
run_experiment 5 "Immigration" '["US border policy","DACA","ICE enforcement"]' \
  "Immigration cold start — keyword narrow topics"

# Exp 6: Gun rights cold start
run_experiment 6 "Gun rights" '["Second Amendment","NRA","gun control debate"]' \
  "Gun rights cold start — keyword narrow topics"

# Exp 7: Religion cold start
run_experiment 7 "Religion" '["Christian faith","evangelical politics","megachurch"]' \
  "Religion cold start — keyword narrow topics"

# Exp 8: Democrat cold start
run_experiment 8 "Democrat" '["AOC","Bernie Sanders","Elizabeth Warren"]' \
  "Democrat cold start — 3 narrow topics"

# Exp 9: Finance cold start
run_experiment 9 "Finance" '["stock market","index funds","personal finance"]' \
  "Finance cold start — keyword narrow topics"

# Exp 10: Sports cold start
run_experiment 10 "Sports" '["NFL football","NBA highlights","sports betting"]' \
  "Sports cold start — keyword narrow topics"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "  All 10 experiments complete."
echo "  Best score: $(get_best)"
echo "  Results in experiment_log.csv"
echo "════════════════════════════════════════"

# Restore Republican as default
set_config "Republican" '["Donald Trump","MAGA movement","GOP Senate"]'
echo "Config reset to Republican."
