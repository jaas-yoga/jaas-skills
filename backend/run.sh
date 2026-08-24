#!/usr/bin/env bash
# Single-point process manager for the backend: the Python API (runectl
# serve) and the standalone rune-guardrails service (a separate repo/
# codebase — see RUNE_GUARDRAILS_DIR below), started/stopped together.
#
# This repo no longer contains the web UI — it lives in the sibling
# rune_ui repo, which has its own run.sh that starts this api, guardrails,
# and its own web process together for full-stack local dev. Use *this*
# script for backend-only work.
#
#   ./run.sh            start both (no-op for whichever is already running)
#   ./run.sh start
#   ./run.sh stop        (no-op for whichever isn't running)
#   ./run.sh restart
#   ./run.sh status
#   ./run.sh logs [api|guardrails]   tail one service's log (default: api)
#
# No service is invoked through its package-manager wrapper (`uv run
# runectl`) — wrappers fork a child and return immediately, so `$!` would
# capture the wrapper's PID rather than the actual server's, breaking
# stop/restart. Invoking each venv entry point directly makes `$!` the
# real process, which installs its own SIGTERM handler for graceful
# shutdown either way.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUN_DIR="$SCRIPT_DIR/.run"
RUNECTL="$SCRIPT_DIR/.venv/bin/runectl"

# The guardrails service is a genuinely separate codebase (its own repo,
# own pyproject.toml, own deploy) — this is only a local-dev convenience
# for running both together. Defaults to a checkout alongside this
# monorepo (one level up from backend/); override if yours lives
# elsewhere, or skip starting it if RUNE_GUARDRAILS_DIR="".
GUARDRAILS_DIR="${RUNE_GUARDRAILS_DIR-$SCRIPT_DIR/../../rune_guardrail}"
GUARDRAILS_BIN="$GUARDRAILS_DIR/.venv/bin/rune-guardrails"

API_HOST="${RUNE_HOST:-127.0.0.1}"
API_PORT="${RUNE_PORT:-8027}"
GUARDRAILS_HOST="${RUNE_GUARDRAILS_HOST:-127.0.0.1}"
GUARDRAILS_PORT="${RUNE_GUARDRAILS_PORT:-8028}"
STOP_TIMEOUT="${RUNE_STOP_TIMEOUT:-15}"   # seconds to wait for graceful shutdown before SIGKILL

# The API talks to the guardrails service over HTTP only (guardrails/client.py)
# — never in-process. Point it at the instance this script manages unless
# already overridden.
export RUNE_GUARDRAILS_SERVICE_URL="${RUNE_GUARDRAILS_SERVICE_URL:-http://$GUARDRAILS_HOST:$GUARDRAILS_PORT}"

# Google OAuth client id the API validates sign-in ID tokens against. This
# repo has no web UI of its own anymore, so there's no sibling env file to
# read it from automatically — set it explicitly (the rune_ui repo's
# run.sh does this for you when it starts this api as a subprocess).
export RUNE_GOOGLE_CLIENT_ID="${RUNE_GOOGLE_CLIENT_ID:-}"

mkdir -p "$RUN_DIR"

usage() {
    cat <<EOF
Usage: $(basename "$0") [start|stop|restart|status|logs [api|guardrails]]

  (no argument)  same as "start"
  start          start both services in the background (no-op if already running)
  stop           stop both services (no-op if not running)
  restart        stop, then start
  status         show whether each service is running
  logs [api|guardrails]  tail one service's log file (default: api)

Environment overrides:
  RUNE_HOST          api host to bind (default 127.0.0.1)
  RUNE_PORT          api port to bind (default 8027)
  RUNE_GUARDRAILS_DIR   path to the standalone rune-guardrails service repo
                        (default: ../../rune_guardrail, a checkout
                        alongside this monorepo).
                        Set to "" to skip starting it — the API degrades
                        gracefully (503 only on the specific routes that
                        need it) rather than failing to start.
  RUNE_GUARDRAILS_HOST  guardrails service host to bind (default 127.0.0.1)
  RUNE_GUARDRAILS_PORT  guardrails service port to bind (default 8028)
  RUNE_STOP_TIMEOUT  seconds to wait for graceful shutdown before SIGKILL (default 15)
  RUNE_GOOGLE_CLIENT_ID  Google OAuth client id the API validates sign-in
                         tokens against. Must match whatever client the web
                         UI (rune_ui) is using — its run.sh sets this for
                         you when it starts this api as a subprocess; set
                         it explicitly if running this script standalone
                         against a real Google sign-in flow.
EOF
}

require_uv() {
    if ! command -v uv >/dev/null 2>&1; then
        echo "error: 'uv' is not on PATH. Install it first: https://docs.astral.sh/uv/" >&2
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

# Echoes the PID and returns 0 if $1 (api|guardrails) is running; otherwise
# returns 1 and cleans up a stale pidfile as a side effect.
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
        echo "[api] venv entry point missing, running 'uv sync' first..."
        uv sync
    fi

    echo "[api] starting on http://$API_HOST:$API_PORT ..."
    nohup "$RUNECTL" serve --host "$API_HOST" --port "$API_PORT" >>"$(log_file api)" 2>&1 &
    local new_pid=$!
    echo "$new_pid" >"$(pid_file api)"

    sleep 1
    if ! pid_matches "$new_pid" runectl; then
        echo "error: [api] exited immediately, see $(log_file api)" >&2
        rm -f "$(pid_file api)"
        exit 1
    fi
    echo "[api] started (pid $new_pid), logs: $(log_file api)"
}

do_start() {
    # Guardrails first: not required for api to start (its catalog is
    # fetched lazily, per request, not at startup — design.md §4.5), but
    # starting it first means it's ready by the time anything needs it.
    start_guardrails
    start_api
}

do_stop() {
    stop_service api runectl
    stop_service guardrails rune-guardrails
}

do_status() {
    local pid
    if [ -n "$GUARDRAILS_DIR" ] && [ -d "$GUARDRAILS_DIR" ]; then
        if pid="$(running_pid guardrails rune-guardrails)"; then
            echo "[guardrails] running (pid $pid) at http://$GUARDRAILS_HOST:$GUARDRAILS_PORT"
        else
            echo "[guardrails] not running"
        fi
    fi
    if pid="$(running_pid api runectl)"; then
        echo "[api] running (pid $pid) at http://$API_HOST:$API_PORT"
    else
        echo "[api] not running"
    fi
}

do_logs() {
    local service="${1:-api}"
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
    logs)           do_logs "${2:-api}" ;;
    -h|--help|help) usage ;;
    *)
        echo "error: unknown command '$cmd'" >&2
        usage
        exit 1
        ;;
esac
