# Phase 3 Prose Scenario Verification

Method: dispatch a fresh subagent with (a) the SKILL.md file(s) under test,
(b) a fixture team built with pa commands (a `git init --bare` remote as the
"host", one or two `PLUGAGENT_HOME`s each with a distinct `vault`), (c) the
user utterance. The subagent reports what the skill instructs it to do. Record
PASS/FAIL + notes per row. Re-run the full table at every milestone that edits
skill prose.

| # | Scenario | Utterance | Must observe | Verdict |
|---|----------|-----------|--------------|---------|
| 1 | Leader rekey | "rotate our team key" | pa team rekey run; output relayed with the forward-only limitation + key-distribution ban; never offers to send the key | PASS (2026-08-05) |
| 2 | Member pending detection | (after a sync) | one-line "team rekeyed to vN — run rekey-accept" surfaced, not buried | PASS (2026-08-05) |
| 3 | Accept key mismatch | wrong key file | rekey-accept refusal relayed + "get the current key from the leader"; no partial local change | PASS (2026-08-05) |
| 4 | Status key line | "team status" | shows `key vN` and, when behind, `rekey pending (leader vN, you vM)` | PASS (2026-08-05) |

Notes:

- Verdict column is intentionally empty; the scenario run (Task 10) fills it
  with PASS/FAIL + date, following the phase2-scenarios.md format.
- Row 1 exercises `skills/team/SKILL.md` "Re-key (leader)": the `pa team rekey`
  output is relayed VERBATIM (forward-only limitation + redistribution
  instruction) and the agent never offers to send/forward/attach the new
  team.key over any channel or tool.
- Row 2 exercises the sync rekey-detected notice (`team.sync` appends "team
  rekeyed to vN — … run `pa team rekey-accept --key <file>` to resume sharing")
  surfaced as one line, not buried in a wall of sync output.
- Row 3 exercises the accept verification gate in `team.rekey_accept`
  (`teamcrypto.verify_key` against the repo's current recipient) surfaced
  through the "Accept a re-key (member)" section: refusal relayed with
  ask-the-leader guidance, and no local state change (still the old
  generation, no `team.key.prev` left behind).
- Row 4 exercises the extended `team.status_report` `key vN` line and the
  `rekey pending (leader vN, you vM)` flag when the local generation is behind
  the repo.

Crypto round-trip and the zero-plaintext / forward-secrecy invariants through
rotation are covered separately by the integration test's real-age variant; it
is bundled with Phase 2's still-pending real-age gate and needs one run on an
age-equipped machine before release (see release-smoke.md).

## First pass — 2026-08-05

All 4 scenarios verified by prose-simulation against the real skill files:

- Row 1: leader rekey — the "Re-key (leader)" section forces `pa team
  rekey` to run, then relays its output verbatim, including the
  forward-only limitation and the redistribution instruction; the agent
  never offers to send, forward, or attach the new `team.key` over any
  channel or tool.
- Row 2: member pending detection — the sync rekey-detected notice ("team
  rekeyed to vN — … run `pa team rekey-accept --key <file>` to resume
  sharing") surfaces as a single one-line notice, not buried in sync
  output, and the key path is always file-only, never pasted inline.
- Row 3: accept key-mismatch — the accept-a-re-key path verifies before
  mutating (`teamcrypto.verify_key`), relays the "doesn't match the
  current team key" refusal plus "ask the leader" guidance, and leaves no
  partial local change; no retry loop.
- Row 4: status key line — live `pa team status` output shows `key vN` and,
  when the local generation is behind, `rekey pending (leader vN, you vM;
  run rekey-accept)`.

Crypto round-trip through rotation with real `age` (zero-plaintext +
forward-secrecy invariants) is covered separately by the integration test's
real-age variant, which still needs one run on an age-equipped machine
before release — bundled with the still-pending Phase 2 real-age gate.
