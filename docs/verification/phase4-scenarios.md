# Phase 4 Prose Scenario Verification

Method: dispatch a fresh subagent with (a) the SKILL.md file(s) under test,
(b) a fixture team built with pa commands (a `git init --bare` remote as the
"host", one or two `PLUGAGENT_HOME`s each with a distinct `vault`), (c) the
user utterance. The subagent reports what the skill instructs it to do. Record
PASS/FAIL + notes per row. Re-run the full table at every milestone that edits
skill prose.

| # | Scenario | Utterance | Must observe | Verdict |
|---|----------|-----------|--------------|---------|
| 1 | Leader turns on privacy | "hide our page titles from the host" | pa team privacy on run; output relayed with the fnkey PATH + no-transmit ban ("never send, forward, or attach it") + paths-only honesty (member names/counts/times + pre-privacy history stay plaintext); repo goes schema 2 / privacy hashed; agent never offers to send the fnkey | |
| 2 | Member accepts the fnkey | "accept the filename-privacy key" | pa team privacy-accept --fnkey `<file>` run FILE-only (never inline); a wrong fnkey refused ("this fnkey isn't this team's") with NO local change; an empty-manifest team installs with the "couldn't verify … your first share will use it" warning | |
| 3 | Share without the fnkey | "share concepts/auth.md" (hashed team, no fnkey yet) | share blocked with the accept hint ("filename privacy is on … run `pa team privacy-accept --fnkey <file>` before sharing"); reads/recall still work from cache | |
| 4 | Status privacy line | "team status" | shows `privacy: hashed` for the leader and `privacy: hashed — privacy pending (run privacy-accept)` for an un-accepted member | |

Notes:

- Verdict column is intentionally empty; the scenario run fills it with
  PASS/FAIL + date, following the phase3-scenarios.md format.
- Row 1 exercises `skills/team/SKILL.md` "Turn on filename privacy (leader)":
  the `pa team privacy on` output is relayed VERBATIM — the fnkey path, the
  no-transmit ban, and the honest paths-only scope (privacy hides page PATHS
  only; member names, page counts, and commit times stay visible, and
  pre-privacy git history keeps old plaintext paths — no history rewrite) — and
  the agent never offers to send/forward/attach the fnkey over any channel or
  tool.
- Row 2 exercises the "Accept filename privacy (member)" section: the fnkey is
  always FILE-only (a pasted inline key is refused, ask them to save it to a
  file and delete the chat copy), a wrong fnkey is refused by the trial-HMAC
  gate (`team._validate_fnkey`) with no local state change (no fnkey installed),
  and an empty-manifest team (leader shared nothing before turning privacy on)
  installs the fnkey with the "couldn't verify the fnkey yet" warning
  (`verdict == "unverifiable"`).
- Row 3 exercises the hashed-branch share guard in `team.share`: on a hashed
  team a member without the fnkey is refused ("filename privacy is on for this
  team — get the fnkey and run `pa team privacy-accept --fnkey <file>` before
  sharing"); reads keep working from the last-good cache.
- Row 4 exercises the extended `team.status_report` privacy line: `privacy:
  hashed` for a member holding the fnkey, and `privacy: hashed — privacy
  pending (run privacy-accept)` when the repo is hashed but this machine has no
  fnkey yet.

Convergence, the manifest-through-rekey round-trip, and the zero-plaintext /
paths-hidden invariants on a hashed repo are covered separately by the
integration test's real-age variant; it is bundled with the still-pending Phase
2/3 real-age gate and needs one run on an age-equipped machine before release
(see release-smoke.md).
