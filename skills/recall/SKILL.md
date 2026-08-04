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
