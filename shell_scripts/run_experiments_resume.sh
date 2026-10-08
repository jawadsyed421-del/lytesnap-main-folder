#!/bin/bash
# run_experiments_resume.sh — Resume from exp 5 (exps 1-4 already complete).

set -o pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

LOG="metrics/experiment_log.csv"
BEST_FILE="metrics/best_score.txt"
PYTHON=".venv/bin/python3"

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

run_experiment() {
  local exp_num="$1"
  local main_topic="$2"
  local narrow_json="$3"
  local description="$4"
  shift 4

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

  if [ "$KEPT" = "false" ] && [ "$#" -gt 0 ]; then
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
    echo "[Revert] Config params reverted to baseline."
  fi

  NARROW_CSV=$($PYTHON -c "import json,sys; print(','.join(json.loads(sys.argv[1])))" "$narrow_json")
  echo "$TS,$main_topic,\"$NARROW_CSV\",$BEFORE,$AFTER,$DELTA,$KEPT,$description" >> "$LOG"

  rm -f config.json.bak
}

# ── Resume from Exp 5 ─────────────────────────────────────────────────────────

run_experiment 5 "Immigration" '["US border policy","DACA","ICE enforcement"]' \
  "Immigration cold start — keyword narrow topics"

run_experiment 6 "Gun rights" '["Second Amendment","NRA","gun control debate"]' \
  "Gun rights cold start — keyword narrow topics"

run_experiment 7 "Religion" '["Christian faith","evangelical politics","megachurch"]' \
  "Religion cold start — keyword narrow topics"

run_experiment 8 "Democrat" '["AOC","Bernie Sanders","Elizabeth Warren"]' \
  "Democrat cold start — 3 narrow topics"

run_experiment 9 "Finance" '["stock market","index funds","personal finance"]' \
  "Finance cold start — keyword narrow topics"

run_experiment 10 "Sports" '["NFL football","NBA highlights","sports betting"]' \
  "Sports cold start — keyword narrow topics"

echo ""
echo "════════════════════════════════════════"
echo "  Exps 5-10 complete."
echo "  Best score: $(get_best)"
echo "  Results in experiment_log.csv"
echo "════════════════════════════════════════"

set_config "Republican" '["Donald Trump","MAGA movement","GOP Senate"]'
echo "Config reset to Republican."
