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

### Re-key cycle (real age, same session as the Phase 2 real-age gate)

Runs in the **same age-equipped session** as Phase 2's still-pending real-age
gate (steps 1–7 above) — both must pass before any release relying on the
confidentiality/rotation guarantee. Continues from the acme team built above
(leader `alice` / HOME 1, member `bob` / HOME 2, at least one shared page each).

8. **Leader rekey** (HOME 1): `pa team rekey --team acme`. Verify it reports the
   rotation to `v2`, prints the path to the new `team.key`, and relays the
   forward-only limitation. Confirm `pa team status` now shows `key v2` for the
   leader.
9. **Distribute + member accept** (HOME 2): copy the new `team.key` over
   securely, then `pa team rekey-accept --key <path> --team acme`. Verify it
   reports acceptance of `v2`; `pa team status` for `bob` now shows `key v2`
   (no longer "rekey pending"). Delete the received key copy.
10. **key_version incremented, `.age`-only on github.com**: open the repo in a
    browser. Verify `team.json`'s `key_version` is `2` (and `recipient` is the
    new `age1…`), and the only other visible files are `*.age` blobs — no
    plaintext, no `.md` under `members/`.
11. **Forward secrecy (v1 key can't read v2)**: keep a copy of the *old* v1
    `team.key`. Pick a page re-encrypted at the rekey (or newly shared after it)
    and attempt `age -d -i <old-v1-key> <that>.age` — it must **fail** to
    decrypt. Confirm the current v2 key decrypts it. This is the forward-secrecy
    invariant: post-rekey ciphertext is unreadable with the retired key.
12. **Share resumes after accept**: back in HOME 2, `pa team share <a-page>.md`
    now succeeds (it was refused with "team rekeyed" before step 9).

### Filename privacy (real age, same session as the real-age gate)

Runs in the **same age-equipped session** as the team smoke and re-key cycle
above (real private GitHub repo, leader `alice` / HOME 1, member `bob` / HOME 2,
at least one shared page each). Exercises opt-in path hiding end-to-end.

13. **Leader turns on privacy** (HOME 1): `pa team privacy on --team acme`.
    Verify it reports privacy is ON, prints the path to the **fnkey**, and
    relays the paths-only scope (member names / page counts / commit times stay
    visible; pre-privacy history keeps old plaintext paths). Confirm
    `pa team status` now shows `privacy: hashed` for the leader.
14. **Hashed names on github.com**: open the repo in a browser. Verify the
    leader's already-shared pages are now `<32-hex>.age` under
    `members/alice/wiki/` — **no real title appears** in the file tree, and the
    commit message that renamed them is `privacy: on` (no plaintext path in it
    either). `team.json` shows `privacy: "hashed"` and `schema_version: 2`. A
    per-member `members/alice/manifest.age` exists (opaque ciphertext).
15. **Second member accepts** (HOME 2): copy the fnkey over securely, then
    `pa team privacy-accept --fnkey <path> --team acme`. Verify it reports
    acceptance; bob's own pre-privacy pages are now renamed to `<32-hex>.age` on
    github.com; `pa team status` for bob shows `privacy: hashed` (no longer
    `privacy pending`). Delete the received fnkey copy.
16. **Recall still resolves real titles**: back in either home,
    `pa team sync --force`, then wake the agent and ask "what do we know about
    `<topic>`?" → the answer still cites the shared pages by their **real
    titles** with member attribution — the hashed host layout is transparent to
    recall (the manifest maps hashes back to paths locally).

### Memory-card sharing (real age, same session as the real-age gate)

Runs in the **same age-equipped session** as the sections above (leader `alice`
/ HOME 1, member `bob` / HOME 2). Exercises opt-in, per-card promotion end to
end. Give alice at least three personal cards first (`pa memory add …`), and
use one of them a few times so it carries non-zero `uses:`/`last_used:`.

17. **Promote exactly one card** (HOME 1): `pa team share-card <card> --team acme`.
    First run must be **refused** with the schema-3 lockout warning; re-run with
    `--confirm-schema-bump` and verify it reports the promotion, that usage
    statistics were stripped, and that the personal card is unchanged
    (`pa memory show <card>` still shows it; the file's `uses:` is intact).
    Re-run the same command once more: it must report "already up to date"
    without creating a commit.
18. **Card-only, ciphertext-only on github.com**: open the repo in a browser.
    Verify `members/alice/memory/` holds exactly ONE `.age` blob (or one
    `<32-hex>.age` if privacy is on), that the two unpromoted card names appear
    **nowhere** in the tree or commit messages, and that `team.json` shows
    `schema_version: 3`.
19. **Receive + attribution + off switch** (HOME 2): `pa team sync --force`,
    then `pa memory list` → a `## Team cards (read-only)` section with
    `(team: alice)` attribution; `pa memory show <card>` prints the
    `(team: alice, read-only)` header and NO `uses:`/`last_used:` line. Add a
    personal card of the same name → it wins, and the team line is marked
    `(shadowed by your card)`. Run `pa team memory off --team acme` → the team
    section disappears immediately, `pa team status` shows `(team memory off)`,
    and the repo's `team.json` is **unchanged** (the opt-out is local only).
    `pa team memory on` restores it.
20. **Withdraw** (HOME 1): `pa team unshare-card <card> --team acme`. Verify the
    forward-only sentence is printed, the blob is gone from `members/alice/memory/`
    on github.com (and the manifest entry with it, if privacy is on), and after
    `pa team sync --force` in HOME 2 the card is gone from `pa memory list` and
    from the local cache. Alice's personal card is still in her vault.
21. **Zero-unpromoted-cards backstop**: run
    `python3 -m pytest tests/test_team_memory_integration.py -q` on this
    age-equipped machine — the `@needs_age` test
    (`test_zero_unpromoted_cards_and_zero_statistics_in_all_objects`) must PASS,
    not skip. It scans **all** git objects, not just HEAD.

Record date + build + verdicts below (execution deferred to separate hardware
per owner policy).
