#!/usr/bin/env bash
# F163 ground-station smoke test.
# Starts the server, runs the simulator in auto mode for ~15 s, then checks
# the REST API: a session exists, a KPI query reports lap_count >= 1 and
# telemetry_rows > 100. Prints PASS/FAIL and cleans up processes.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv"
PY="$VENV/bin/python"
HOST="127.0.0.1"
# Override when 8000 is taken, e.g. by a server you are already running.
PORT="${F163_SMOKE_PORT:-8000}"
BASE="http://$HOST:$PORT"
DB_PATH="$REPO_ROOT/data/smoke.db"

SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
  fi
}
trap cleanup EXIT

fail() {
  echo "FAIL: $1"
  exit 1
}

# 1. Ensure venv exists.
if [ ! -x "$PY" ]; then
  echo "Creating virtualenv..."
  python3 -m venv "$VENV" || fail "venv creation failed"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$REPO_ROOT/requirements.txt" || fail "pip install failed"
fi

# Fresh DB for a deterministic smoke run.
rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm" "$DB_PATH-journal"

# 2. Start the server.
echo "Starting server..."
F163_DB_PATH="$DB_PATH" "$PY" -m uvicorn server.app.main:app \
  --host "$HOST" --port "$PORT" --log-level warning &
SERVER_PID=$!

# Wait for health.
READY=0
for _ in $(seq 1 50); do
  if curl -fs "$BASE/api/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.2
done
[ "$READY" -eq 1 ] || fail "server did not become healthy"
echo "Server healthy."

# 3. Run the simulator in auto mode for 15 s. The first lap, from a standing
# start, takes about 9 s and only counts once the car has been all the way round.
echo "Running simulator (auto, 15 s)..."
"$PY" -m sim.car --mode auto --duration 15 \
  --server "ws://$HOST:$PORT/ws/car" --car-id car-smoke || fail "simulator exited non-zero"

# Give the server a moment to flush the final telemetry batch.
sleep 1.5

# 4. Query sessions.
SESSIONS_JSON="$(curl -fs "$BASE/api/sessions")" || fail "GET /api/sessions failed"
echo "Sessions: $SESSIONS_JSON"
SESSION_ID="$("$PY" - "$SESSIONS_JSON" <<'PYEOF'
import json, sys
data = json.loads(sys.argv[1])
if not data:
    print("")
else:
    print(data[0]["id"])
PYEOF
)"
[ -n "$SESSION_ID" ] || fail "no session created"
echo "Newest session id: $SESSION_ID"

# 5. Query KPIs and assert.
KPIS_JSON="$(curl -fs "$BASE/api/sessions/$SESSION_ID/kpis")" || fail "GET kpis failed"
echo "KPIs: $KPIS_JSON"

"$PY" - "$KPIS_JSON" <<'PYEOF' || exit 1
import json, sys
k = json.loads(sys.argv[1])
lap_count = k.get("lap_count", 0)
telemetry_rows = k.get("telemetry_rows", 0)
print(f"lap_count={lap_count} telemetry_rows={telemetry_rows}")
ok = True
if lap_count < 1:
    print(f"FAIL: lap_count {lap_count} < 1")
    ok = False
if telemetry_rows <= 100:
    print(f"FAIL: telemetry_rows {telemetry_rows} <= 100")
    ok = False
sys.exit(0 if ok else 1)
PYEOF

echo "PASS"
exit 0
