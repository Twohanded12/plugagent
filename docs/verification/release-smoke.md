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

## Team smoke (run on separate hardware — dev-Mac install prohibited by owner policy)

Team mode needs `age` (`brew install age`) and a **real private GitHub repo**
(empty at start). Run on two machines, or two `PLUGAGENT_HOME`s on one machine
(each with a distinct `vault` path). Never run the install steps on the dev
Mac — owner policy.

1. **Leader init** (machine/HOME 1): create an empty private repo, then
   `pa team init acme --repo <url> --as alice`. Verify `team.key` printed and
   the repo has a `team.json` commit. The leader is share-ready immediately —
   `--as` claims the `alice` namespace, no separate self-join.
2. **Share two pages**: distill or `pa wiki put` two pages, then
   `pa team share <a>.md` and `pa team share <b>.md`. Verify each reports
   "shared".
3. **Member join** (machine/HOME 2): copy `team.key` over securely, then
   `pa team join <url> --key <path> --as bob`. Verify success summary; delete
   the received key copy.
4. **Sync + attributed recall**: `pa team sync --force`, then wake the agent and
   ask "what do we know about <topic>?" → the answer cites the leader's shared
   page **with member attribution** (e.g. "(teammate's shared page)").
5. **Ciphertext-only eyeball**: open the repo on github.com in a browser. Verify
   the only visible files are `team.json` and `*.age` blobs — no plaintext page
   bodies, no `.md` under `members/`. Open one `.age` file: it must be
   unreadable ciphertext.
6. **Leak-guard spot check**: in the leader's local clone
   (`~/.plugagent/teams/acme/repo`), hand-place a plaintext file
   (`echo secret > leak.md`), `git add` + `git commit` it, then attempt a push
   via `pa team sync --force` (or `pa team share` of any page). The push must be
   **refused** by the leak guard — verify nothing reached the remote (the
   plaintext file is not on github.com).
7. **Kill-switch spot check**: `pa config set capture off` does not affect team
   reads (cache-based) but confirm personal capture stays off during the run;
   `pa team status` reports each team's last-sync age, unpushed count, and
   decrypt-failure count.

Record date + build + verdicts below (execution deferred to separate hardware
per owner policy).
