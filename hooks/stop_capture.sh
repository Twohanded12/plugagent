#!/bin/sh
# PlugAgent Stop-hook shim. Contract: NEVER exit non-zero, NEVER block the session.
STATE_DIR="${PLUGAGENT_HOME:-$HOME/.plugagent}/state"
payload=$(cat 2>/dev/null)
transcript=$(printf '%s' "$payload" | sed -n 's/.*"transcript_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
[ -n "$transcript" ] || exit 0
if command -v python3 >/dev/null 2>&1; then
  python3 "${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}/scripts/pa" capture --transcript "$transcript" >/dev/null 2>&1 || {
    mkdir -p "$STATE_DIR" 2>/dev/null
    printf '%s capture: python invocation failed\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$STATE_DIR/errors.log" 2>/dev/null
  }
else
  mkdir -p "$STATE_DIR" 2>/dev/null
  printf '%s capture: python3 not found\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$STATE_DIR/errors.log" 2>/dev/null
fi
exit 0
