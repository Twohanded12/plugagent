---
name: onboard
description: >
  First-run setup for PlugAgent. Use when the user wants to set up PlugAgent,
  invokes /plugagent:setup, or addresses their personal agent before any agent
  name exists in config (`python3 "$CLAUDE_PLUGIN_ROOT/scripts/pa" config get agent_name`
  returns None). Names the agent, records capture consent, defers vault
  creation to first capture.
---

# PlugAgent Onboarding

**Language rule: mirror the user.** Detect the language of the user's first
utterance and conduct the whole onboarding in it (Korean → Korean, English →
English). Follow mid-conversation switches.

All shell calls below use the CLI: `python3 "$CLAUDE_PLUGIN_ROOT/scripts/pa" …`
(referred to as `pa …`).

## Steps

1. **Check state.** `pa config get agent_name`. If no name exists, proceed to
   step 2. A name existing does not by itself mean onboarding finished — a
   prior session may have died between naming (step 2) and consent (step 3).
   If there is any doubt whether capture was consciously chosen, resume from
   the first incomplete step rather than declaring onboarding done — in
   practice: re-ask the consent question (step 3). Only once naming and an
   explicit capture choice are both confirmed, say onboarding is done and show
   `pa status --full` instead. Renaming later is possible via
   `pa config set agent_name '<new>'`, after confirming the new name with the
   user and telling them the old name will no longer wake the agent.
2. **Name the agent.** Ask: "What would you like to call your agent? This name
   becomes how you summon it." Extract the intended name from the reply —
   users often answer in a sentence ("hmm, maybe Nova?") rather than a bare
   name; if the utterance wasn't just the name, confirm the extracted name
   back with the user before writing. Validate it: not empty and not a
   reserved word (claude, plugagent, assistant, agent, pa — case-insensitive).
   If reserved, explain and ask again with two alternative suggestions. Once
   confirmed, write it with the value shell-quoted:
   `pa config set agent_name '<name>'`.
3. **Explain the vault, get consent for capture.** One short paragraph: sessions
   will be silently captured into `~/PlugAgent/` (a plain folder of Markdown the
   user can open anytime), nothing ever leaves the machine, and capture can be
   turned off with one command. Ask whether to enable capture now.
   - Whatever the answer, always write the setting explicitly — this write is
     what marks consent as given: Yes → `pa config set capture on`.
     No → `pa config set capture off`.
4. **Check status.** `pa status --full` — this exercises config; then mention
   the vault folder will be created on first capture (no empty scaffolding).
5. **Offer exclusions.** Ask if any project paths should never be captured;
   for each, add to the exclusion list via
   `pa config set exclude '["<path1>", "<path2>"]'` (full list each time —
   this is a full-replacement write, not an append). If the exclusion list
   is already non-empty, first read the current value with
   `pa config get exclude` so the new write preserves the existing entries.
6. **Close.** Greet the user by the agent's new name, in the user's language,
   and give three example invocations (recall, brief, "organize today").

## Hard rules

- Never proceed past step 2 without a valid name — everything else keys off it.
- Never enable capture silently; step 3's consent is explicit.
- If the user asks to use agent features (recall, briefing, etc.) mid-onboarding,
  explain the vault is empty until capture begins, then finish onboarding first.
- If any `pa` command errors mid-flow, report the failure and stop — do not
  proceed to the closing greeting as if setup completed.
