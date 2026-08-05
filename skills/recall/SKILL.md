---
name: recall
description: >
  Answer "what do I know / what did we decide about X?" from the PlugAgent
  vault. Invoked via the core plugagent skill's routing.
---

# Recall

Mirror the user's language. Vault root: `pa config get vault` (default `~/PlugAgent`).

1. Read `wiki/index.md`; pick candidate pages by name/description. If
   `wiki/index.md` does not exist, the wiki is empty (nothing distilled
   yet) — go straight to steps 3-4 and say so in the answer.
2. Read the top 1–3 matching pages fully. Follow one hop of links if needed.
2b. If a team is configured, run `pa team sync` (TTL makes this cheap — a
    "sync skipped (within TTL…)" or a "serving stale cache" message is normal
    and non-blocking, keep going). Whether or not sync succeeded, check the
    aggregate team cache index at `~/.plugagent/teams/<team>/cache/index.md`:
    if it exists, READ it and open any matching member pages at
    `~/.plugagent/teams/<team>/cache/members/<m>/wiki/…` — these are
    plaintext and already decrypted from a prior sync, so a sync error (e.g.
    age not installed, network failure) does not make them unreadable. Its
    lines look like `- members/bob/wiki/concepts/auth.md — JWT decision
    (bob)`. Team citations MUST carry attribution: "(teammate bob's shared
    page)". If `pa team sync` reported a failure, still use the cache but add
    ONE line: "team data may be stale (last sync couldn't refresh)". Do NOT
    surface a raw age-install hint mid-recall — this is a read flow, degrade
    silently on that front.
    Only treat the team as "no team pages available" and fall back to
    personal sources alone when the cache index does not exist at that path
    at all (e.g. no sync has ever succeeded).
    My-page vs teammate-page contradictions follow the same ⚠️ rule as any
    other contradiction: show both, ask, never auto-resolve.
3. Check memory: `pa memory recall '<keyword>'` (shell-quoted; CLI, so stats
   update). Matching is case-insensitive substring, so a short, distinctive
   keyword works better than a long phrase.
4. If wiki is thin, grep `raw/sessions/` for the keyword and read matching
   session files (read-only).
5. Answer with citations — name the wiki pages / raw files used.
6. Contradictions between sources: present both with a ⚠️ marker and ask the
   user which is current. Never silently pick one.

This skill is read-only: steps above only ever read (wiki/raw files directly,
or `pa memory recall`/`pa memory show`, which read but also bump usage stats).
Nothing here writes to the vault — routes that need to record something
(preference capture, forgetting, distilling) belong to the core skill or to
skills/distill, not here.
