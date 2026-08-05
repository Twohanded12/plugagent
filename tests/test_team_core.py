import json

import pytest

from pa import config, team


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    return tmp_path


def test_member_name_rules():
    assert team.member_name_error("alice") is None
    assert team.member_name_error("bob-2") is None
    for bad in ("", "Alice", "a/b", "a..b", "a b", "한글", "-lead", "x" * 33,
                "abc\n", "abc\ndef"):
        assert team.member_name_error(bad) is not None, bad


def test_local_config_roundtrip(tmp_path):
    team.save_local("alpha", {"repo_url": "u", "member": "alice",
                              "last_sync": 0, "last_synced_commit": None,
                              "schema_version": 1})
    cfg = team.load_local("alpha")
    assert cfg["member"] == "alice"
    assert (team.team_dir("alpha") / "team.json").exists()


def test_needs_sync_ttl():
    assert team.needs_sync(0, 900, now=1000) is True
    assert team.needs_sync(500, 900, now=1000) is False
    assert team.needs_sync(100, 900, now=1001) is True


def test_resolve_team_zero_one_many(tmp_path):
    with pytest.raises(team.TeamError, match="no team"):
        team.resolve_team(None)
    team.save_local("alpha", {"member": "a"})
    assert team.resolve_team(None) == "alpha"
    team.save_local("beta", {"member": "a"})
    with pytest.raises(team.TeamError, match="alpha.*beta|beta.*alpha"):
        team.resolve_team(None)
    assert team.resolve_team("beta") == "beta"
    with pytest.raises(team.TeamError, match="unknown team"):
        team.resolve_team("gamma")


def test_team_dir_rejects_unsafe_names():
    for bad in ("../evil", "A", "a/b"):
        with pytest.raises(team.TeamError):
            team.team_dir(bad)


def test_load_local_wraps_corrupt_json(tmp_path):
    d = team.team_dir("alpha")
    d.mkdir(parents=True, exist_ok=True)
    (d / "team.json").write_text("not json{", encoding="utf-8")
    with pytest.raises(team.TeamError, match="corrupt"):
        team.load_local("alpha")
