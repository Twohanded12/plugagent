# Phase 1 Prose Scenario Verification

Method: dispatch a fresh subagent with (a) the SKILL.md file(s) under test,
(b) a fixture vault built with pa commands, (c) the user utterance. The
subagent reports what the skill instructs it to do. Record PASS/FAIL + notes
per row. Re-run the full table at every milestone that edits skill prose.

| # | Scenario | Utterance | Must observe | Verdict |
|---|----------|-----------|--------------|---------|
| 1 | Onboard happy path | "set up plugagent" (EN) | name asked → validated → capture consent asked explicitly | PASS (2026-08-04) |
| 2 | Onboard reserved name | name "Claude" | rejected + 2 alternatives offered | PASS (2026-08-04) |
| 3 | Wake + route, KO | "노바야, 어제 뭐 했지?" | config name check → brief flow → Korean response | PASS (2026-08-04) |
| 4 | Recall citations | "what do we know about auth?" | index.md first → citations in answer | PASS (2026-08-04) |
| 5 | Recall contradiction | fixture has 2 conflicting cards | both shown with ⚠️, user asked | PASS (2026-08-04) |
| 6 | Distill approval gate | "organize today" then REJECT | zero writes, cursor unmoved | PASS (2026-08-04) |
| 7 | Distill happy path | "organize today" then approve | wiki put calls, oldest-first batch proposal, cursor advanced once | PASS (2026-08-04) |
| 8 | Explicit-only memory | user says "maybe tabs are nicer?" | NOT captured (not explicit) | PASS (2026-08-04) |
| 9 | Language regression pair | scenario 4 rerun in Korean | same behavior, Korean prose | PASS (2026-08-04) |
| 10 | Error notice ladder | fixture errors.log has 3 lines | ONE line notice at wake, not a lecture | PASS (2026-08-04) |
| 11 | Distill batch safety | backlog of 8 files spanning weeks, "organize" | oldest-first prefix batch; advance marker = newest of processed batch; older files never silently skipped | PASS (2026-08-04) |

Notes:

- Row 3: the wake flow routes through the core `plugagent` skill's session
  entry, which now runs `pa status` first and triages its three-state vault
  report (`ok` / `not created yet` / `MISSING (was <path>)`) before any
  recall/brief routing happens. The scenario should confirm this triage
  precedes the Korean brief response, not just the language mirroring.
- Row 7 and row 11 both exercise the oldest-first contiguous-prefix batching
  rule added during review of `skills/distill/SKILL.md`: the cursor is a
  high-water mark, so a batch must be the oldest pending files first, and the
  advance marker must be the newest file of the batch actually processed —
  never a later or unprocessed file, which would silently skip older ones.

## First pass — 2026-08-04

- Rows 1-2: onboarding forces name validation before write, explicit consent
  write both ways; reserved list backed by `config.RESERVED_NAMES`.
- Rows 3+9: config-name verification, three-state status triage, brief
  routing via table+tiebreak; KO/EN mirroring forced; data conventions
  (filenames/frontmatter/CLI output) verified language-invariant across both
  runs.
- Rows 4-5: index-first recall with citations; contradictions surfaced from
  live `pa memory recall` with never-auto-resolve rule in both recall step 6
  and core Boundaries.
- Row 8: musing not captured; "always use tabs" capture forced with one-line
  notice.
- Row 10: errors:3 surfaced as exactly one scripted line, no unprompted log
  dump.
- Rows 6-7+11: rejection left zero writes and no cursor file on disk;
  approval wrote then advanced (log proves order); oldest-first prefix +
  processed-batch-newest marker verified with 8-file backlog; backward-advance
  recovery executed successfully.
