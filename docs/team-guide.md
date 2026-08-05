# PlugAgent Team Mode — Guide

Team mode lets a small group share **distilled wiki pages** through a private
git repository, encrypted end-to-end. It is opt-in and sits on top of the
Phase 1 personal features — nothing about your personal vault changes when you
join a team.

- **Bidirectional.** Every member can share pages and read everyone else's.
  There is no central server and no daemon; sync is a lazy git pull that runs
  when you ask your agent something team-related.
- **Encrypted at rest.** Page bodies are encrypted with
  [age](https://github.com/FiloSottile/age) before they ever leave your
  machine. The hosting provider (GitHub, etc.) stores ciphertext only.
- **Namespaced.** Each member owns a `members/<name>/` folder in the repo.
  You write only into your own; you read everyone's.

Team mode requires the `age` and `age-keygen` binaries (`brew install age` on
macOS). Personal mode never needs them — the dependency boundary is exactly
the team-mode toggle. Developed and tested on macOS.

## Leader setup (once)

1. Create an **empty** private repository (GitHub, GitLab, self-hosted — any
   git remote you can clone and push to). Do not add a README or license; init
   needs it empty.
2. Run:

   ```
   pa team init <team-name> --repo <url> --as <member-name>
   ```

   This generates the team keypair, commits `team.json` (the public recipient)
   to the repo, claims `<member-name>` as your own `members/` namespace, and
   prints the path to `team.key`. It is a single step — the leader is
   share-ready immediately, with no separate self-join. `<member-name>` follows
   the same rules as a member join (1–32 characters, lowercase
   letters/digits/hyphens).
3. **Distribute `team.key` to members over a secure channel** — a password
   manager's secure-note share, an encrypted message, in person. Never commit
   it, never post it in a public channel, never paste it into a chat log. Your
   agent will not send it for you; distribution is yours to do deliberately.

## Member join (once per machine)

Ask your agent "connect me to the team repo" for a guided wizard, or run it
directly:

```
pa team join <url> --key <path-to-team.key> --as <member-name>
```

- `<member-name>` is 1–32 characters, lowercase letters/digits/hyphens; it
  becomes your folder in the repo and cannot be changed later without
  abandoning your namespace.
- Join verifies the key against the repo's committed recipient (a trial
  encrypt/decrypt) and refuses if they do not match, so there is no
  half-working state.
- After a successful join, **delete the copy of `team.key` you were sent** (from
  Downloads, chat, etc.). The key now lives at
  `~/.plugagent/teams/<team>/team.key` with `0600` permissions.

Sharing a page: `pa team share concepts/auth.md` (a path inside your vault
`wiki/`). Only markdown wiki pages can be shared — never raw sessions, never
memory cards. Distill also offers to share pages it just wrote.

## What is and isn't protected

| | |
|---|---|
| Protected | Page **content** at rest on the host — ciphertext only. A repo leak reveals no page bodies. |
| Exposed (documented) | **Metadata**: member names, page paths (a path *is* the page title — `concepts/auth.md.age` reveals that an auth doc exists), and commit times/frequency. v1 keeps plaintext paths for simplicity and diff-ability. |
| Unprotected by design | Your **local decrypted cache** at `~/.plugagent/teams/<team>/cache/`. The threat model is the hosting provider, not your own machine (which already holds your raw sessions). |

## Member departure & re-keying (manual in v1)

Because all members share one key, **a departed member can still decrypt the
repo — past and future — until the team re-keys.** v1 ships the procedure, not
an automation (`pa team rekey` is deferred). Re-keying is a manual, leader-led
operation:

1. Leader generates a new keypair: `age-keygen -o team-new.key` (note the new
   `age1…` recipient it prints).
2. Leader redistributes `team-new.key` to the *remaining* members over a secure
   channel, and updates `recipient` in the repo's `team.json` to the new public
   key (commit + push).
3. Each member re-encrypts every page in their own `members/<name>/` namespace:
   decrypt each `*.age` with the **old** key, re-encrypt with the **new**
   recipient, commit, and push (force-replacing the old ciphertext).
4. Everyone replaces their local `~/.plugagent/teams/<team>/team.key` with the
   new key and runs `pa team sync --force`.

**Honest limitation:** the departed member keeps any copy of the old key and any
data they already pulled; re-keying only protects data written *after* the
re-key. During the transition, pages a member has not yet re-encrypted will
fail to decrypt for others — that is expected (see troubleshooting).

## Second-machine rejoin (deliberate namespace reuse)

`pa team join` refuses a member name that already exists in the repo — this is
the collision guard that stops two people from silently sharing a namespace. To
reuse *your own* namespace from a second machine, set it up by hand:

1. Get your `team.key` onto the second machine securely and clone the repo:
   `git clone <url> ~/.plugagent/teams/<team>/repo`.
2. Copy the key to `~/.plugagent/teams/<team>/team.key` and `chmod 600` it.
3. Create `~/.plugagent/teams/<team>/team.json` (the local config, distinct from
   the repo's committed `team.json`) with your existing member name:

   ```json
   {
     "repo_url": "<url>",
     "member": "<your-existing-name>",
     "last_sync": 0,
     "last_synced_commit": null,
     "decrypt_failures": [],
     "schema_version": 1
   }
   ```
4. Run `pa team sync --force` to build the local cache.

## Troubleshooting

- **`age` missing** — team commands refuse with `brew install age`. Install it
  and retry; personal features keep working regardless.
- **Key mismatch on join** — the received key does not match the repo's
  recipient. Ask the leader for the current `team.key` (a re-key may have
  happened).
- **Decrypt failures in `pa team status`** — usually a re-key in progress:
  pages not yet re-encrypted by their owner cannot be decrypted with the new
  key. Sync uses **skip-don't-poison**: it keeps the last good cached copy,
  counts the failure, and retries automatically on later syncs. Once the owner
  re-encrypts, the next sync resolves it.
- **Stale cache / offline** — if a sync pull fails (network down), your agent
  still answers from the last synced cache and adds a one-line "last synced N
  ago" notice. `pa team status` shows the exact age per team.
- **Corrupt or deleted clone** — re-clone the repo into
  `~/.plugagent/teams/<team>/repo` manually and `pa team sync --force`; the
  cache is kept and rebuilt.
