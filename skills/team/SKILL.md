---
name: team
description: >
  Team features for PlugAgent: join a team repository (wizard), share a wiki
  page with the team, explain team status, run the leader's init. Invoked via
  the core plugagent skill's routing on team intents ("connect me to the team
  repo", "share this with the team", "how's the team sync?").
---

# Team

Mirror the user's language. CLI base: `python3 "$CLAUDE_PLUGIN_ROOT/scripts/pa"` (`pa …`).
All team operations require the `age` tool; if a command fails with the install
hint, relay it in ONE line and stop.

## Join wizard ("connect me to the team")

1. Ask for the repository URL and where they saved the team.key file they
   received. Never accept a key pasted inline into chat — it should be a file;
   if they paste one, tell them to save it to a file and delete the chat copy.
   If the user has no key yet, tell them to get the team.key from the team
   leader over a secure channel before continuing. If they've already joined
   this team on this machine, the CLI will say so — offer `pa team sync`
   instead of re-joining.
2. Ask what member name they want — lowercase letters/digits/hyphens, max 32
   (this becomes their folder in the team repo). Suggest their agent-name
   lowercased if it fits.
3. Run `pa team join <url> --key '<path>' --as <member>`. On error, relay the
   one-line `pa:` message and help fix it (wrong key → ask the leader for the
   current team.key; taken name → suggest alternatives; schema mismatch →
   update the plugin).
4. On success, report the team size / page count line and mention: "your agent
   will now include teammates' shared pages in recall, with attribution."

## Leader init ("set up a team repo")

1. Confirm they have an EMPTY private repository ready and its URL.
2. Ask for the leader's own member name too (1–32 chars, lowercase
   letters/digits/hyphens — validate it before running), then run
   `pa team init <team-name> --repo <url> --as <member>`. This claims the
   leader's `members/` namespace in one step — they are share-ready
   immediately, with no separate self-join.
3. Relay the key-handling warning VERBATIM — the team.key must go to members
   over a secure channel and must never be committed or posted publicly. Never
   offer to send, forward, attach, or otherwise transmit the team.key on the
   user's behalf — over any channel or tool. The user distributes it themselves
   over a secure channel of their choosing.
4. Point them to docs/team-guide.md for member instructions and re-keying.

## Sharing ("share X with the team")

1. Identify the wiki page — a wiki page (relative path like `concepts/auth.md`);
   list `wiki/` matches if ambiguous. Only vault wiki pages can be shared: the
   input must be a `.md` page inside your vault wiki, never an absolute or
   escaping path, never raw sessions, never memory cards.
2. Confirm ONCE with the page name and team name, then run
   `pa team share <relpath> [--team T]`.
3. Relay the result: shared, or saved-pending-retry on network failure.

## Status ("how's the team sync?")

Run `pa team status` and present it in the user's language, per team, one line
each. If a team shows an ERROR line, mention re-keying or a corrupt config may
be the cause. If decrypt failures are listed, mention re-keying may be in
progress and point to the guide.

## Boundaries

- Never display, read aloud, copy, or move the team.key file's contents.
- Never offer to send, forward, attach, or otherwise transmit the team.key on
  the user's behalf — over any channel or tool. The user distributes it
  themselves over a secure channel of their choosing.
- Every share needs the user's explicit confirmation in this conversation.
- Team writes go ONLY through `pa team` commands.
