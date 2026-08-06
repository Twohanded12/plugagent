import json
import subprocess

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


def _put_page(rel, desc, body):
    from pa import distill
    distill.wiki_put(rel, f"---\ndescription: {desc}\n---\n\n{body}\n")


def test_rekey_rotates_recipient_bumps_version_and_reencrypts(joined):
    _put_page("concepts/a.md", "A", "SECRET-A")
    team.share("alpha", "concepts/a.md")                 # a page exists at v1
    msg = team.rekey("alpha")
    assert "v2" in msg and "secure channel" in msg and "future data only" in msg.lower()
    repo = team.repo_dir("alpha")
    meta = team._read_committed_meta(repo)
    assert meta["key_version"] == 2 and meta["recipient"].endswith("v2")
    assert json.loads((repo / "team.json").read_text())["schema_version"] == 1
    # leader's page re-encrypted to v2, readable with the new current key;
    # the decrypted content is the FULL markdown page (frontmatter + body)
    blob = (repo / "members/lead/wiki/concepts/a.md.age").read_bytes()
    assert teamcrypto.decrypt(team.key_path("alpha"), blob).endswith(b"SECRET-A\n")
    # local generation advanced; .prev discarded after own re-encryption
    assert team._local_generation(team.load_local("alpha")) == 2
    assert not team.prev_key_path("alpha").exists()
    assert not (team.team_dir("alpha") / ".rekey-target").exists()   # marker cleaned up


def test_rekey_refuses_when_local_behind(joined):
    tmp_path, remote = joined
    # remote jumps to v2 under us
    d = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(d)], check=True)
    for k, v in (("user.email", "o@o"), ("user.name", "o")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    (d / "team.json").write_text(json.dumps(
        {"name": "alpha", "recipient": "age1fake-v2", "key_version": 2,
         "schema_version": 1}, indent=2) + "\n")
    subprocess.run(["git", "-C", str(d), "commit", "-aqm", "rekey: v2"], check=True)
    subprocess.run(["git", "-C", str(d), "push", "-q"], check=True)
    with pytest.raises(team.TeamError, match="sync|accept|behind|rekey"):
        team.rekey("alpha")


def test_rekey_leaves_no_prev_and_repo_has_no_plaintext(joined):
    _put_page("concepts/b.md", "B", "SECRET-B")
    team.share("alpha", "concepts/b.md")
    team.rekey("alpha")
    # (fake crypto embeds plaintext; the real zero-plaintext grep is the
    # integration test's real-age variant — here we assert structure)
    assert not team.prev_key_path("alpha").exists()
    assert team.key_path("alpha").read_text().endswith("v2")


def test_rekey_ignores_stray_non_age_file_in_namespace(joined):
    # A stray non-.age file under the leader's namespace (editor backup, leftover
    # .tmp) must NOT be swept into the rekey commit — a blanket `git add -A` would
    # stage it, trip push_with_rebase's leak guard (LeakGuardError), and jam the
    # whole team layer. Targeted staging leaves it untracked and rekey completes.
    _put_page("concepts/d.md", "D", "SECRET-D")
    team.share("alpha", "concepts/d.md")
    repo = team.repo_dir("alpha")
    stray = repo / "members/lead/wiki/notes.md.bak"
    stray.write_text("scratch plaintext — must never be pushed")

    msg = team.rekey("alpha")
    assert "v2" in msg
    assert team._read_committed_meta(repo)["key_version"] == 2
    # the stray file is still there, still untracked (never committed)
    assert stray.exists()
    st = subprocess.run(["git", "-C", str(repo), "status", "--porcelain",
                         "--", "members/lead/wiki/notes.md.bak"],
                        capture_output=True, text=True)
    assert st.stdout.strip().startswith("??")


def test_rekey_resumes_after_interruption_without_data_loss(joined, monkeypatch):
    # Crash mid-re-encryption: run rekey but make the FINAL push explode after
    # re-encryption + commit, then re-run rekey and confirm it completes with the
    # leader's page readable under the new key (no orphaned/lost original).
    _put_page("concepts/c.md", "C", "SECRET-C")
    team.share("alpha", "concepts/c.md")

    import pa.teamgit as tg
    real_push = tg.push_with_rebase
    calls = {"n": 0}

    def flaky_push(repo):
        # let _pull_or_fail's push (call 1) through; blow up the rekey push (call 2)
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated crash after re-encryption")
        return real_push(repo)

    monkeypatch.setattr(tg, "push_with_rebase", flaky_push)
    with pytest.raises(Exception):
        team.rekey("alpha")
    # interrupted state: marker + .prev present, key installed, page re-encrypted
    assert (team.team_dir("alpha") / ".rekey-target").exists()
    assert team.prev_key_path("alpha").exists()
    # Restore ONLY push — NOT monkeypatch.undo(), which would also revert the
    # whole fake_crypto boundary and PLUGAGENT_HOME, making the resumed rekey run
    # against real (absent) age. Targeted restore keeps the fake crypto in place.
    monkeypatch.setattr(tg, "push_with_rebase", real_push)

    msg = team.rekey("alpha")               # resume — must NOT keygen a v3
    assert "v2" in msg
    meta = team._read_committed_meta(team.repo_dir("alpha"))
    assert meta["key_version"] == 2         # resumed to v2, not v3
    blob = (team.repo_dir("alpha") / "members/lead/wiki/concepts/c.md.age").read_bytes()
    assert teamcrypto.decrypt(team.key_path("alpha"), blob).endswith(b"SECRET-C\n")
    assert not team.prev_key_path("alpha").exists()
    assert not (team.team_dir("alpha") / ".rekey-target").exists()


def test_rekey_resumes_from_dirty_tree_after_partial_reencrypt(joined):
    # Issue I1: a crash MID-re-encryption (one .age rotated in the working tree
    # via os.replace, uncommitted, BEFORE the rekey commit) leaves the git tree
    # DIRTY. Every subsequent team command then hit _pull_or_fail's
    # `pull --rebase` on the dirty tree, which fails with "cannot pull with
    # rebase: you have unstaged changes" — surfaced as the misleading
    # "cannot reach team remote", so the resume logic was never reached. The fix
    # restores the tree to HEAD before pulling; resume then completes to v2.
    import shutil
    _put_page("concepts/e.md", "E", "SECRET-E")
    team.share("alpha", "concepts/e.md")
    repo = team.repo_dir("alpha")
    blob_path = repo / "members/lead/wiki/concepts/e.md.age"

    # --- Hand-build the exact interrupted, DIRTY-tree partial state ---
    # marker written BEFORE the key install (as rekey() does); old key -> .prev;
    # v2 key installed as current; ONE blob rotated in the working tree but NOT
    # committed (this is the uncommitted os.replace that makes the tree dirty).
    marker = team._rekey_marker("alpha")
    marker.write_text(json.dumps({"recipient": "age1fake-v2", "key_version": 2}) + "\n")
    shutil.move(str(team.key_path("alpha")), str(team.prev_key_path("alpha")))
    team.key_path("alpha").write_text("FAKEKEY-v2")
    v1_plain = teamcrypto.decrypt(team.prev_key_path("alpha"), blob_path.read_bytes())
    blob_path.write_bytes(teamcrypto.encrypt("age1fake-v2", v1_plain))  # rotated, uncommitted
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                           capture_output=True, text=True)
    assert dirty.stdout.strip()                      # precondition: tree IS dirty

    # --- Resume: must complete to v2, NOT raise the misleading network error ---
    msg = team.rekey("alpha")
    assert "v2" in msg
    assert team._read_committed_meta(repo)["key_version"] == 2
    # leader's page readable under the NEW key, full markdown preserved
    assert teamcrypto.decrypt(
        team.key_path("alpha"), blob_path.read_bytes()).endswith(b"SECRET-E\n")
    assert team._local_generation(team.load_local("alpha")) == 2
    assert not team.prev_key_path("alpha").exists()
    assert not marker.exists()
    # tree is clean again (the rotation is now committed)
    end = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                         capture_output=True, text=True)
    assert not end.stdout.strip()
