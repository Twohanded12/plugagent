import subprocess
from pathlib import Path

import pytest

from pa import config, team, teamcrypto
from tests.team_helpers import fake_crypto, make_remote


@pytest.fixture()
def joined(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    team.init_team("alpha", str(remote), "lead")
    return tmp_path, remote


def _teammate_push(remote, member, rel, recipient, data):
    """Simulate another clone pushing a page sealed with `recipient`."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    subprocess.run(["git", "clone", "-q", str(remote), str(d)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    p = d / "members" / member / "wiki" / (rel + ".age")
    p.parent.mkdir(parents=True)
    p.write_bytes(teamcrypto.encrypt(recipient, data))
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "x"], check=True)
    subprocess.run(["git", "-C", str(d), "push", "-q"], check=True)


def test_sync_fallback_reads_prev_generation(joined):
    _tmp, remote = joined
    # a v1 page exists; locally we hold a v2 team.key + a v1 .prev
    _teammate_push(remote, "bob", "old.md", "age1fake-v1", b"OLDBODY")
    # install a v2 key as current, keep v1 as .prev
    import shutil
    shutil.move(str(team.key_path("alpha")), str(team.prev_key_path("alpha")))  # v1 -> .prev
    v2_recipient, v2_key = teamcrypto.keygen(team.team_dir("alpha") / "stage")
    shutil.move(str(v2_key), str(team.key_path("alpha")))                       # v2 -> current
    team.sync("alpha", force=True)
    cached = team.cache_dir("alpha") / "members/bob/wiki/old.md"
    assert cached.read_text() == "OLDBODY"     # read via .prev fallback


def test_sync_reports_rekey_detected(joined):
    _tmp, remote = joined
    # bump the repo generation behind our back (simulate a leader on another machine)
    repo = team.repo_dir("alpha")
    meta = team._read_committed_meta(repo)
    import json, subprocess as sp
    (repo / "team.json").write_text(json.dumps(
        {"name": "alpha", "recipient": "age1fake-v2", "key_version": 2,
         "schema_version": 1}, indent=2) + "\n")
    sp.run(["git", "-C", str(repo), "commit", "-aqm", "rekey: v2"], check=True)
    from pa import teamgit
    teamgit.push_with_rebase(repo)
    # our local generation is still 1
    out = team.sync("alpha", force=True)
    assert "rekeyed to v2" in out and "rekey-accept" in out


def test_sync_on_dirty_tree_reports_local_cause_not_network(joined):
    # Mirrors d6e43b5's fix for _pull_or_fail, but for sync()'s own inline
    # push_with_rebase + `git pull --rebase` block, which does NOT route
    # through _pull_or_fail. A dirty working tree fails `git pull --rebase`
    # LOCALLY regardless of network state — sync() must not mislabel that as
    # "sync failed (network?)". sync() fails soft (returns a string), so it
    # must still return here rather than raising.
    _tmp, _remote = joined
    repo = team.repo_dir("alpha")
    # Modify a tracked file without committing, so `git status --porcelain`
    # is non-empty: push_with_rebase has nothing new to push (no-op success),
    # but the subsequent `git pull --rebase` refuses on the dirty tree.
    meta_path = repo / "team.json"
    meta_path.write_text(meta_path.read_text() + "// junk\n")
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                           capture_output=True, text=True)
    assert dirty.stdout.strip()               # precondition: tree IS dirty

    out = team.sync("alpha", force=True)       # must return, not raise
    assert "uncommitted changes" in out
    assert "checkout -- ." in out
    assert "network" not in out


def test_sync_on_schema_bumped_repo_fails_before_touching_cache(joined):
    _tmp, remote = joined
    repo = team.repo_dir("alpha")
    import json, subprocess as sp
    (repo / "team.json").write_text(json.dumps(
        {"name": "alpha", "recipient": "age1fake-v1", "schema_version": 99}, indent=2) + "\n")
    sp.run(["git", "-C", str(repo), "commit", "-aqm", "bump schema"], check=True)
    from pa import teamgit; teamgit.push_with_rebase(repo)
    before = team.load_local("alpha").get("last_synced_commit")
    with pytest.raises(team.TeamError, match="schema_version"):
        team.sync("alpha", force=True)
    # cursor did NOT advance — the sync failed fast, not half-applied
    assert team.load_local("alpha").get("last_synced_commit") == before
