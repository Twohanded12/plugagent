"""Team layer flows and local team config. Policy lives here; git and crypto
mechanisms live in teamgit/teamcrypto."""
import datetime as _dt
import json
import re
import time
from pathlib import Path

from pa import config, teamgit

SCHEMA_VERSION = 1
SYNC_TTL_SECONDS = 900
# Stricter than the wake-word rules: the member name becomes a git path
# segment and the namespace-enforcement key (spec §3 Flow 2).
_MEMBER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class TeamError(Exception):
    pass


def member_name_error(name: str):
    if not _MEMBER_RE.fullmatch(name or ""):
        return (f"invalid member name {name!r} — use 1-32 chars of "
                "lowercase letters, digits, hyphens (must start alphanumeric)")
    return None


def teams_root() -> Path:
    return config.home() / "teams"


def team_dir(name: str) -> Path:
    if not _MEMBER_RE.fullmatch(name or ""):
        raise TeamError(f"invalid team name {name!r} — use 1-32 chars of "
                        "lowercase letters, digits, hyphens")
    return teams_root() / name


def repo_dir(name: str) -> Path:
    return team_dir(name) / "repo"


def cache_dir(name: str) -> Path:
    return team_dir(name) / "cache"


def key_path(name: str) -> Path:
    return team_dir(name) / "team.key"


def prev_key_path(name: str) -> Path:
    return team_dir(name) / "team.key.prev"


def load_local(name: str) -> dict:
    p = team_dir(name) / "team.json"
    if not p.exists():
        raise TeamError(f"unknown team {name!r}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TeamError(f"corrupt team config {p}: {e}")


def save_local(name: str, cfg: dict) -> None:
    d = team_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "team.json").write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_teams() -> list[str]:
    if not teams_root().exists():
        return []
    return sorted(p.name for p in teams_root().iterdir()
                  if (p / "team.json").exists())


def resolve_team(name):
    teams = list_teams()
    if name is not None:
        if name not in teams:
            raise TeamError(f"unknown team {name!r} — known: {teams or 'none'}")
        return name
    if not teams:
        raise TeamError("no team configured — run `pa team init` or `pa team join`")
    if len(teams) == 1:
        return teams[0]
    raise TeamError(f"multiple teams ({', '.join(teams)}) — pass --team")


def needs_sync(last_sync: float, ttl: int = SYNC_TTL_SECONDS, now=None) -> bool:
    now = time.time() if now is None else now
    return last_sync == 0 or (now - last_sync) >= ttl


def _local_generation(cfg: dict) -> int:
    return cfg.get("key_version", 1)


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def init_team(name: str, repo_url: str, member: str) -> str:
    from pa import teamcrypto, teamgit
    teamcrypto.require_age()
    err = member_name_error(member)
    if err:
        raise TeamError(err)
    import shutil as _sh
    # Marker-based guard: (team_dir/"team.json") — the local config file
    # written by save_local() — is the only "this team is fully set up"
    # marker. A team_dir that exists WITHOUT it is debris from a killed
    # earlier attempt (init writes the key + clones the repo before it ever
    # calls save_local), not a real collision — wipe it and proceed.
    if (team_dir(name) / "team.json").exists():
        raise TeamError(f"team {name!r} already exists locally")
    _sh.rmtree(team_dir(name), ignore_errors=True)
    try:
        recipient, _identity = teamcrypto.keygen(team_dir(name))
        teamgit.clone(repo_url, repo_dir(name))
        repo = repo_dir(name)
        if any(p for p in repo.iterdir() if p.name != ".git"):
            raise TeamError("repository is not empty — init needs an empty repo")
        (repo / "team.json").write_text(json.dumps(
            {"name": name, "recipient": recipient, "schema_version": SCHEMA_VERSION},
            indent=2) + "\n", encoding="utf-8")
        import subprocess
        subprocess.run(["git", "-C", str(repo), "add", "team.json"], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "team: init"],
                       check=True, capture_output=True)
        teamgit.push_with_rebase(repo)
        save_local(name, {"repo_url": repo_url, "member": member, "last_sync": 0,
                          "last_synced_commit": None, "decrypt_failures": [],
                          "schema_version": SCHEMA_VERSION})
    except Exception:
        # team_dir(name) was wiped clean (or absent) right before this try,
        # so it's always safe to wipe it again on any failure — no orphaned
        # key+repo left behind that would make "already exists" lie to a retry.
        _sh.rmtree(team_dir(name), ignore_errors=True)
        raise
    return (f"team {name!r} initialized. Hand {key_path(name)} to members over a "
            "secure channel — never commit it or post it publicly.")


def _read_committed_meta(repo: Path) -> dict:
    meta_path = repo / "team.json"
    if not meta_path.exists():
        raise TeamError("not a PlugAgent team repository (no team.json)")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TeamError(f"corrupt team.json in repository: {e}")
    if not isinstance(meta.get("name"), str):
        raise TeamError("not a valid PlugAgent team repository (bad team.json: name)")
    if not isinstance(meta.get("recipient"), str):
        raise TeamError("not a valid PlugAgent team repository (bad team.json: recipient)")
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise TeamError("team repo schema_version mismatch — update the plugin")
    # key_version is additive (spec §2): absent on legacy Phase 2 repos = gen 1.
    # Never gate schema_version on it.
    meta["key_version"] = meta.get("key_version", 1)
    return meta


def _copy_key_600(src: Path, dest: Path) -> None:
    """Copy the key with the destination created O_EXCL 0o600 from the first
    byte — never a window where the key sits world/group-readable."""
    import os
    data = src.read_bytes()
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def join_team(repo_url: str, received_key: Path, member: str) -> str:
    from pa import teamcrypto, teamgit
    teamcrypto.require_age()
    err = member_name_error(member)
    if err:
        raise TeamError(err)
    if not received_key.exists():
        raise TeamError(f"key file not found: {received_key}")
    import shutil as _sh, tempfile
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "repo"
        teamgit.clone(repo_url, probe)
        meta = _read_committed_meta(probe)
        name = meta["name"]
        # Identity-based guard (T4 carry-forward, mirrors init_team): a local
        # team.json marks this team as set up on this machine, but only a
        # NON-None member means an actually-claimed identity. A team.json with
        # member:None is a leader who ran `pa team init` (share-ready now, but
        # a coherent self-join target too); a markerless team_dir is debris
        # from a killed earlier attempt. Neither is a completed join — wipe and
        # proceed rather than lying to the user about "already joined".
        marker = team_dir(name) / "team.json"
        if marker.exists():
            try:
                existing = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            if existing.get("member"):
                raise TeamError(f"already joined team {name!r} on this machine")
        _sh.rmtree(team_dir(name), ignore_errors=True)
        if not teamcrypto.verify_key(received_key, meta["recipient"]):
            raise TeamError("key does not match this team's recipient — "
                            "ask the leader for the current team.key")
        if (probe / "members" / member).exists():
            raise TeamError(f"member name {member!r} already taken — pick another "
                            "(re-joining from a new machine? see the team guide)")
        # From here, config presence (save_local, last) is the "join
        # completed" marker list_teams() already treats as truth — so the
        # key copy and repo move must land BEFORE it, and any failure along
        # the way must wipe the partial team_dir so a retry doesn't hit
        # "already joined" on a team that was never actually joined.
        try:
            team_dir(name).mkdir(parents=True, exist_ok=True, mode=0o700)
            _copy_key_600(received_key, key_path(name))
            _sh.move(str(probe), str(repo_dir(name)))
            save_local(name, {"repo_url": repo_url, "member": member, "last_sync": 0,
                              "last_synced_commit": None, "decrypt_failures": [],
                              "schema_version": SCHEMA_VERSION})
        except Exception:
            _sh.rmtree(team_dir(name), ignore_errors=True)
            raise
    summary = sync(name, force=True)
    return (f"joined team {name!r} as {member!r}. {summary} Delete the received "
            "key copy you were sent (e.g. from Downloads/chat) — it now lives "
            "in your PlugAgent config.")


def share(name: str, relpath: str) -> str:
    from pa import teamcrypto, teamgit
    teamcrypto.require_age()
    cfg = load_local(name)
    if not cfg.get("member"):
        raise TeamError("no member identity for this team — join first")
    repo = repo_dir(name)
    # Pull first so the generation gate and the recipient are evaluated against
    # fresh remote state, not a stale clone (spec §4 gate 3). A network failure
    # here fails the share closed rather than encrypting with a stale key.
    _pull_or_fail(repo)
    repo_gen = _read_committed_meta(repo)["key_version"]
    if _local_generation(cfg) < repo_gen:
        raise TeamError(
            f"team rekeyed to v{repo_gen} — run `pa team rekey-accept` first, "
            "then re-share")
    wiki = config.vault() / "wiki"
    page = wiki / relpath
    if not page.resolve().is_relative_to(wiki.resolve()):
        raise TeamError("share input must be inside your vault wiki")
    # Re-derive relpath from the resolved, already-verified-contained page
    # rather than trusting the caller's string from here on. This collapses
    # "./", "//", "a/../b" — and, critically, an ABSOLUTE relpath: pathlib's
    # "/" operator drops the left operand whenever the right one is
    # absolute, so `wiki / relpath` above silently became just `relpath`
    # again, and the same trick later turned `repo / "members" / m / "wiki"
    # / (relpath + ".age")` into the absolute path itself — writing the
    # encrypted blob as a sibling of the original page inside the vault
    # wiki instead of into the repo (and leaving nothing staged, so the
    # commit below would fail on an empty tree).
    relpath = str(page.resolve().relative_to(wiki.resolve()))
    if not relpath.endswith(".md"):
        raise TeamError("only markdown wiki pages can be shared")
    page = wiki / relpath
    if not page.exists():
        candidates = [str(p.relative_to(wiki)) for p in wiki.rglob("*.md")][:5]
        raise TeamError(f"no such wiki page {relpath!r} — nearby: {candidates}")
    meta = _read_committed_meta(repo)
    blob = teamcrypto.encrypt(meta["recipient"], page.read_bytes())
    dest = repo / "members" / cfg["member"] / "wiki" / (relpath + ".age")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    dest_rel = dest.relative_to(repo).as_posix()
    import subprocess
    subprocess.run(["git", "-C", str(repo), "add", dest_rel], check=True, capture_output=True)
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", dest_rel],
                            capture_output=True, text=True)
    if not status.stdout.strip():
        return f"nothing new to share for {relpath!r} (already up to date)"
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", f"share: {relpath}"],
                   check=True, capture_output=True)
    try:
        teamgit.push_with_rebase(repo)
    except teamgit.PushError as e:
        return (f"shared {relpath!r} locally; push failed ({e}) — "
                "will retry on next sync")
    # Residual rekey-vs-share race (spec §4 gate 3): the rebase above may have
    # pulled in a rekey that landed between our pull-gate check and this push
    # — that rebase touches only members/<me>/… (no team.json conflict) so it
    # succeeds, but the blob we just pushed would be old-generation. Catch it
    # here; the page is already pushed but the user must accept the new key
    # and re-share so the stale-generation blob gets superseded.
    try:
        pushed_gen = _read_committed_meta(repo)["key_version"]
    except TeamError:
        pushed_gen = _local_generation(cfg)   # can't assess; don't sink a completed share
    if _local_generation(cfg) < pushed_gen:
        raise TeamError("team rekeyed during share — your page was pushed but under "
                        "the old generation; run rekey-accept and re-share to supersede it")
    # Deliberately do NOT touch last_sync/last_synced_commit here: the rebase
    # may have pulled in teammate commits we haven't decrypted yet — advancing
    # the cursor would permanently skip them. Let sync do all cursor movement.
    # sync()'s own push_with_rebase here is a tolerated no-op — we already
    # pushed above, so it has nothing pending to send.
    sync(name, force=True)
    return f"shared {relpath!r} with team {name!r}"


def sync(name, force: bool = False) -> str:
    from pa import teamcrypto, teamgit
    cfg = load_local(name)
    if not force and not needs_sync(cfg.get("last_sync", 0)):
        return "sync skipped (within TTL — use --force to override)"
    teamcrypto.require_age()
    repo = repo_dir(name)
    try:
        teamgit.push_with_rebase(repo)      # push pending, then we pull below
    except teamgit.PushError as e:
        if _is_dirty(repo):
            return _dirty_sync_message(repo)
        return f"sync failed (network?): {e} — serving stale cache"
    import subprocess
    pulled = subprocess.run(["git", "-C", str(repo), "pull", "-q", "--rebase"],
                            capture_output=True, text=True)
    if pulled.returncode != 0:
        if _is_dirty(repo):
            return _dirty_sync_message(repo)
        return f"sync failed (network?): {teamgit._first_line(pulled.stderr)} — serving stale cache"
    meta = _read_committed_meta(repo)
    changed = teamgit.changed_age_files(repo, cfg.get("last_synced_commit"))
    # Retry previously-failed decrypts even when unchanged (re-key transitions:
    # skip-don't-poison means skipped, not forgotten)
    retry = [(rel, "M") for rel in cfg.get("decrypt_failures", [])
             if (rel, "M") not in changed and (rel, "A") not in changed]
    failures = []
    written = 0
    deleted = 0
    for rel, status in changed + retry:
        src = repo / rel
        dest = cache_dir(name) / rel[: -len(".age")]
        if status == "D":
            # changed_age_files() reports both plain deletions and the
            # vacated side of a rename as "D" — remove the stale cache copy
            # directly here rather than waiting on the orphan sweep (which
            # stays on as a backstop for anything this loop doesn't see,
            # e.g. cache entries orphaned by a run that crashed mid-sync).
            if dest.exists() or dest.is_symlink():
                dest.unlink()
                deleted += 1
            continue
        if src.is_symlink():
            # A teammate's repo should never contain a symlinked .age file —
            # decrypting through one could read/leak anything on this
            # machine that the link target points at. Treat it as a
            # decrypt failure (suspicious), never follow it. Checked before
            # src.exists() on purpose: exists() follows symlinks and would
            # report False (silently skipping, no failure recorded) for a
            # symlink whose target happens to be absent right now.
            failures.append(rel)
            continue
        if not src.exists():                # deleted upstream
            continue
        blob = src.read_bytes()
        try:
            data = teamcrypto.decrypt(key_path(name), blob)
        except teamcrypto.DecryptError:
            prev = prev_key_path(name)
            if prev.exists():
                try:
                    data = teamcrypto.decrypt(prev, blob)
                except teamcrypto.DecryptError:
                    failures.append(rel)
                    continue
            else:
                failures.append(rel)
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            # Refuse to follow a symlink on the write side either — never
            # write decrypted content through a link some prior state left
            # behind.
            dest.unlink()
        dest.write_bytes(data)
        written += 1
    _remove_cache_orphans(name)
    _rebuild_index(name)
    cfg["last_sync"] = time.time()
    cfg["last_synced_commit"] = teamgit.head_commit(repo)
    cfg["decrypt_failures"] = failures
    save_local(name, cfg)
    msg = f"synced team {name!r}: {written} page(s) updated"
    if deleted:
        msg += f", {deleted} removed"
    if failures:
        msg += f", {len(failures)} file(s) failed to decrypt (kept last good copy)"
    repo_gen = meta["key_version"]
    if repo_gen > _local_generation(cfg):
        msg += (f". team rekeyed to v{repo_gen} — get the new team.key and run "
                "`pa team rekey-accept --key <file>` to resume sharing")
    return msg


def _is_dirty(repo: Path) -> bool:
    """True if `repo` has any uncommitted change to a tracked file (`git
    status --porcelain` non-empty). Shared by `_pull_or_fail` (raises) and
    `sync` (returns a string) so both distinguish a LOCAL dirty-tree
    condition — which fails `git pull --rebase` regardless of network state —
    from a genuine network/remote failure (commit d6e43b5 / this fix)."""
    import subprocess
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                         capture_output=True, text=True)
    return bool(out.stdout.strip())


def _dirty_sync_message(repo: Path) -> str:
    # sync() fails SOFT (returns a string, never raises) — this is the
    # sync-flavored counterpart to _pull_or_fail's _dirty_error(), naming the
    # same `git checkout -- .` recovery so the guidance is consistent across
    # share/rekey (which raise via _pull_or_fail) and sync (which doesn't).
    return (f"sync deferred: {repo} has uncommitted changes (an earlier team "
            "operation may have been interrupted) — resolve with "
            f"`git -C {repo} checkout -- .` and retry")


def _pull_or_fail(repo: Path) -> None:
    import subprocess
    # push any pending local commits first (so our own prior shares land),
    # then pull --rebase. Fail closed on error.
    from pa import teamgit

    def _dirty_error() -> TeamError:
        # Issue I1 defense: a dirty tree fails `pull --rebase` LOCALLY ("cannot
        # pull with rebase: you have unstaged changes") — never mislabel that as
        # a network problem. rekey/rekey-accept clean the tree before calling
        # here, so this catches any OTHER interrupted-operation dirty state.
        return TeamError(
            f"local repo has uncommitted changes ({repo}) — an earlier team "
            "operation may have been interrupted; resolve with "
            f"`git -C {repo} checkout -- .` and retry")

    try:
        teamgit.push_with_rebase(repo)
    except teamgit.PushError as e:
        if _is_dirty(repo):
            raise _dirty_error()
        raise TeamError(f"cannot reach team remote: {e}")
    pulled = subprocess.run(["git", "-C", str(repo), "pull", "-q", "--rebase"],
                            capture_output=True, text=True)
    if pulled.returncode != 0:
        if _is_dirty(repo):
            raise _dirty_error()
        raise TeamError(f"cannot reach team remote: {teamgit._first_line(pulled.stderr)}")


def _reencrypt_namespace(repo: Path, member: str, new_key: Path,
                         prev_key: Path, new_recipient: str) -> list[str]:
    """Re-encrypt every .age under members/<member>/wiki/ from prev_key to new_recipient.

    Idempotent: a blob that already decrypts under new_key is this generation
    and is skipped. A blob that decrypts under neither is corrupt/unknown —
    skipped and counted (never modified, so the original is never lost).
    Writes are atomic (temp file + os.replace).

    The caller MUST keep prev_key available until this returns cleanly — a
    crash-resume re-run needs it to rotate still-old-generation blobs;
    retiring prev_key on a partial run strands them as failures."""
    import os
    from pa import teamcrypto
    base = repo / "members" / member / "wiki"
    failures = []
    if not base.exists():
        return failures
    for age_file in sorted(base.rglob("*.age")):
        if age_file.is_symlink():
            # mirror sync()'s guard: never read through a symlink here either
            # — the target could be anything outside the repo.
            failures.append(str(age_file.relative_to(repo)))
            continue
        blob = age_file.read_bytes()
        try:
            teamcrypto.decrypt(new_key, blob)
            continue                              # already this generation
        except teamcrypto.DecryptError:
            pass
        try:
            data = teamcrypto.decrypt(prev_key, blob)
        except teamcrypto.DecryptError:
            failures.append(str(age_file.relative_to(repo)))
            continue
        new_blob = teamcrypto.encrypt(new_recipient, data)
        tmp = age_file.with_name(age_file.name + ".tmp")
        tmp.write_bytes(new_blob)
        os.replace(tmp, age_file)                 # atomic
    return failures


def _rekey_marker(name: str) -> Path:
    # Local-only (never in git) record of an in-progress rotation's target,
    # written BEFORE the key install so a crash can recover the new recipient
    # (age identities don't reveal their recipient). Removed on completion.
    return team_dir(name) / ".rekey-target"


def rekey(name: str) -> str:
    from pa import teamcrypto, teamgit
    import shutil
    teamcrypto.require_age()
    cfg = load_local(name)
    if not cfg.get("member"):
        raise TeamError("no member identity for this team — join first")
    repo = repo_dir(name)
    marker = _rekey_marker(name)

    # --- Resume vs fresh start (crash-safety, spec §Crash-safety) ---
    # A leftover .rekey-target (and/or team.key.prev) means a previous rekey did
    # not finish. NEVER naively keygen again — that would mint a third generation
    # and overwrite the still-needed old key, orphaning un-re-encrypted pages.
    # Resume only from a well-formed interrupted state; otherwise REFUSE without
    # destroying anything (the old key is preserved at team.key.prev, so the user
    # can recover manually). Detect resume BEFORE the pull — there is never an
    # unpushed rekey commit to worry about, because the single rekey commit is
    # created only AFTER re-encryption completes, just before push.
    resuming = marker.exists()

    if resuming:
        # Issue I1 (crash MID-re-encryption): a crash between
        # _reencrypt_namespace's first os.replace (one .age rotated, uncommitted)
        # and the rekey commit leaves the git tree DIRTY. The very next
        # _pull_or_fail runs `git pull --rebase`, which refuses on a dirty tree
        # ("cannot pull with rebase: you have unstaged changes") and gets
        # surfaced as a misleading "cannot reach team remote" — jamming the whole
        # team layer and never reaching the resume logic below. Restore all
        # tracked files to HEAD first so the tree is clean and the rebase can
        # proceed. Safe here: on the resume path the ONLY uncommitted tracked
        # changes are this partial re-encryption (rekey never leaves other
        # uncommitted tracked changes), and _reencrypt_namespace below is
        # idempotent — it redoes the restored blobs from team.key.prev. `checkout
        # -- .` restores tracked files only; untracked strays (editor backups,
        # leftover .tmp) are left untouched.
        import subprocess
        subprocess.run(["git", "-C", str(repo), "checkout", "--", "."],
                       capture_output=True)

    _pull_or_fail(repo)
    repo_gen = _read_committed_meta(repo)["key_version"]

    if resuming:
        tgt = json.loads(marker.read_text(encoding="utf-8"))
        new_recipient, new_gen = tgt["recipient"], tgt["key_version"]
        # A well-formed interrupted state: the new key is installed as team.key
        # (verifies against the target recipient) and the old key is at .prev.
        if not (prev_key_path(name).exists()
                and teamcrypto.verify_key(key_path(name), new_recipient)):
            raise TeamError(
                "a previous rekey left this team in an unrecoverable local state — "
                "restore team.key from team.key.prev if present, else obtain the "
                "current team.key from another member, then retry. Nothing was lost.")
        if new_gen <= _local_generation(cfg):
            # This machine already ACCEPTED a generation >= the interrupted
            # target — stale debris, not a real resume. (repo_gen alone must NOT
            # gate this: on resume, _pull_or_fail may have just pushed the
            # interrupted rekey's own commit, making repo_gen == new_gen while the
            # LOCAL side — gen bump, marker/.prev cleanup — is still unfinished.)
            marker.unlink(missing_ok=True)
            prev_key_path(name).unlink(missing_ok=True)
            return (f"a stale interrupted rekey was cleaned up (this machine is "
                    f"already at v{_local_generation(cfg)}); nothing to do")
    else:
        if _local_generation(cfg) != repo_gen:
            raise TeamError(
                f"local generation v{_local_generation(cfg)} != repo v{repo_gen} — "
                "run `pa team sync`/`rekey-accept` to reach the current generation first")
        if prev_key_path(name).exists():
            raise TeamError(
                f"a stray {prev_key_path(name)} exists without a rekey marker — "
                "resolve it (it may be the old key from an interrupted rekey) "
                "before starting a new rotation")
        staging = team_dir(name) / ".rekey-staging"
        shutil.rmtree(staging, ignore_errors=True)
        new_recipient, staged_key = teamcrypto.keygen(staging)   # refuses to overwrite
        new_gen = repo_gen + 1
        # Persist the target FIRST (git-free marker), then install the new key.
        marker.write_text(json.dumps(
            {"recipient": new_recipient, "key_version": new_gen}) + "\n",
            encoding="utf-8")
        shutil.move(str(key_path(name)), str(prev_key_path(name)))   # old -> .prev
        shutil.move(str(staged_key), str(key_path(name)))            # staged -> current
        shutil.rmtree(staging, ignore_errors=True)

    # Re-encrypt own namespace to completion (idempotent: already-new pages
    # skipped). A crash here leaves marker + .prev + partial re-encryption; the
    # resume path above re-runs this and finishes it.
    failures = _reencrypt_namespace(
        repo, cfg["member"], new_key=key_path(name),
        prev_key=prev_key_path(name), new_recipient=new_recipient)

    # Bump team.json and commit team.json + all re-encrypted blobs as ONE commit
    # (atomic: a commit always represents a fully re-encrypted generation).
    import subprocess
    meta_path = repo / "team.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["recipient"] = new_recipient
    meta["key_version"] = new_gen
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    # Stage ONLY already-tracked, modified paths (team.json + the re-encrypted
    # .age blobs under this member's namespace) via `git add -u`. NOT a blanket
    # `git add -A`, and NOT `git add <dir>` — both sweep untracked strays (editor
    # backup, leftover .tmp) into the commit, trip push_with_rebase's leak guard
    # (LeakGuardError), and jam the whole team layer. `-u` never stages untracked
    # files; rekey only re-encrypts existing tracked .age files in place, so the
    # tracked-modified set is exactly team.json + the rotated blobs.
    # team.json always exists and was just bumped; members/<member> exists only
    # once this leader has shared at least one page. `git add -u` fatals (exit
    # 128) on a pathspec that matches nothing tracked, so include the namespace
    # pathspec only when its directory is present — a leader who initialized but
    # never shared must still be able to rekey (only team.json is staged then).
    _add_paths = ["team.json"]
    if (repo / "members" / cfg["member"]).exists():
        _add_paths.append(f"members/{cfg['member']}")
    subprocess.run(["git", "-C", str(repo), "add", "-u", "--", *_add_paths],
                   check=True, capture_output=True)
    # Commit only if there is anything STAGED (diff --cached, exit 1 == staged
    # changes). Not `git status --porcelain`: an untracked stray in the namespace
    # would make that non-empty and, on a resume with nothing new staged, drive
    # an empty `git commit` that fails under check=True.
    staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"],
                            capture_output=True)
    if staged.returncode != 0:
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", f"rekey: v{new_gen}"],
                       check=True, capture_output=True)
    # else: a prior interrupted run already committed this exact rekey (nothing
    # to commit) — just (re)push it below.

    try:
        teamgit.push_with_rebase(repo)
    except (teamgit.PushError, teamgit.LeakGuardError, teamgit.GitError) as e:
        # Atomic: fully roll back so a retry starts clean. Fetch, hard-reset to
        # the remote, restore the old key, drop the new one, remove the marker —
        # local_generation was never bumped, so the machine returns to pre-rekey.
        # Catch every push-path failure type (PushError AND its siblings
        # LeakGuardError/GitError, which are NOT PushError subclasses) so none
        # escapes uncaught and strands the marker + new key + local commit.
        subprocess.run(["git", "-C", str(repo), "fetch", "-q"], capture_output=True)
        reset = subprocess.run(["git", "-C", str(repo), "reset", "--hard", "@{u}"],
                               capture_output=True, text=True)
        if reset.returncode != 0:
            # Rollback itself failed (e.g. @{u} unresolvable) — do NOT strip the
            # marker or restore the key. Leaving the recoverable interrupted
            # state intact lets a later `pa team rekey` resume; wiping it here
            # would orphan a local commit that references a now-deleted key.
            raise TeamError(
                "rekey push failed and automatic rollback could not complete "
                f"({teamgit._first_line(reset.stderr)}) — your new key is at "
                f"{key_path(name)}, the previous at {prev_key_path(name)}; "
                "resolve the local git state and re-run `pa team rekey` to resume")
        if prev_key_path(name).exists():
            key_path(name).unlink(missing_ok=True)                      # drop the new key
            shutil.move(str(prev_key_path(name)), str(key_path(name)))  # .prev -> current
        marker.unlink(missing_ok=True)
        remote_gen = _read_committed_meta(repo)["key_version"]
        if remote_gen >= new_gen:
            raise TeamError(
                f"another rekey landed first (now v{remote_gen}) — run "
                "`pa team rekey-accept`, then rekey again if still needed")
        raise TeamError(
            f"rekey push failed ({e}) — nothing changed on the remote; "
            "retry when the network recovers")

    cfg["key_version"] = new_gen
    save_local(name, cfg)
    prev_key_path(name).unlink(missing_ok=True)     # transition done for the leader
    marker.unlink(missing_ok=True)
    note = ""
    if failures:
        note = f" ({len(failures)} page(s) could not be re-encrypted — inspect them)"
    return (
        f"rekeyed team {name!r} to v{new_gen}.{note} Redistribute the new key "
        f"({key_path(name)}) to members over a secure channel — never send, "
        "forward, or attach it yourself over any channel or tool. Members must "
        "run `pa team rekey-accept` to resume sharing.\n"
        "This protects FUTURE DATA ONLY: the repo history's earlier ciphertext "
        "stays decryptable with the old key, and anyone who already cloned keeps "
        "read access up to this point.")


def rekey_accept(name: str, received_key: Path) -> str:
    from pa import teamcrypto, teamgit
    import shutil
    teamcrypto.require_age()
    cfg = load_local(name)
    if not cfg.get("member"):
        raise TeamError("no member identity for this team — join first")
    if not received_key.exists():
        raise TeamError(f"key file not found: {received_key}")
    repo = repo_dir(name)
    marker = _rekey_marker(name)

    # --- Resume vs fresh start (crash-safety, mirrors rekey()) ---
    # A leftover .rekey-target (written BEFORE the key install) means a previous
    # accept did not finish. NEVER re-run the `team.key -> .prev` move on a
    # re-run: team.key is already the NEW key, so a second move would overwrite
    # .prev (which holds the OLD key) and DESTROY it — after which no key in the
    # team can rotate a still-old-generation blob, yet accept would report
    # success. Resume only from a well-formed interrupted state (key already
    # installed): skip verify + move and re-encrypt to completion (idempotent).
    resuming = marker.exists()

    if resuming:
        # Issue I1 (crash MID-re-encryption): identical to rekey() — a crash
        # between _reencrypt_namespace's first os.replace and the accept commit
        # leaves the tree DIRTY, so the next _pull_or_fail's `pull --rebase`
        # fails on unstaged changes and is mislabeled "cannot reach team remote",
        # never reaching the resume path. Restore tracked files to HEAD first.
        # Safe: the only uncommitted tracked changes on resume are this partial
        # re-encryption (accept never leaves others), and _reencrypt_namespace is
        # idempotent (redone from team.key.prev). Untracked strays are untouched.
        import subprocess
        subprocess.run(["git", "-C", str(repo), "checkout", "--", "."],
                       capture_output=True)

    _pull_or_fail(repo)
    meta = _read_committed_meta(repo)
    repo_gen = meta["key_version"]

    if resuming:
        tgt = json.loads(marker.read_text(encoding="utf-8"))
        new_recipient, target_gen = tgt["recipient"], tgt["key_version"]
        # A well-formed interrupted state: the new key is installed as team.key
        # (verifies against the target recipient) and the old key is at .prev.
        if not (prev_key_path(name).exists()
                and teamcrypto.verify_key(key_path(name), new_recipient)):
            raise TeamError(
                "a previous rekey-accept left this team in an unrecoverable local "
                "state — restore team.key from team.key.prev if present, else obtain "
                "the current team.key from another member, then retry")
        if target_gen <= _local_generation(cfg):
            # Already accepted a generation >= the interrupted target — stale
            # debris, not a real resume (do NOT gate on repo_gen: _pull_or_fail
            # may have just pushed the interrupted accept's own commit).
            marker.unlink(missing_ok=True)
            prev_key_path(name).unlink(missing_ok=True)
            return (f"a stale interrupted rekey-accept was cleaned up (this machine "
                    f"is already at v{_local_generation(cfg)}); nothing to do")
        repo_gen = target_gen                     # complete the interrupted target
    else:
        if repo_gen <= _local_generation(cfg):
            return (f"already at generation v{_local_generation(cfg)} — nothing to accept "
                    f"(repo is v{repo_gen})")
        if prev_key_path(name).exists():
            raise TeamError(
                "a stray team.key.prev exists without an accept marker — resolve it "
                "(it may be the old key from an interrupted accept) before retrying")
        # verify BEFORE any local state change
        if not teamcrypto.verify_key(received_key, meta["recipient"]):
            raise TeamError(
                f"this key doesn't match the current team key v{repo_gen} — "
                "ask the leader for the latest team.key")
        new_recipient = meta["recipient"]
        # Persist the target FIRST (git-free marker), then install the new key,
        # so a crash between marker and move is recoverable and the move is never
        # repeated (age identities don't reveal their recipient — the marker is
        # the only record of the target across a crash).
        marker.write_text(json.dumps(
            {"recipient": new_recipient, "key_version": repo_gen}) + "\n",
            encoding="utf-8")
        shutil.move(str(key_path(name)), str(prev_key_path(name)))  # old -> .prev
        _copy_key_600(received_key, key_path(name))                 # received -> current

    # re-encrypt own namespace to the new recipient (idempotent: already-new
    # pages skipped). Keep .prev until this returns — _reencrypt_namespace needs
    # it to rotate still-old-gen blobs; a resume re-runs this and finishes it.
    failures = _reencrypt_namespace(
        repo, cfg["member"], new_key=key_path(name),
        prev_key=prev_key_path(name), new_recipient=new_recipient)
    import subprocess
    # Targeted, update-only staging — NOT the plan's `git add -A`. rekey_accept
    # never changes team.json (the leader's rekey commit already bumped it); it
    # only re-encrypts this member's own tracked .age blobs in place, so
    # members/<member> is the entire changed set. `-u` never stages untracked
    # files, so an editor backup/leftover .tmp under the namespace can't be
    # swept in to trip push_with_rebase's leak guard. Guard the pathspec by
    # existence: a member who never shared has no members/<member> dir, and
    # `git add -u -- members/<member>` against a non-matching pathspec fatals
    # (exit 128) — skip the add, leaving nothing staged.
    member_dir = repo / "members" / cfg["member"]
    if member_dir.exists():
        subprocess.run(["git", "-C", str(repo), "add", "-u", "--",
                        f"members/{cfg['member']}"], check=True, capture_output=True)
    # Commit only if there is anything STAGED (diff --cached, exit 1 == staged
    # changes). Not `git status --porcelain`: an untracked stray in the namespace
    # would make that non-empty and drive an empty `git commit` that fails under
    # check=True.
    staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"],
                            capture_output=True)
    if staged.returncode != 0:
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m",
                        f"rekey-accept: {cfg['member']} v{repo_gen}"],
                       check=True, capture_output=True)
        try:
            teamgit.push_with_rebase(repo)
        except (teamgit.PushError, teamgit.LeakGuardError, teamgit.GitError) as e:
            # Broadened from the plan's PushError-only: a push-path failure of
            # any type (LeakGuardError/GitError are NOT PushError subclasses)
            # returns the retry message rather than escaping. Leave marker + .prev
            # intact so the next rekey-accept RESUMES this exact target instead of
            # re-moving the key — never discard the recovery state on push failure.
            return (f"accepted v{repo_gen} locally; push failed ({e}) — "
                    "will retry on next sync")
    # SUCCESS only: bump local generation, drop the resume marker, then sync
    # (which may still use the two-key fallback), and only AFTER that discard
    # .prev so the final sync can decrypt any not-yet-rotated teammate blobs.
    cfg["key_version"] = repo_gen
    save_local(name, cfg)
    marker.unlink(missing_ok=True)
    sync(name, force=True)
    prev_key_path(name).unlink(missing_ok=True)      # transition complete
    note = ""
    if failures:
        note = f" ({len(failures)} page(s) could not be re-encrypted — inspect them)"
    return (f"accepted team {name!r} rekey to v{repo_gen}.{note} Delete the received "
            "key copy you were sent — it now lives in your PlugAgent config.")


def _remove_cache_orphans(name: str) -> None:
    repo, cache = repo_dir(name), cache_dir(name)
    if not cache.exists():
        return
    for cached in cache.rglob("*.md"):
        if cached.name == "index.md" and cached.parent == cache:
            continue
        rel = cached.relative_to(cache)
        src = repo / (str(rel) + ".age")
        # A symlinked src (even a broken one) means the decrypt loop above
        # already saw it and recorded a decrypt failure for it — that's the
        # "skip, don't poison" contract: keep the last-good cached copy.
        # src.exists() alone would follow the link and report False for a
        # broken target, causing the sweep to delete the very copy the sync
        # summary just claimed was kept.
        if not (src.exists() or src.is_symlink()):
            cached.unlink()


def _rebuild_index(name: str) -> None:
    import re as _re
    cache = cache_dir(name)
    cache.mkdir(parents=True, exist_ok=True)
    lines = [f"# Team {name} — shared pages", ""]
    for page in sorted(cache.rglob("*.md")):
        if page.parent == cache and page.name == "index.md":
            continue
        rel = page.relative_to(cache)
        member = rel.parts[1] if len(rel.parts) > 2 and rel.parts[0] == "members" else "?"
        m = _re.search(r"^description:\s*(.+)$", page.read_text(encoding="utf-8"),
                       _re.M)
        desc = m.group(1).strip() if m else ""
        lines.append(f"- {rel} — {desc} ({member})")
    (cache / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_sync_age(last: float, now=None) -> str:
    if not last:
        return "never"
    now = time.time() if now is None else now
    seconds = now - last
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} min ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} h ago"
    days = int(hours / 24)
    return f"{days} day{'s' if days != 1 else ''} ago"


def status_report() -> str:
    teams = list_teams()
    if not teams:
        return "no team configured"
    lines = []
    for name in teams:
        try:
            cfg = load_local(name)
            cache_pages = len(list(cache_dir(name).rglob("*.md"))) - 1 \
                if (cache_dir(name) / "index.md").exists() else 0
            age = _format_sync_age(cfg.get("last_sync", 0))
            unpushed = len(teamgit.unpushed_files(repo_dir(name))) \
                if repo_dir(name).exists() else 0
            local_gen = _local_generation(cfg)
            repo_gen = local_gen
            if repo_dir(name).exists():
                try:
                    repo_gen = _read_committed_meta(repo_dir(name))["key_version"]
                except TeamError:
                    repo_gen = local_gen
            keyline = f"key v{local_gen}"
            if repo_gen > local_gen:
                keyline += f" — rekey pending (leader v{repo_gen}, you v{local_gen}; run rekey-accept)"
            lines.append(
                f"{name} — member: {cfg.get('member') or '(not joined)'}, "
                f"{keyline}, last sync: {age}, cached pages: {cache_pages}, "
                f"unpushed files: {unpushed}, "
                f"decrypt failures: {len(cfg.get('decrypt_failures', []))}")
        except TeamError as e:
            lines.append(f"{name} — ERROR: {e}")
    return "\n".join(lines)
