---
name: distill
description: >
  Turn recent raw sessions into distilled wiki knowledge, with user approval.
  Invoked when the user says "organize today's work", "정리해줘", or similar,
  via the core plugagent skill's routing.
---

# Distill

Mirror the user's language. **Nothing is written before the user approves.**

1. `pa distill pending` — list unprocessed raw files. If more than ~20,
   propose a batch from the OLDEST end of the `pa distill pending` output
   ("start with the oldest week?" / "the first N files?") and scope down.
   The cursor is a high-water mark: advancing to a file permanently skips
   every pending file that sorts before it. Batches must therefore be a
   contiguous prefix (oldest-first) of the pending list.
2. Read the pending raw files (read-only). Files with `parse_failed: true`
   frontmatter are pointer stubs with no distillable content — mention them
   to the user, do not draft wiki pages from them, and do not follow the
   `transcript:` path. Advancing past them is safe (a post-parser-fix
   re-capture lands as a new raw file).
3. Draft a proposal — for each suggested wiki change: target relpath
   (concepts/…, projects/…, decisions/…, patterns/…), one-line description,
   and a 2–4 line summary of what the page will say. Never propose `index.md`
   or an empty relpath as a target, and never a relpath that would escape the
   wiki directory (e.g. via `..`) — `pa wiki put` rejects all three. Present
   the whole proposal and ask for approval (allow per-item opt-out).
4. On approval, for each approved page:
   `pa wiki put <relpath>` with the full page content (frontmatter with
   `description:` + body) on stdin.
5. `pa distill advance --to <newest-file-of-the-processed-batch>` — only
   after all approved writes succeed, and only valid when every pending file
   sorting before that marker was processed in this run. The marker must be
   the exact filename of that file, exactly as printed by `pa distill
   pending` (not a date, not a partial name) — the CLI refuses any marker
   that doesn't name an existing raw file, and refuses outright if the vault
   is missing, both as a one-line `pa:` error. On a `pa:` error, stop and
   report it to the user rather than retrying blindly. If files were
   accidentally skipped, `pa distill advance --to <an-older-filename>` moves
   the cursor backward and they reappear in pending.
6. Report in one paragraph: pages written, cursor position, anything skipped.
7. If the user rejects everything: write nothing, do NOT advance the cursor,
   and say the raw files remain for a later pass.
8. Team offer (only if a team is configured — `pa team status` not saying
   "no team"): after ALL approved writes and the cursor advance are done, ask
   in ONE line: "any of the pages I just wrote worth sharing with the team?"
   If yes → per-page confirmation, then `pa team share <relpath>` each.
   Skip any page the user already shared earlier in this same turn — do not
   re-offer it. Declining ends the flow — never auto-share.

## Approval gate

The gate in step 3 is absolute: no `pa wiki put` and no `pa distill advance`
run before the user has approved the specific pages being written. Partial
approval is fine (write only the approved subset), but the cursor advance in
step 5 only happens after every approved write in that batch has succeeded —
if any `pa wiki put` fails, stop, report which pages wrote and which didn't,
and do not advance the cursor past raw files whose distillation didn't fully
land. A full rejection (step 7) or a failed write both leave the cursor
untouched, so the same raw files reappear in the next `pa distill pending`.
