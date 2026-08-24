#!/usr/bin/env bash
# Single-point process manager for the full rune stack, run from the UI
# repo: this app's own Next.js dev server, the rune-registry backend API
# (a separate repo/codebase — see RUNE_BACKEND_DIR below), and the
# standalone rune-guardrails service (also separate — see
# RUNE_GUARDRAILS_DIR below), started/stopped together.
#
#   ./run.sh            start all three (no-op for whichever is already running)
#   ./run.sh start
#   ./run.sh stop        (no-op for whichever isn't running)
#   ./run.sh restart
#   ./run.sh status
#   ./run.sh logs [api|web|guardrails]   tail one service's log (default: web)
#
# No service is invoked through its package-manager wrapper (`uv run
# runectl`, `npm run dev`) — wrappers fork a child and return immediately,
# so `$!` would capture the wrapper's PID rather than the actual server's,
# breaking stop/restart. Invoking each venv/node_modules entry point
# directly makes `$!` the real process, which installs its own SIGTERM
# handler for graceful shutdown either way.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUN_DIR="$SCRIPT_DIR/.run"
NEXT_BIN="$SCRIPT_DIR/node_modules/.bin/next"

# The backend and guardrails service are genuinely separate codebases
# (their own repos, own dependency managers, own deploys) — this is only a
# local-dev convenience for running the whole stack together from here.
# Both default to sibling checkouts; override if yours live elsewhere, or
# skip starting one by setting its DIR var to "".
BACKEND_DIR="${RUNE_BACKEND_DIR-$SCRIPT_DIR/../rune_skills}"
RUNECTL="$BACKEND_DIR/.venv/bin/runectl"
GUARDRAILS_DIR="${RUNE_GUARDRAILS_DIR-$SCRIPT_DIR/../rune_guardrail}"
GUARDRAILS_BIN="$GUARDRAILS_DIR/.venv/bin/rune-guardrails"

WEB_HOST="${RUNE_WEB_HOST:-0.0.0.0}"
WEB_PORT="${RUNE_WEB_PORT:-3027}"
API_HOST="${RUNE_HOST:-127.0.0.1}"
API_PORT="${RUNE_PORT:-8027}"
GUARDRAILS_HOST="${RUNE_GUARDRAILS_HOST:-127.0.0.1}"
GUARDRAILS_PORT="${RUNE_GUARDRAILS_PORT:-8028}"
STOP_TIMEOUT="${RUNE_STOP_TIMEOUT:-15}"   # seconds to wait for graceful shutdown before SIGKILL

# The API talks to the guardrails service over HTTP only — never
# in-process. Point it at the instance this script manages unless already
# overridden.
export RUNE_GUARDRAILS_SERVICE_URL="${RUNE_GUARDRAILS_SERVICE_URL:-http://$GUARDRAILS_HOST:$GUARDRAILS_PORT}"

# Falls back to AUTH_GOOGLE_ID from THIS repo's own .env.local — no longer
# a cross-repo file reach-in, since run.sh and .env.local now live
# together — so the backend validates Google sign-in tokens against the
# same dedicated OAuth client this app uses, without copy-pasting the
# client id a second time. RUNE_GOOGLE_CLIENT_ID (if already set) always
# wins.
if [ -z "${RUNE_GOOGLE_CLIENT_ID:-}" ] && [ -n "${AUTH_GOOGLE_ID:-}" ]; then
    RUNE_GOOGLE_CLIENT_ID="$AUTH_GOOGLE_ID"
elif [ -z "${RUNE_GOOGLE_CLIENT_ID:-}" ] && [ -f "$SCRIPT_DIR/.env.local" ]; then
    RUNE_GOOGLE_CLIENT_ID="$(sed -n 's/^AUTH_GOOGLE_ID=//p' "$SCRIPT_DIR/.env.local" | tail -1)"
fi
export RUNE_GOOGLE_CLIENT_ID="${RUNE_GOOGLE_CLIENT_ID:-}"

mkdir -p "$RUN_DIR"

usage() {
    cat <<EOF
Usage: $(basename "$0") [start|stop|restart|status|logs [api|web|guardrails]]

  (no argument)  same as "start"
  start          start all services in the background (no-op if already running)
  stop           stop all services (no-op if not running)
  restart        stop, then start
  status         show whether each service is running
  logs [api|web|guardrails]  tail one service's log file (default: web)

Environment overrides:
  RUNE_BACKEND_DIR   path to the rune-registry backend repo (default:
                     ../rune_skills, a sibling checkout). Set to "" to skip
                     starting the api — see also RUNE_API_URL in .env.local.
  RUNE_GUARDRAILS_DIR   path to the standalone rune-guardrails service repo
                        (default: ../rune_guardrail, a sibling checkout).
                        Set to "" to skip starting it — the API degrades
                        gracefully (503 only on the specific routes that
                        need it) rather than failing to start.
  RUNE_WEB_HOST      network interface(s) to bind (default 0.0.0.0 — Next's
                     own default, covers 127.0.0.1). This is independent of
                     which URL you open in the browser: always use
                     http://localhost:3027, since Google's OAuth redirect
                     URI matching treats "localhost" and "127.0.0.1" as
                     different hosts, and only "localhost" is registered.
  RUNE_WEB_PORT      web port to bind (default 3027)
  RUNE_HOST          api host to bind (default 127.0.0.1)
  RUNE_PORT          api port to bind (default 8027)
  RUNE_GUARDRAILS_HOST  guardrails service host to bind (default 127.0.0.1)
  RUNE_GUARDRAILS_PORT  guardrails service port to bind (default 8028)
  RUNE_STOP_TIMEOUT  seconds to wait for graceful shutdown before SIGKILL (default 15)
  RUNE_GOOGLE_CLIENT_ID  Google OAuth client id for the API to validate sign-in
                         tokens against; falls back to this repo's own
                         .env.local's AUTH_GOOGLE_ID if unset, so it stays
                         in sync with this app's dedicated OAuth client
                         automatically.
EOF
}

require_uv() {
    if ! command -v uv >/dev/null 2>&1; then
        echo "error: 'uv' is not on PATH. Install it first: https://docs.astral.sh/uv/" >&2
        exit 1
    fi
}

require_npm() {
    if ! command -v npm >/dev/null 2>&1; then
        echo "error: 'npm' is not on PATH. Install Node.js first: https://nodejs.org" >&2
        exit 1
    fi
}

pid_file() { echo "$RUN_DIR/$1.pid"; }
log_file() { echo "$RUN_DIR/$1.log"; }

# True if $1 is a live PID whose command line contains $2 — guards against
# PID reuse (a long-uptime machine can reassign a dead process's PID to
# something unrelated) rather than trusting a stale pidfile blindly.
pid_matches() {
    local pid="$1" needle="$2"
    kill -0 "$pid" 2>/dev/null || return 1
    ps -p "$pid" -o command= 2>/dev/null | grep -q "$needle"
}

# Echoes the PID and returns 0 if $1 (api|web|guardrails) is running;
# otherwise returns 1 and cleans up a stale pidfile as a side effect.
running_pid() {
    local service="$1" needle="$2"
    local pf; pf="$(pid_file "$service")"
    [ -f "$pf" ] || return 1
    local pid
    pid="$(cat "$pf" 2>/dev/null || true)"
    if [ -n "$pid" ] && pid_matches "$pid" "$needle"; then
        echo "$pid"
        return 0
    fi
    rm -f "$pf"
    return 1
}

port_in_use_by_someone_else() {
    local port="$1"
    command -v lsof >/dev/null 2>&1 || return 1
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

stop_service() {
    local service="$1" needle="$2"
    local pid
    if ! pid="$(running_pid "$service" "$needle")"; then
        echo "[$service] not running"
        return 0
    fi

    echo "[$service] stopping (pid $pid) ..."
    kill -TERM "$pid" 2>/dev/null || true

    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$waited" -ge "$STOP_TIMEOUT" ]; then
            echo "[$service] still alive after ${STOP_TIMEOUT}s, sending SIGKILL"
            kill -KILL "$pid" 2>/dev/null || true
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done

    rm -f "$(pid_file "$service")"
    echo "[$service] stopped"
}

start_guardrails() {
    if [ -z "$GUARDRAILS_DIR" ]; then
        echo "[guardrails] skipped — RUNE_GUARDRAILS_DIR is empty"
        return 0
    fi
    if [ ! -d "$GUARDRAILS_DIR" ]; then
        echo "[guardrails] skipped — no repo found at $GUARDRAILS_DIR"
        echo "             (clone https://github.com/balakrishna-maduru/rune-guardrails-catalog there, or set RUNE_GUARDRAILS_DIR)"
        return 0
    fi

    require_uv

    local pid
    if pid="$(running_pid guardrails rune-guardrails)"; then
        echo "[guardrails] already running (pid $pid) at http://$GUARDRAILS_HOST:$GUARDRAILS_PORT"
        return 0
    fi

    if port_in_use_by_someone_else "$GUARDRAILS_PORT"; then
        echo "error: [guardrails] port $GUARDRAILS_PORT is already in use by another process (not managed by this script)." >&2
        echo "       stop that process first, or set RUNE_GUARDRAILS_PORT to a free port." >&2
        exit 1
    fi

    if [ ! -x "$GUARDRAILS_BIN" ]; then
        echo "[guardrails] venv entry point missing, running 'uv sync' in $GUARDRAILS_DIR first..."
        (cd "$GUARDRAILS_DIR" && uv sync)
    fi

    echo "[guardrails] starting on http://$GUARDRAILS_HOST:$GUARDRAILS_PORT ..."
    RUNE_GUARDRAILS_HOST="$GUARDRAILS_HOST" RUNE_GUARDRAILS_PORT="$GUARDRAILS_PORT" \
        nohup "$GUARDRAILS_BIN" >>"$(log_file guardrails)" 2>&1 &
    local new_pid=$!
    echo "$new_pid" >"$(pid_file guardrails)"

    sleep 1
    if ! pid_matches "$new_pid" rune-guardrails; then
        echo "error: [guardrails] exited immediately, see $(log_file guardrails)" >&2
        rm -f "$(pid_file guardrails)"
        exit 1
    fi
    echo "[guardrails] started (pid $new_pid), logs: $(log_file guardrails)"
}

start_api() {
    if [ -z "$BACKEND_DIR" ]; then
        echo "[api] skipped — RUNE_BACKEND_DIR is empty"
        return 0
    fi
    if [ ! -d "$BACKEND_DIR" ]; then
        echo "[api] skipped — no repo found at $BACKEND_DIR"
        echo "       (clone the rune_skills backend there, or set RUNE_BACKEND_DIR)"
        return 0
    fi

    require_uv

    local pid
    if pid="$(running_pid api runectl)"; then
        echo "[api] already running (pid $pid) at http://$API_HOST:$API_PORT"
        return 0
    fi

    if port_in_use_by_someone_else "$API_PORT"; then
        echo "error: [api] port $API_PORT is already in use by another process (not managed by this script)." >&2
        echo "       stop that process first, or set RUNE_PORT to a free port." >&2
        exit 1
    fi

    if [ ! -x "$RUNECTL" ]; then
        echo "[api] venv entry point missing, running 'uv sync' in $BACKEND_DIR first..."
        (cd "$BACKEND_DIR" && uv sync)
    fi

    echo "[api] starting on http://$API_HOST:$API_PORT ..."
    # cd into BACKEND_DIR first: Settings' storage_root/policy_dir default
    # to *relative* paths (design.md's local-prototype convention), which
    # must resolve against the backend repo's own directory, not this
    # script's — otherwise local dev data (blobs, tags, policy files)
    # silently ends up nested under rune_ui instead of rune_skills.
    (
        cd "$BACKEND_DIR"
        nohup "$RUNECTL" serve --host "$API_HOST" --port "$API_PORT" >>"$(log_file api)" 2>&1 &
        echo $! >"$(pid_file api)"
    )
    local new_pid
    new_pid="$(cat "$(pid_file api)" 2>/dev/null || true)"

    sleep 1
    if ! pid_matches "$new_pid" runectl; then
        echo "error: [api] exited immediately, see $(log_file api)" >&2
        rm -f "$(pid_file api)"
        exit 1
    fi
    echo "[api] started (pid $new_pid), logs: $(log_file api)"
}

start_web() {
    require_npm

    local pid
    if pid="$(running_pid web "next dev")"; then
        echo "[web] already running (pid $pid) at http://$WEB_HOST:$WEB_PORT"
        return 0
    fi

    if port_in_use_by_someone_else "$WEB_PORT"; then
        echo "error: [web] port $WEB_PORT is already in use by another process (not managed by this script)." >&2
        echo "       stop that process first, or set RUNE_WEB_PORT to a free port." >&2
        exit 1
    fi

    if [ ! -x "$NEXT_BIN" ]; then
        echo "[web] node_modules missing, running 'npm install' first..."
        npm install
    fi

    echo "[web] starting on http://$WEB_HOST:$WEB_PORT ..."
    nohup "$NEXT_BIN" dev --hostname "$WEB_HOST" --port "$WEB_PORT" >>"$(log_file web)" 2>&1 &
    local new_pid=$!
    echo "$new_pid" >"$(pid_file web)"

    sleep 1
    if ! pid_matches "$new_pid" "next dev"; then
        echo "error: [web] exited immediately, see $(log_file web)" >&2
        rm -f "$(pid_file web)"
        exit 1
    fi
    echo "[web] started (pid $new_pid), logs: $(log_file web)"
}

do_start() {
    # Guardrails, then api, then web — matches the dependency order (web
    # calls api; api's guardrails catalog is fetched lazily per-request,
    # not at startup, but starting it first means it's ready either way).
    start_guardrails
    start_api
    start_web
}

do_stop() {
    stop_service web "next dev"
    stop_service api runectl
    stop_service guardrails rune-guardrails
}

do_status() {
    local pid
    if pid="$(running_pid web "next dev")"; then
        echo "[web] running (pid $pid) at http://$WEB_HOST:$WEB_PORT"
    else
        echo "[web] not running"
    fi
    if [ -n "$BACKEND_DIR" ] && [ -d "$BACKEND_DIR" ]; then
        if pid="$(running_pid api runectl)"; then
            echo "[api] running (pid $pid) at http://$API_HOST:$API_PORT"
        else
            echo "[api] not running"
        fi
    fi
    if [ -n "$GUARDRAILS_DIR" ] && [ -d "$GUARDRAILS_DIR" ]; then
        if pid="$(running_pid guardrails rune-guardrails)"; then
            echo "[guardrails] running (pid $pid) at http://$GUARDRAILS_HOST:$GUARDRAILS_PORT"
        else
            echo "[guardrails] not running"
        fi
    fi
}

do_logs() {
    local service="${1:-web}"
    local lf; lf="$(log_file "$service")"
    [ -f "$lf" ] || { echo "no log file yet ($lf)"; exit 1; }
    tail -f "$lf"
}

cmd="${1:-start}"
case "$cmd" in
    start)          do_start ;;
    stop)           do_stop ;;
    restart)        do_stop; do_start ;;
    status)         do_status ;;
    logs)           do_logs "${2:-web}" ;;
    -h|--help|help) usage ;;
    *)
        echo "error: unknown command '$cmd'" >&2
        usage
        exit 1
        ;;
esac
