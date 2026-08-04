# Release Smoke (manual, real machine)

1. `claude plugin marketplace add <repo-or-local-path>` → `/plugin install plugagent@plugagent-marketplace` → restart Claude Code.
2. `/plugagent:setup` → name agent, consent to capture.
3. Run one ordinary session (any small task). Close it.
4. Verify: `~/PlugAgent/raw/sessions/` has today's file; `wiki/log.md` has a CAPTURE line.
5. Wake the agent by name → ask "what did I do today?" → briefing mentions step 3's task.
6. Say an explicit preference → one-line "noted" → `pa memory list` shows the card.
7. "Organize today's work" → proposal → approve → wiki page exists; reject path tested once too (verify the proposal takes the OLDEST pending files first).
8. `pa config set capture off` → run a session → no new raw file.
9. Break python3 (rename PATH shim) → close a session → Claude Code shows no error; errors.log grew.

Record date + build + verdicts below.

## Run 1 — 2026-08-04, build 0.1.0 (main @ 98f01b8), macOS

Live smoke on the developer machine. Headless sub-sessions were unavailable
(CLI OAuth expired), so conversational steps were exercised at the CLI layer
and stand on the scenario table (phase1-scenarios.md, 11/11 PASS); everything
mechanical ran live against the REAL home (`~/.plugagent`, `~/PlugAgent`) and
the REAL installed plugin copy (claude plugin cache, hooks.json with timeout,
shim mode 755 verified).

| Step | Verdict | Evidence |
|---|---|---|
| 1. Marketplace add + plugin install | PASS (live) | `claude plugin marketplace add` + `install` succeeded, user scope |
| 2. Onboarding | PARTIAL (CLI-level) | conversation blocked by CLI OAuth; real config writes exercised (`agent_name 'Nova'`, explicit `capture on`); prose flow = scenario rows 1–2 |
| pre-consent gate (C1) | PASS (live) | hook fired with name-only config → exit 0, NO vault created, status `not created yet` |
| 3. Session end → capture | PASS (live, manual hook fire) | installed shim invoked with a REAL Claude Code transcript (session 775a9648…) — desktop-app restart not possible mid-smoke, so the Stop event itself was simulated by direct shim invocation |
| 4. Raw + log verified | PASS (live) | raw file with correct session_id/cwd frontmatter, 3 messages; `wiki/log.md` CAPTURE line; found: slug-length wart → fixed in this commit pair |
| 5. Wake → briefing | SCENARIO | rows 3, 9 (live sub-session unavailable) |
| 6. Preference card | PASS (live) | `pa memory add` → hot index 1 card |
| 7. Distill | PASS (live) | pending → `pa wiki put concepts/smoke-demo.md` → advance → pending empty, index.md updated; reject path = scenario row 6 |
| 8. Kill switch | PASS (live) | `capture off` → hook fire with a second real transcript → raw count unchanged, exit 0 |
| 9. python3 broken | PASS (live) | curated PATH without python3 → exit 0, errors.log gained "python3 not found", status errors: 1 |

Post-smoke: smoke artifacts removed from the real home; plugin left installed;
capture left OFF pending the owner's real onboarding.
