import json
import subprocess

import pytest

from pa import config, team, teamcrypto, teamgit
from tests.team_helpers import fake_crypto, make_remote


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    return tmp_path, remote


def test_init_creates_repo_meta_and_key(env):
    tmp_path, remote = env
    team.init_team("alpha", str(remote), "lead")
    committed = json.loads(
        subprocess.run(["git", "-C", str(team.repo_dir("alpha")), "show",
                        "HEAD:team.json"], capture_output=True, text=True).stdout)
    assert committed == {"name": "alpha", "recipient": "age1fake-v1",
                        "schema_version": 1}
    assert team.key_path("alpha").exists()
    local = team.load_local("alpha")
    assert local["member"] == "lead"        # leader claims namespace at init


def test_join_validates_and_builds_cache(env, tmp_path, monkeypatch):
    _tmp, remote = env
    team.init_team("alpha", str(remote), "lead")
    # simulate a second machine: fresh home
    home2 = tmp_path / "home2"
    key_copy = tmp_path / "received.key"
    key_copy.write_text("FAKEKEY-v1")
    monkeypatch.setenv("PLUGAGENT_HOME", str(home2))
    config.set_value("vault", str(tmp_path / "vault2"))
    team.join_team(str(remote), key_copy, "alice")
    local = team.load_local("alpha")        # name read from committed team.json
    assert local["member"] == "alice"
    assert team.key_path("alpha").read_text() == "FAKEKEY-v1"
    assert oct(team.key_path("alpha").stat().st_mode).endswith("600")


def test_join_rejects_bad_member_name(env, tmp_path):
    _tmp, remote = env
    team.init_team("alpha", str(remote), "lead")
    key = tmp_path / "k"; key.write_text("FAKEKEY-v1")
    with pytest.raises(team.TeamError, match="invalid member name"):
        team.join_team(str(remote), key, "Not/Safe")


def test_join_rejects_wrong_key(env, tmp_path, monkeypatch):
    _tmp, remote = env
    team.init_team("alpha", str(remote), "lead")
    # second machine — otherwise the already-joined guard fires before key check
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home2"))
    config.set_value("vault", str(tmp_path / "vault2"))
    bad = tmp_path / "bad.key"; bad.write_text("WRONG")
    with pytest.raises(team.TeamError, match="key does not match"):
        team.join_team(str(remote), bad, "alice")


def test_join_rejects_taken_member_name(env, tmp_path, monkeypatch):
    _tmp, remote = env
    team.init_team("alpha", str(remote), "lead")
    # leader claims 'alice' by pushing a namespace marker
    repo = team.repo_dir("alpha")
    marker = repo / "members" / "alice" / "wiki" / "x.md.age"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"FAKEAGE:x")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "m"], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q"], check=True)
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home2"))
    config.set_value("vault", str(tmp_path / "vault2"))
    key = tmp_path / "k"; key.write_text("FAKEKEY-v1")
    with pytest.raises(team.TeamError, match="already taken"):
        team.join_team(str(remote), key, "alice")


def test_init_push_failure_cleans_up(env, monkeypatch):
    tmp_path, remote = env

    def boom(repo):
        raise teamgit.PushError("network down")

    monkeypatch.setattr(teamgit, "push_with_rebase", boom)
    with pytest.raises(teamgit.PushError):
        team.init_team("alpha", str(remote), "lead")
    assert not team.team_dir("alpha").exists()
    # retry doesn't get stuck behind a phantom "already exists" — it gets
    # past that guard and fails the same clean way again
    with pytest.raises(teamgit.PushError):
        team.init_team("alpha", str(remote), "lead")
    assert not team.team_dir("alpha").exists()


def test_join_failure_cleans_up(env, tmp_path, monkeypatch):
    _tmp, remote = env
    team.init_team("alpha", str(remote), "lead")
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home2"))
    config.set_value("vault", str(tmp_path / "vault2"))
    key_copy = tmp_path / "received2.key"
    key_copy.write_text("FAKEKEY-v1")

    def boom(name, cfg):
        raise RuntimeError("disk full")

    monkeypatch.setattr(team, "save_local", boom)
    with pytest.raises(RuntimeError):
        team.join_team(str(remote), key_copy, "alice")
    assert not team.team_dir("alpha").exists()


def test_join_wipes_markerless_debris(env, tmp_path, monkeypatch):
    # T4 carry-forward: config presence (team.json) is the "joined" marker.
    # A team_dir that exists WITHOUT it is SIGKILL debris from an interrupted
    # join, not a completed join — it must be wiped, not treated as a
    # collision.
    _tmp, remote = env
    team.init_team("alpha", str(remote), "lead")
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home2"))
    config.set_value("vault", str(tmp_path / "vault2"))
    key_copy = tmp_path / "received3.key"
    key_copy.write_text("FAKEKEY-v1")
    debris = team.team_dir("alpha")
    debris.mkdir(parents=True)
    (debris / "junk.txt").write_text("leftover from a killed join")
    team.join_team(str(remote), key_copy, "alice")
    local = team.load_local("alpha")
    assert local["member"] == "alice"
    assert not (debris / "junk.txt").exists()


def test_join_rejects_bad_meta(env, tmp_path):
    _tmp, remote = env
    # push a team.json missing "recipient" — not init_team, which always
    # writes a valid one; simulate a hand-rolled/corrupted leader repo.
    work = tmp_path / "leader_work"
    teamgit.clone(str(remote), work)
    (work / "team.json").write_text(
        json.dumps({"name": "alpha", "schema_version": 1}) + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "team.json"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-q", "-m", "bad meta"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q"], check=True)
    key = tmp_path / "k"; key.write_text("FAKEKEY-v1")
    with pytest.raises(team.TeamError, match="not a valid"):
        team.join_team(str(remote), key, "alice")


def test_dispatcher_team_flag_missing_value(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    from pa.__main__ import main
    rc = main(["team", "sync", "--team"])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "pa: --team needs a value"
