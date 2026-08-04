---
description: PlugAgent diagnostics — capture health, vault, memory, cursor
---

Run `python3 "$CLAUDE_PLUGIN_ROOT/scripts/pa" status --full` and present the
result in the user's language, one short annotated block. If errors > 0, offer
to inspect `~/.plugagent/state/errors.log` and diagnose.
