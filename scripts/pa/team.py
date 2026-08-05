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
    repo = repo_dir(name)
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
    # Deliberately do NOT touch last_sync/last_synced_commit here: the rebase
    # may have pulled in teammate commits we haven't decrypted yet — advancing
    # the cursor would permanently skip them. Let sync do all cursor movement.
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
        return f"sync failed (network?): {e} — serving stale cache"
    import subprocess
    pulled = subprocess.run(["git", "-C", str(repo), "pull", "-q", "--rebase"],
                            capture_output=True, text=True)
    if pulled.returncode != 0:
        return f"sync failed (network?): {pulled.stderr.strip()} — serving stale cache"
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
        try:
            data = teamcrypto.decrypt(key_path(name), src.read_bytes())
        except teamcrypto.DecryptError:
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
    return msg


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
            lines.append(
                f"{name} — member: {cfg.get('member') or '(not joined)'}, "
                f"last sync: {age}, cached pages: {cache_pages}, "
                f"unpushed files: {unpushed}, "
                f"decrypt failures: {len(cfg.get('decrypt_failures', []))}")
        except TeamError as e:
            lines.append(f"{name} — ERROR: {e}")
    return "\n".join(lines)
