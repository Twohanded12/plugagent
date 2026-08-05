# Phase 2 Prose Scenario Verification

Method: dispatch a fresh subagent with (a) the SKILL.md file(s) under test,
(b) a fixture team built with pa commands (a `git init --bare` remote as the
"host", one or two `PLUGAGENT_HOME`s each with a distinct `vault`), (c) the
user utterance. The subagent reports what the skill instructs it to do. Record
PASS/FAIL + notes per row. Re-run the full table at every milestone that edits
skill prose.

| # | Scenario | Utterance | Must observe | Verdict |
|---|----------|-----------|--------------|---------|
| 1 | Join wizard happy path | "connect me to the team repo" | URL+key-file asked (inline key refused), member name validated, join runs, success summary | PASS (2026-08-04) |
| 2 | Join wizard bad key | key doesn't match | one-line pa: error relayed + ask-leader guidance, no retry loop | PASS (2026-08-04) |
| 3 | Post-distill share offer | distill approve, then decline offer | offer is ONE line, decline = zero team commands | PASS (2026-08-04) |
| 4 | Team recall attribution | "what do we know about auth?" with teammate page in cache | teammate citation carries member attribution; contradiction with own page → ⚠️ both + ask | PASS (2026-08-04) |
| 5 | Sync failure staleness | cache present, network down | answer still served + ONE staleness line | PASS (2026-08-04) |
| 6 | Personal brief isolation | "what did I do yesterday?" with team cache populated | zero team content in the personal brief | PASS (2026-08-04) |

Notes:

- Verdict column is intentionally empty; the scenario run (Task 10) fills it
  with PASS/FAIL + date, following the phase1-scenarios.md format.
- Row 2 exercises the fail-closed key check in `team.join_team` (trial
  encrypt/decrypt via `teamcrypto.verify_key`) surfaced through
  `skills/team/SKILL.md` join step 3.
- Row 3 exercises the post-distill offer added to `skills/distill/SKILL.md`
  (offer only when a team is configured; decline is a no-op, never auto-share).
- Row 4 exercises `skills/recall/SKILL.md` step 2b: team cache index +
  attribution, and the my-page-vs-teammate-page contradiction reusing the
  same ⚠️-show-both-never-auto-resolve rule as Phase 1.
- Row 5 exercises the stale-cache path in `team.sync` (network failure →
  "serving stale cache") surfaced as a single staleness line, not a lecture.
- Row 6 exercises `skills/brief/SKILL.md`: team activity is excluded from
  personal briefings unless the user explicitly asks about the team.

## First pass — 2026-08-04

All 6 scenarios verified by prose-simulation subagents against the real
skill files (not summaries):

- Rows 1-2: join wizard — file-only key handling (inline key pasted in chat
  is refused, key is never transmitted) + member-name validation on the
  happy path; bad-key path relays the one-line `pa:` error and stops, no
  retry loop.
- Row 3: post-distill share offer — gated on a team being configured,
  deduped (offered once, not re-offered every batch), and decline is a
  genuine no-op (zero team commands run).
- Rows 4-5: recall attribution and the ⚠️ contradiction rule, verified
  against a hand-built plaintext team cache fixture; sync-failure
  degradation.
- Row 6: personal-brief isolation, including the "we/us" edge case (user
  asking about shared work in first-person plural) — team content still
  excluded unless the team is explicitly named.

Crypto round-trip with real `age` (not the fixture's plaintext-cache
shortcut) is covered separately by the integration test's real-age variant;
it still needs one run on an age-equipped machine before release.
