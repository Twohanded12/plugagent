# PlugAgent

> **Status:** v0.3 — personal use plus opt-in, end-to-end-encrypted team
> sharing of the wiki layer, now with re-key automation for rotating a
> compromised or departing-member team key. Page content is encrypted at
> rest; metadata (member names, page paths, commit times) is not — see
> [Team mode](#team-mode-v03).

PlugAgent is a personal agent that learns you and records your work, running
entirely as a Claude Code plugin. While you work in normal Claude Code
sessions, a hook silently captures a gist of each session into a local
Markdown vault — no tokens spent, nothing injected into your workflow. When
you want something back, you call your agent by the name you gave it: recall
what you know about a topic, get a briefing of yesterday's work, or distill
recent raw sessions into a curated wiki. The more you use it, the more it
knows about how you like to work.

## Why PlugAgent

- **No daemon.** Everything automatic rides on official Claude Code hook
  events. There is no resident process, no cron job — nothing to keep alive,
  nothing that breaks when CLI policies change.
- **Subscription-leveraged.** Capture and indexing are token-free
  deterministic CLI work that runs at session end. You spend tokens only when
  you ask for something (recall, briefing, distillation). No API metering
  required.
- **Local-first.** Your data is plain Markdown in `~/PlugAgent/`, on your
  machine, readable in any editor. Nothing ever leaves your machine in
  Phase 1.

## Install

Requirements: the Claude Code desktop app, and `python3` on your PATH (the
macOS built-in is fine — the CLI is stdlib-only). Developed and tested on
macOS; the CLI is stdlib-only Python and the hook shim is POSIX sh, so Linux
should work but is untested. Windows is not supported yet.

```
/plugin marketplace add <path or git URL of this repository>
/plugin install plugagent@plugagent-marketplace
```

Then restart Claude Code so the capture hook registers.

## First run

```
/plugagent:setup
```

Setup does two things:

1. **Name your agent.** The name you choose becomes the wake word — you will
   address your agent by it from then on. Reserved words ("claude", skill
   names) are rejected with suggestions.
2. **Capture consent.** Session capture is an explicit choice, not a default
   you discover later. You can change it at any time (see
   [Your data](#your-data)).

The vault itself is created lazily by the first capture — no empty folders if
you never use it.

## Daily use

Address your agent by its name in any session (examples assume you named it
"Nova"), or use the slash commands. Your agent mirrors your language — speak
Korean and it answers in Korean.

| What | English | 한국어 |
|---|---|---|
| Recall | "Nova, what do we know about the auth decision?" | "노바야, 인증 관련해서 뭐 결정했었지?" |
| Brief | "Nova, what did I do yesterday?" | "노바야, 어제 뭐 했지?" |
| Distill | "Nova, organize today's work" | "노바야, 오늘 작업 정리해줘" |
| Remember | "Always run the linter before committing" | "커밋 전에 항상 린터 돌려줘" |
| Forget | "Forget that preference" | "그 취향은 잊어줘" |
| Status | `/plugagent:status` or "Nova, how are you doing?" | "노바야, 상태 어때?" |

Notes on behavior:

- **Distill never writes without approval.** It proposes wiki updates first;
  you approve (or opt out per item) before anything is written.
- **Learning is visible.** When your agent saves a preference card, it says
  so in one line ("noted: lint-before-commit"). Only explicit statements are
  captured — it does not guess at your tastes.
- **Recall cites its sources** — the wiki pages and raw session files it
  used. Contradictory records are shown side by side, never silently
  resolved.

## Your data

Everything lives in a visible folder at `~/PlugAgent/` — plain Markdown you
can open in any editor or Obsidian:

```
~/PlugAgent/
├── raw/sessions/                  # immutable layer — auto-appended, never edited
│   └── 2026-08-04-<slug>-<sid>.md #   session gist + excerpts, keyed by session_id
├── wiki/                          # distilled layer — pages written by distill
│   ├── index.md                   #   catalog (first read on any query)
│   ├── log.md                     #   one-line capture/distill history
│   └── concepts/ projects/ decisions/ patterns/
├── memory/                        # personalization layer
│   ├── MEMORY.md                  #   hot index (the only file loaded at session start)
│   └── cards/*.md                 #   one card = one fact
└── .state/                        # distill cursor
```

Controls (the `pa` CLI is `python3 scripts/pa` from this repository, or the
plugin's installed copy — your agent runs these for you when asked):

- **Raw is immutable to the agent.** Sessions are appended, never edited. The
  one sanctioned deletion path is an explicit request — "delete that
  session" — which runs `pa raw forget <session-id>` after confirming the
  exact file with you. (The vault is your folder; the immutability rule binds
  the agent, not you.)
- **Exclusion list.** Projects whose path is listed in
  `pa config set exclude '["~/private-project"]'` are never captured — the
  check lives in the capture CLI itself, so it holds even when no skill runs.
- **Kill switch.** `pa config set capture off` stops all capture globally;
  `on` resumes it.
- Machine config lives at `~/.plugagent/config.json`; capture error logs at
  `~/.plugagent/state/`. Capture failures never break your session — they
  are logged and surfaced as a one-line notice on the next wake.

## Team mode (v0.3)

Opt-in: a small group can share **distilled wiki pages** through a private git
repository, encrypted end-to-end with [age](https://github.com/FiloSottile/age).
Each member owns a namespace in the repo, writes only into their own, and reads
everyone's — with attribution — in recall. Raw sessions and memory cards never
leave your machine. Team mode is the only feature that needs `age`
(`brew install age`); personal mode stays dependency-free.

```
# leader, once (needs an empty private repo) — claims the "alice" namespace, share-ready:
pa team init acme --repo git@github.com:acme/brain.git --as alice
# then hand team.key to members over a secure channel — never commit or post it

# each other member, once per machine:
pa team join git@github.com:acme/brain.git --key ~/team.key --as bob
```

Then `pa team share concepts/auth.md` shares a page, and asking your agent
"what do we know about X?" folds in teammates' shared pages. Rotate the team
key with `pa team rekey` (members then run `pa team rekey-accept`) — forward
secrecy only; see the guide. **Honesty note:**
page *content* is encrypted at rest, but *metadata* — member names, page paths
(a path is the page title), and commit times — is visible to whoever hosts the
repo. Full details, the departure/re-key procedure, and troubleshooting are in
[`docs/team-guide.md`](docs/team-guide.md).

## Roadmap

Team sharing of the wiki layer and re-key automation (`pa team rekey` /
`pa team rekey-accept` — forward-secrecy only) have both landed (see above).
Still ahead: memory-card sharing and filename/metadata privacy (paths are
currently plaintext). Raw transcripts never leave your machine. Verification
records for the current release live in
[`docs/verification/`](docs/verification/).

## License

[MIT](LICENSE).

---

Bug reports and questions: GitHub Issues. Contributions welcome once Phase 1
stabilizes.
