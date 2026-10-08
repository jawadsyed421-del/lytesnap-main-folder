#!/bin/bash
# Phased treatment schedule:
#   Days 0-2  (intensive):   run every 3 hours
#   Days 3-6  (maintenance): run once per day
#   Day 7+    (complete):    unload schedule and stop

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python3"
RESHAPER="$ROOT_DIR/engine/youtube_reshaper.py"
LOGS_DIR="$ROOT_DIR/running_logs"
STATE_FILE="$ROOT_DIR/schedules/schedule_state.json"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.lytesnap.plist"

if [ ! -f "$STATE_FILE" ]; then
  echo "[lytesnap] No schedule state — exiting"
  exit 0
fi

TODAY=$(date +"%Y-%m-%d")

DAYS_ELAPSED=$("$PYTHON" -c "
import json, sys
from datetime import date
with open('$STATE_FILE') as f: d = json.load(f)
start = date.fromisoformat(d['startDate'])
print((date.today() - start).days)
")

# Day 7+: treatment complete — unload and stop
if [ "$DAYS_ELAPSED" -ge 7 ]; then
  echo "[lytesnap] Treatment complete (day $DAYS_ELAPSED) — stopping schedule"
  launchctl unload "$LAUNCH_AGENT" 2>/dev/null
  exit 0
fi

# Days 3-6: maintenance — run at most once per day
if [ "$DAYS_ELAPSED" -ge 3 ]; then
  LAST_RUN=$("$PYTHON" -c "
import json
with open('$STATE_FILE') as f: d = json.load(f)
print(d.get('lastRunDate', ''))
")
  if [ "$LAST_RUN" = "$TODAY" ]; then
    echo "[lytesnap] Maintenance phase: already ran today — skipping"
    exit 0
  fi
fi

# Update lastRunDate before sleeping so concurrent launches can't double-fire
"$PYTHON" -c "
import json
with open('$STATE_FILE') as f: d = json.load(f)
d['lastRunDate'] = '$TODAY'
with open('$STATE_FILE', 'w') as f: json.dump(d, f, indent=2)
"

# Random jitter: 1–5 minutes
DELAY=$((60 + RANDOM % 241))
PHASE=$( [ "$DAYS_ELAPSED" -lt 3 ] && echo "intensive" || echo "maintenance" )
echo "[lytesnap] Day $DAYS_ELAPSED ($PHASE) — waiting ${DELAY}s then starting session"
sleep "$DELAY"

TS=$(date +"%Y-%m-%dT%H-%M-%S")
RUN_DIR="$LOGS_DIR/$TS"
mkdir -p "$RUN_DIR"

echo "[lytesnap] Starting session at $TS"
"$PYTHON" "$RESHAPER" --run-dir "$RUN_DIR" >> "$RUN_DIR/session.log" 2>&1
