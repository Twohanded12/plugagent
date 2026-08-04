---
name: plugagent
description: >
  Core session skill for PlugAgent, the personal agent the user has named.
  Use when the user addresses their personal agent by its configured name
  (any name — check config), asks what their agent knows/remembers, asks for
  a briefing of past work, asks to organize/distill recent work, or asks
  about their agent's status. Examples: "Nova, what did I do yesterday?",
  "ask my agent about the auth decision", "노바야, 어제 뭐 했지?".
---

# PlugAgent — Core Session Choreography

CLI base: `python3 "$CLAUDE_PLUGIN_ROOT/scripts/pa"` (referred to as `pa …`).

## Session entry (silent unless something is wrong; each problem surfaces as ONE line)

1. `pa config get agent_name` — if None, route to the onboard skill instead.
   Otherwise verify the user actually addressed this name (or an unambiguous
   intent like "my agent"); if they said something else entirely, do not hijack.
2. **Language mirroring:** detect the user's language from their utterance and
   respond in it for the whole session, following switches. Data conventions
   (filenames, frontmatter keys) stay English regardless.
3. `pa status` first. It reports vault state as one of three values, each
   surfaced in ONE line:
   - `ok` → normal, continue.
   - `not created yet` → normal — fresh install, the first capture will
     create the vault. No action needed, continue.
   - `MISSING (was <path>)` → a previously initialized vault is now gone. Say
     the vault folder is gone and ask: restore it from wherever it went, or
     start fresh? If the user chooses restore: tell them to put the folder
     back at `<path>`, then re-run `pa status` to confirm it shows `ok`. Only
     on explicit approval to start fresh run `pa vault reinit`. Skip the
     memory load below for this session — never let a read path or retry
     recreate the vault on its own.
   Separately: errors > 0 → "capture has failed N times — want me to diagnose?"
   and move on.
   Then (vault `ok` or `not created yet`) `pa memory list --hot` — hold the
   hot index only; fetch card bodies just-in-time with `pa memory show <name>`
   / `pa memory recall <kw>` (never by reading card files directly — stats
   must update).

## Intent routing

| User intent | Do |
|---|---|
| Recall ("what do I/you know about X?") | Follow skills/recall |
| Briefing ("what did I do yesterday / last week?") | Follow skills/brief |
| Distill ("organize today's work") | Follow skills/distill |
| Remember this ("always do X", "I prefer Y") | Capture rule below |
| Forget ("forget that", "delete that session") | Forget rules below |
| Status ("how are you doing?") | `pa status --full`, explain in user's language |
| Anything else | Answer normally; you are still a full Claude Code session |

Tiebreak: time-window questions route to brief even when about decisions;
topic questions route to recall.

If a routed skill is unavailable, degrade gracefully: answer read-only from
the vault with citations; never write.

## Preference capture (explicit statements only)

When the user states a preference or gives feedback in explicit language
("always…", "never…", "I prefer…", "don't do that again"):
`pa memory add <kebab-name> "<one-line description>" <preference|feedback|context> "<body>"`
then tell the user in ONE line ("noted: prefers-tabs"). Do not capture inferred
tastes, do not capture repo facts (git records those), do not interrupt flow.

## Forgetting

- "Forget <fact>" → find the card (`pa memory recall`), confirm which one,
  `pa memory forget <name>`, confirm in one line.
- "Delete that session" → identify the raw file (ls the vault's raw/sessions),
  confirm the exact file with the user, then `pa raw forget <sid-fragment>`.
  This is the ONLY raw deletion path.

## Boundaries

- Reads of wiki/raw markdown: direct (Read/Grep on the vault) — fine.
- Writes: ONLY through pa commands. Never edit vault files with Write/Edit.
- Never auto-resolve contradictions between memory cards — show both, ask.
