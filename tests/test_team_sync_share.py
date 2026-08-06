import subprocess

import pytest

from pa import config, distill, team
from tests.team_helpers import fake_crypto, make_remote


@pytest.fixture()
def joined(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    team.init_team("alpha", str(remote), "alice")
    return tmp_path, remote


def put_page(relpath, description, body):
    distill.wiki_put(relpath, f"---\ndescription: {description}\n---\n\n{body}\n")


def test_share_encrypts_and_pushes(joined):
    tmp_path, remote = joined
    put_page("concepts/auth.md", "JWT decision", "we chose JWT")
    msg = team.share("alpha", "concepts/auth.md")
    assert "shared" in msg
    local_blob = (team.repo_dir("alpha") / "members/alice/wiki/concepts/auth.md.age").read_bytes()
    assert local_blob.startswith(b"FAKEAGE:")   # went through the crypto boundary
    assert team.load_local("alpha")["last_synced_commit"] is not None  # set by the trailing sync
    # and the trailing sync decrypted our own page into the cache
    assert (team.cache_dir("alpha") / "members/alice/wiki/concepts/auth.md").exists()


def test_share_rejects_outside_wiki(joined):
    with pytest.raises(team.TeamError, match="wiki"):
        team.share("alpha", "../raw/sessions/x.md")


def test_share_rejects_missing_page(joined):
    with pytest.raises(team.TeamError, match="no such wiki page"):
        team.share("alpha", "concepts/nope.md")


def test_share_without_member_identity_refuses(joined):
    cfg = team.load_local("alpha"); cfg["member"] = None; team.save_local("alpha", cfg)
    put_page("concepts/a.md", "d", "b")
    with pytest.raises(team.TeamError, match="join"):
        team.share("alpha", "concepts/a.md")


def test_sync_decrypts_to_cache_and_builds_index(joined, tmp_path):
    _tmp, remote = joined
    put_page("concepts/auth.md", "JWT decision", "we chose JWT")
    team.share("alpha", "concepts/auth.md")
    # simulate teammate bob pushing a page from another clone
    bob = tmp_path / "bobclone"
    subprocess.run(["git", "clone", "-q", str(remote), str(bob)], check=True)
    for k, v in (("user.email", "b@b"), ("user.name", "b")):
        subprocess.run(["git", "-C", str(bob), "config", k, v], check=True)
    page = bob / "members/bob/wiki/notes/tips.md.age"
    page.parent.mkdir(parents=True)
    page.write_bytes(b"FAKEAGE:v1:---\ndescription: Bob tips\n---\n\nbe kind\n")
    subprocess.run(["git", "-C", str(bob), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(bob), "commit", "-q", "-m", "share"], check=True)
    subprocess.run(["git", "-C", str(bob), "push", "-q"], check=True)

    team.sync("alpha", force=True)
    cached = team.cache_dir("alpha") / "members/bob/wiki/notes/tips.md"
    assert cached.exists() and "be kind" in cached.read_text()
    index = (team.cache_dir("alpha") / "index.md").read_text()
    assert "members/bob/wiki/notes/tips.md — Bob tips (bob)" in index
    assert "members/alice/wiki/concepts/auth.md — JWT decision (alice)" in index


def test_sync_ttl_skips_and_force_overrides(joined):
    team.sync("alpha", force=True)
    assert "skipped" in team.sync("alpha")          # within TTL
    assert "skipped" not in team.sync("alpha", force=True)


def test_sync_skips_undecryptable_file_without_poisoning(joined, tmp_path):
    _tmp, remote = joined
    bad = tmp_path / "badclone"
    subprocess.run(["git", "clone", "-q", str(remote), str(bad)], check=True)
    for k, v in (("user.email", "b@b"), ("user.name", "b")):
        subprocess.run(["git", "-C", str(bad), "config", k, v], check=True)
    f = bad / "members/mallory/wiki/x.md.age"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"NOT-A-VALID-BLOB")
    subprocess.run(["git", "-C", str(bad), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(bad), "commit", "-q", "-m", "bad"], check=True)
    subprocess.run(["git", "-C", str(bad), "push", "-q"], check=True)
    put_page("concepts/ok.md", "fine", "good body")
    team.share("alpha", "concepts/ok.md")
    out = team.sync("alpha", force=True)
    assert "1 file(s) failed to decrypt" in out
    assert (team.cache_dir("alpha") / "members/alice/wiki/concepts/ok.md").exists()
    assert team.load_local("alpha")["decrypt_failures"] == ["members/mallory/wiki/x.md.age"]


def test_sync_removes_cache_for_deleted_pages(joined):
    put_page("concepts/temp.md", "temp", "x")
    team.share("alpha", "concepts/temp.md")
    team.sync("alpha", force=True)
    repo = team.repo_dir("alpha")
    subprocess.run(["git", "-C", str(repo), "rm", "-q",
                    "members/alice/wiki/concepts/temp.md.age"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "rm"], check=True)
    from pa import teamgit
    teamgit.push_with_rebase(repo)
    team.sync("alpha", force=True)
    assert not (team.cache_dir("alpha") / "members/alice/wiki/concepts/temp.md").exists()


# --- carry-forwards ---------------------------------------------------------


def test_sync_skips_symlinked_age_file_without_following_it(joined, tmp_path):
    # T2 carry-forward: a teammate's repo should never contain a symlinked
    # .age file — decrypting through one could read/leak anything the link
    # target points at on this machine. sync() must skip it (counted with
    # decrypt failures, not silently ignored) and never follow it.
    _tmp, remote = joined
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("not part of any vault")
    evil = tmp_path / "evilclone"
    subprocess.run(["git", "clone", "-q", str(remote), str(evil)], check=True)
    for k, v in (("user.email", "e@e"), ("user.name", "e")):
        subprocess.run(["git", "-C", str(evil), "config", k, v], check=True)
    link_path = evil / "members/mallory/wiki/link.md.age"
    link_path.parent.mkdir(parents=True)
    link_path.symlink_to(outside)
    subprocess.run(["git", "-C", str(evil), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(evil), "commit", "-q", "-m", "evil symlink"], check=True)
    subprocess.run(["git", "-C", str(evil), "push", "-q"], check=True)

    out = team.sync("alpha", force=True)
    assert "1 file(s) failed to decrypt" in out
    assert team.load_local("alpha")["decrypt_failures"] == ["members/mallory/wiki/link.md.age"]
    cached = team.cache_dir("alpha") / "members/mallory/wiki/link.md"
    assert not cached.exists()
    assert not cached.is_symlink()


def test_sync_handles_D_status_deletion_without_relying_on_orphan_sweep(joined, monkeypatch):
    # changed_age_files() carry-forward: a deleted .age file comes through
    # the diff as a plain "D" status entry. The sync loop must handle "D"
    # entries directly (delete the stale cache copy) rather than relying
    # solely on the orphan sweep backstop — disable the sweep here to prove
    # the explicit D-status branch does the removal on its own. (An
    # .age-to-.age rename does *not* emit a "D" — teamgit only reports the
    # vacated side as "D" when the new name stops being a .age path, or for
    # an ordinary delete like this one — so that case stays covered by the
    # orphan sweep alone, per the plan.)
    from pa import teamgit
    put_page("concepts/temp2.md", "temp2", "x")
    team.share("alpha", "concepts/temp2.md")
    repo = team.repo_dir("alpha")
    subprocess.run(["git", "-C", str(repo), "rm", "-q",
                    "members/alice/wiki/concepts/temp2.md.age"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "rm"], check=True)
    teamgit.push_with_rebase(repo)

    monkeypatch.setattr(team, "_remove_cache_orphans", lambda name, manifests: None)
    team.sync("alpha", force=True)
    assert not (team.cache_dir("alpha") / "members/alice/wiki/concepts/temp2.md").exists()


# --- fix-first review round (absolute-path share, symlink-safe orphan sweep) -


def test_share_with_absolute_relpath_stays_inside_repo(joined):
    # Important #1: pathlib's "/" operator drops the left operand whenever
    # the right one is absolute, so an absolute-but-in-wiki relpath used to
    # sail through `wiki / relpath` and `repo / ... / (relpath + ".age")`
    # alike, ending up writing the encrypted blob as a sibling of the
    # original page INSIDE the vault wiki instead of into the repo.
    tmp_path, remote = joined
    put_page("concepts/auth.md", "JWT decision", "we chose JWT")
    vault = config.vault()
    abs_relpath = str((vault / "wiki" / "concepts" / "auth.md").resolve())
    msg = team.share("alpha", abs_relpath)
    assert "shared" in msg
    assert (team.repo_dir("alpha") / "members/alice/wiki/concepts/auth.md.age").exists()
    assert not any(vault.rglob("*.age"))


def test_orphan_sweep_preserves_cache_on_broken_symlink_replacement(joined, tmp_path):
    # Important #2: the orphan sweep used to compare cache entries against
    # `src.exists()`, which follows symlinks — so once a teammate's .age
    # blob degenerated into a broken symlink, the sweep saw "doesn't exist"
    # and deleted the last-good cached plaintext out from under a sync
    # summary that had just claimed it was kept.
    _tmp, remote = joined
    put_page("concepts/valid.md", "valid", "good content")
    team.share("alpha", "concepts/valid.md")

    evil = tmp_path / "evilclone2"
    subprocess.run(["git", "clone", "-q", str(remote), str(evil)], check=True)
    for k, v in (("user.email", "e@e"), ("user.name", "e")):
        subprocess.run(["git", "-C", str(evil), "config", k, v], check=True)
    target = evil / "members/alice/wiki/concepts/valid.md.age"
    target.unlink()
    target.symlink_to(evil / "nonexistent-target")
    subprocess.run(["git", "-C", str(evil), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(evil), "commit", "-q", "-m", "swap for broken symlink"],
                   check=True)
    subprocess.run(["git", "-C", str(evil), "push", "-q"], check=True)

    out = team.sync("alpha", force=True)
    assert "1 file(s) failed to decrypt" in out
    assert team.load_local("alpha")["decrypt_failures"] == ["members/alice/wiki/concepts/valid.md.age"]
    cached = team.cache_dir("alpha") / "members/alice/wiki/concepts/valid.md"
    assert cached.exists()
    assert "good content" in cached.read_text()


def test_leader_can_share_immediately_after_init(tmp_path, monkeypatch):
    # Regression (Phase 2 merge-blocker): the leader who runs `pa team init
    # ... --as <member>` claims a namespace in ONE step and is share-ready —
    # no broken self-join needed. This exercises the real flow with ZERO
    # direct cfg["member"] assignment.
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    team.init_team("alpha", str(remote), "lead")
    put_page("concepts/x.md", "leader page", "leader body")
    msg = team.share("alpha", "concepts/x.md")
    assert "shared" in msg and "join first" not in msg
    # the encrypted blob landed in the repo under the leader's namespace ...
    assert (team.repo_dir("alpha") / "members/lead/wiki/concepts/x.md.age").exists()
    # ... and the trailing sync decrypted it back into the leader's cache
    assert (team.cache_dir("alpha") / "members/lead/wiki/concepts/x.md").exists()
