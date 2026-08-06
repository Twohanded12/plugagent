import shutil
import subprocess
from pathlib import Path

import pytest

from pa import config, team, teamcrypto
from tests.team_helpers import fake_crypto, make_remote


@pytest.fixture()
def two_homes(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    # leader home
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "lead-home"))
    config.set_value("vault", str(tmp_path / "lead-vault"))
    team.init_team("alpha", str(remote), "lead")
    leader_key_v1 = tmp_path / "k1"; shutil.copy(team.key_path("alpha"), leader_key_v1)
    return tmp_path, remote, leader_key_v1


def _put_page(rel, desc, body):
    from pa import distill
    distill.wiki_put(rel, f"---\ndescription: {desc}\n---\n\n{body}\n")


def _join_as(tmp_path, monkeypatch, remote, key, member, tag):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / f"{tag}-home"))
    config.set_value("vault", str(tmp_path / f"{tag}-vault"))
    team.join_team(str(remote), key, member)


def test_accept_verifies_installs_reencrypts_and_bumps(two_homes, tmp_path, monkeypatch):
    _tmp, remote, key_v1 = two_homes
    # member bob joins at v1, shares a page
    _join_as(tmp_path, monkeypatch, remote, key_v1, "bob", "bob")
    _put_page("notes/n.md", "N", "BOB-BODY")
    team.share("alpha", "notes/n.md")
    # leader rekeys to v2 (switch back to leader home)
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "lead-home"))
    config.set_value("vault", str(tmp_path / "lead-vault"))
    team.rekey("alpha")
    new_key = tmp_path / "k2"; shutil.copy(team.key_path("alpha"), new_key)
    # bob accepts
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "bob-home"))
    config.set_value("vault", str(tmp_path / "bob-vault"))
    msg = team.rekey_accept("alpha", new_key)
    assert "v2" in msg
    assert team._local_generation(team.load_local("alpha")) == 2
    assert not team.prev_key_path("alpha").exists()          # discarded after accept
    # bob's own page is now v2 — decrypted content is the full markdown page
    blob = (team.repo_dir("alpha") / "members/bob/wiki/notes/n.md.age").read_bytes()
    assert teamcrypto.decrypt(team.key_path("alpha"), blob).endswith(b"BOB-BODY\n")


def test_accept_refuses_wrong_key(two_homes, tmp_path, monkeypatch):
    _tmp, remote, key_v1 = two_homes
    _join_as(tmp_path, monkeypatch, remote, key_v1, "bob", "bob")
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "lead-home"))
    config.set_value("vault", str(tmp_path / "lead-vault"))
    team.rekey("alpha")
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "bob-home"))
    config.set_value("vault", str(tmp_path / "bob-vault"))
    wrong = tmp_path / "wrong"; wrong.write_text("FAKEKEY-v9")
    with pytest.raises(team.TeamError, match="match|current team key"):
        team.rekey_accept("alpha", wrong)
    # no local change: still v1, no .prev
    assert team._local_generation(team.load_local("alpha")) == 1
    assert not team.prev_key_path("alpha").exists()


def test_share_blocked_until_accept_then_works(two_homes, tmp_path, monkeypatch):
    _tmp, remote, key_v1 = two_homes
    _join_as(tmp_path, monkeypatch, remote, key_v1, "bob", "bob")
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "lead-home"))
    config.set_value("vault", str(tmp_path / "lead-vault"))
    team.rekey("alpha")
    new_key = tmp_path / "k2"; shutil.copy(team.key_path("alpha"), new_key)
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "bob-home"))
    config.set_value("vault", str(tmp_path / "bob-vault"))
    _put_page("notes/m.md", "M", "X")
    with pytest.raises(team.TeamError, match="rekeyed"):
        team.share("alpha", "notes/m.md")
    team.rekey_accept("alpha", new_key)
    assert "shared" in team.share("alpha", "notes/m.md")


def test_accept_resumes_after_interruption_without_destroying_prev(
        two_homes, tmp_path, monkeypatch):
    # Crash the accept AFTER re-encryption + commit but during the push, then
    # re-run and confirm it RESUMES (no second `team.key -> .prev` move that
    # would overwrite/destroy the old key) and completes to v2 with the page
    # readable under the new key. Mirrors the rekey resume test.
    _tmp, remote, key_v1 = two_homes
    _join_as(tmp_path, monkeypatch, remote, key_v1, "bob", "bob")
    _put_page("notes/n.md", "N", "BOB-BODY")
    team.share("alpha", "notes/n.md")
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "lead-home"))
    config.set_value("vault", str(tmp_path / "lead-vault"))
    team.rekey("alpha")
    new_key = tmp_path / "k2"; shutil.copy(team.key_path("alpha"), new_key)
    # bob accepts, but the accept push explodes after re-encryption + commit
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "bob-home"))
    config.set_value("vault", str(tmp_path / "bob-vault"))
    import pa.teamgit as tg
    real_push = tg.push_with_rebase
    calls = {"n": 0}

    def flaky_push(repo):
        # let _pull_or_fail's push (call 1) through; blow up the accept push
        # (call 2) with a NON-caught error so it interrupts (not the caught
        # PushError/LeakGuardError/GitError retry path)
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated crash after re-encryption")
        return real_push(repo)

    monkeypatch.setattr(tg, "push_with_rebase", flaky_push)
    with pytest.raises(Exception):
        team.rekey_accept("alpha", new_key)
    # interrupted state: marker + .prev present, new key installed, old key SAFE
    assert (team.team_dir("alpha") / ".rekey-target").exists()
    assert team.prev_key_path("alpha").exists()
    assert team.prev_key_path("alpha").read_text() == "FAKEKEY-v1"   # OLD key intact
    assert team._local_generation(team.load_local("alpha")) == 1     # not yet bumped
    # Restore ONLY push (targeted setattr, NOT monkeypatch.undo which would also
    # revert the fake_crypto boundary + PLUGAGENT_HOME).
    monkeypatch.setattr(tg, "push_with_rebase", real_push)
    msg = team.rekey_accept("alpha", new_key)                        # resume
    assert "v2" in msg
    assert team._local_generation(team.load_local("alpha")) == 2
    assert not team.prev_key_path("alpha").exists()                  # discarded
    assert not (team.team_dir("alpha") / ".rekey-target").exists()   # marker gone
    blob = (team.repo_dir("alpha") / "members/bob/wiki/notes/n.md.age").read_bytes()
    assert teamcrypto.decrypt(team.key_path("alpha"), blob).endswith(b"BOB-BODY\n")


def test_accept_refuses_stray_prev_without_marker(two_homes, tmp_path, monkeypatch):
    # A team.key.prev with NO accept marker is ambiguous debris (possibly the old
    # key from an interrupted accept) — refuse rather than risk a destructive move.
    _tmp, remote, key_v1 = two_homes
    _join_as(tmp_path, monkeypatch, remote, key_v1, "bob", "bob")
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "lead-home"))
    config.set_value("vault", str(tmp_path / "lead-vault"))
    team.rekey("alpha")
    new_key = tmp_path / "k2"; shutil.copy(team.key_path("alpha"), new_key)
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "bob-home"))
    config.set_value("vault", str(tmp_path / "bob-vault"))
    team.sync("alpha", force=True)                       # repo now v2, bob still v1
    team.prev_key_path("alpha").write_text("FAKEKEY-v1")  # stray .prev, no marker
    with pytest.raises(team.TeamError, match="stray"):
        team.rekey_accept("alpha", new_key)
    assert team._local_generation(team.load_local("alpha")) == 1


def test_accept_resumes_from_dirty_tree_after_partial_reencrypt(
        two_homes, tmp_path, monkeypatch):
    # Issue I1 (accept side): a crash MID-re-encryption during rekey-accept (one
    # .age rotated in the working tree, uncommitted, BEFORE the accept commit)
    # leaves the git tree DIRTY. _pull_or_fail's `pull --rebase` then fails on the
    # dirty tree and is mislabeled "cannot reach team remote", locking the team
    # layer before the resume path runs. The fix restores the tree first; resume
    # completes to v2 with the page readable under the new key.
    import json
    _tmp, remote, key_v1 = two_homes
    _join_as(tmp_path, monkeypatch, remote, key_v1, "bob", "bob")
    _put_page("notes/n.md", "N", "BOB-BODY")
    team.share("alpha", "notes/n.md")
    # leader rekeys to v2
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "lead-home"))
    config.set_value("vault", str(tmp_path / "lead-vault"))
    team.rekey("alpha")
    new_key = tmp_path / "k2"; shutil.copy(team.key_path("alpha"), new_key)
    # switch to bob and hand-build the interrupted, DIRTY-tree partial accept
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "bob-home"))
    config.set_value("vault", str(tmp_path / "bob-vault"))
    repo = team.repo_dir("alpha")
    blob_path = repo / "members/bob/wiki/notes/n.md.age"
    marker = team._rekey_marker("alpha")
    marker.write_text(json.dumps({"recipient": "age1fake-v2", "key_version": 2}) + "\n")
    shutil.move(str(team.key_path("alpha")), str(team.prev_key_path("alpha")))  # old -> .prev
    team.key_path("alpha").write_text("FAKEKEY-v2")                             # new key installed
    v1_plain = teamcrypto.decrypt(team.prev_key_path("alpha"), blob_path.read_bytes())
    blob_path.write_bytes(teamcrypto.encrypt("age1fake-v2", v1_plain))          # rotated, uncommitted
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                           capture_output=True, text=True)
    assert dirty.stdout.strip()                      # precondition: tree IS dirty

    # --- Resume: must complete to v2, NOT raise the misleading network error ---
    msg = team.rekey_accept("alpha", new_key)
    assert "v2" in msg
    assert team._local_generation(team.load_local("alpha")) == 2
    assert not team.prev_key_path("alpha").exists()
    assert not marker.exists()
    blob = blob_path.read_bytes()
    assert teamcrypto.decrypt(team.key_path("alpha"), blob).endswith(b"BOB-BODY\n")
    end = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                         capture_output=True, text=True)
    assert not end.stdout.strip()                    # tree clean again
