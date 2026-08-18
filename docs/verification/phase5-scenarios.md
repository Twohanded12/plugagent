# Phase 5 Prose Scenario Verification

Method: dispatch a fresh subagent with (a) the SKILL.md file(s) under test,
(b) a fixture team built with pa commands (a `git init --bare` remote as the
"host", two `PLUGAGENT_HOME`s each with a distinct `vault`, each with a few
personal memory cards), (c) the user utterance. The subagent reports what the
skill instructs it to do. Record PASS/FAIL + notes per row. Re-run the full
table at every milestone that edits skill prose.

| # | Scenario | Utterance | Must observe | Verdict |
|---|----------|-----------|--------------|---------|
| 1 | Promote one memory card | "share my lint-before-commit card with the team" | the USER's named card only — the agent never picks one itself; confirmed once by card + team name, then `pa team share-card lint-before-commit`; the FIRST promotion on a team is refused with the schema-3 lockout warning, relayed verbatim, and only re-run with `--confirm-schema-bump` after the user says yes; success line relayed ("usage statistics were stripped; your personal card is unchanged"); the personal card file is byte-identical afterwards | |
| 2 | A received card in the hot index | "what does the team know about linting?" / "show me my memory" | `pa memory list` shows a `## Team cards (read-only)` section with `- lint-before-commit — <desc> (team: alice)`; `pa memory show lint-before-commit` prints the `(team: alice, read-only)` header; a same-named personal card wins and the team line is marked `(shadowed by your card)`, never dropped; a name shared by two members asks for `pa memory show <name> --from <member>` | |
| 3 | Turn received cards off | "stop mixing the team's memory cards into mine" | `pa team memory off [--team T]` run; output relayed including "local only — teammates are not told"; the `## Team cards` section is gone from `pa memory list` in the SAME session (no second command needed); `pa team status` appends `(team memory off)` to the card line; team WIKI pages keep syncing and keep showing up in team recall | |
| 4 | Withdraw a promoted card | "stop sharing that card with the team" | `pa team unshare-card lint-before-commit [--team T]` run after one confirmation; the forward-only sentence relayed VERBATIM and not softened ("This stops FUTURE access only — anyone who already cloned the repository keeps the old ciphertext from its history"); the receiver loses the card from their hot index on their next sync; the personal card is still there locally; a card that was never promoted is refused with "is not shared with team" | |

Notes:

- Verdict column is intentionally empty; the scenario run fills it with
  PASS/FAIL + date, following the phase4-scenarios.md format.
- Row 1 exercises `skills/team/SKILL.md` "Share a memory card": promotion is
  **per card and user-named** — the agent never volunteers a card, never
  batches, and never promotes as a side effect of another task. The first
  promotion on a team raises the repo `schema_version` to 3, which locks
  un-upgraded teammates (v0.4.0) out of the team layer, so `team.share_card`
  refuses until `--confirm-schema-bump` is passed: "this is the first memory
  card on this team, which raises the repo schema to 3 — teammates still on
  v0.4.0 will be locked out of the team layer until they upgrade." That
  consent gate fires **before any filesystem write**, so a refusal leaves
  nothing behind. Stripping is an allowlist (`memory.build_promotion` keeps
  `name`/`description`/`type` + body), so `uses:`, `last_used:`, `created:`
  and any hand-added key never ship; the personal card is read only.
  On a hashed team a member without the fnkey is refused with the same accept
  hint `pa team share` gives.
- Row 2 exercises the fold-in in `memory.rebuild_index` plus the read-only
  fallback in `memory.show`/`memory.recall`. Team cards are appended under a
  `## Team cards (read-only)` heading with `(team: <member>)` attribution; a
  personal card of the same name shadows it (personal body wins in `show`,
  personal hit comes first in `recall`, team line marked
  `(shadowed by your card)`). A team hit is never bumped and never written
  into the personal vault, so a teammate's card cannot silently become the
  receiver's own and be re-promoted under their name. Two members sharing one
  name gives the `--from <member>` disambiguation message.
- Row 3 exercises `team.set_team_memory` and the switch `team.cards_for_index`
  reads. The flag is written to the **local** `team.json` only — the repo copy
  is shared state, so opting out never tells the team who stopped reading.
  `set_team_memory` rebuilds `MEMORY.md` immediately, because that file is what
  a session loads at start-up; without the rebuild the switch would appear to
  do nothing until the next unrelated memory command. The off switch must have
  no side door: `team._rebuild_index` keeps memory cards out of the team wiki
  index, and `skills/brief` skips the `memory/` root when it walks the team
  cache, so a briefing cannot resurface cards the user switched off.
- Row 4 exercises `team.unshare_card`. It needs **no fnkey** by design: on a
  hashed team the member reverse-looks-up their own hash in their own manifest
  with the age key alone, so a member who never accepted filename privacy can
  still withdraw. Withdrawal is forward-only — the blob leaves HEAD and the
  receiver's cache on the next sync, but the ciphertext stays in git history
  and anyone who already cloned keeps it. That sentence is the command's own
  output; relay it, do not soften it.

The zero-unpromoted-cards / zero-statistics invariant over **all** git objects
(not just HEAD) is covered by the real-age variant in
`tests/test_team_memory_integration.py`; it is bundled with the still-pending
real-age gate and needs one run on an age-equipped machine before release
(see release-smoke.md).
