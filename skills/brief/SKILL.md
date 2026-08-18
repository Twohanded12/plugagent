---
name: brief
description: >
  Brief the user on their recent work ("what did I do yesterday / last week?")
  from the PlugAgent vault. Invoked via the core plugagent skill's routing.
---

# Brief

Mirror the user's language. Text-first (no charts in Phase 1).

1. Determine the window from the request (yesterday / last week / N days). If
   the request names no window, default to the last 7 days and say which
   window you used.
2. List `raw/sessions/` files whose date prefix falls in the window; read them.
3. Read `wiki/log.md` tail for capture/distill events in the window.
4. Compose: 3–8 bullet summary grouped by project (use `cwd` frontmatter),
   then one line of "open threads" if any session ended mid-task. Sessions
   without a `cwd` (e.g. unparsed pointer captures) go in an "unknown" group
   and are mentioned as unparsed captures.
5. If the window has no captures, say so and show `pa status` (maybe capture
   is off or failing — don't guess silently).
6. Team activity is EXCLUDED from personal briefings. Only when the user
   explicitly asks about the team ("what did the team do last week?") do you
   read the team cache — group by member, cite with attribution, and note
   staleness if the last sync is old. "we"/"us" without naming the team stays
   personal (default to personal on ambiguity). Brief does not run `pa team
   sync` (it stays side-effect-free) — team pages are served from whatever the
   last recall pulled; say "as of the last sync" when presenting them.
7. When you walk the team cache, read shared WIKI pages only — that is
   `members/<member>/wiki/` — and SKIP `members/<member>/memory/` entirely.
   Received memory cards are not team activity, and a user who ran
   `pa team memory off` must not see them resurface in a briefing. Team cards
   reach the user through the memory hot index alone, never through brief.

This skill is read-only: every step above only reads (`raw/sessions/` files,
`wiki/log.md`, `pa status`). Nothing here writes to the vault.
