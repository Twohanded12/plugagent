import time

import pytest

from pa import config, team
from tests.team_helpers import fake_crypto, make_remote


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    fake_crypto(monkeypatch)
    return tmp_path


def test_status_no_teams():
    assert "no team" in team.status_report()


def test_status_reports_per_team(tmp_path):
    remote = make_remote(tmp_path)
    team.init_team("alpha", str(remote), "alice")
    cfg = team.load_local("alpha")
    cfg["decrypt_failures"] = ["members/x/wiki/bad.md.age"]
    team.save_local("alpha", cfg)
    report = team.status_report()
    assert "alpha" in report and "alice" in report
    assert "decrypt failures: 1" in report
    assert "last sync" in report


def test_status_reports_days_old_sync(tmp_path):
    remote = make_remote(tmp_path)
    team.init_team("alpha", str(remote), "alice")
    cfg = team.load_local("alpha")
    cfg["last_sync"] = time.time() - (3 * 86400)
    team.save_local("alpha", cfg)
    report = team.status_report()
    assert "day" in report


def test_status_isolates_corrupt_team(tmp_path):
    remote_a = make_remote(tmp_path / "a")
    remote_b = make_remote(tmp_path / "b")
    team.init_team("alpha", str(remote_a), "alice")
    team.init_team("beta", str(remote_b), "lead")
    (team.team_dir("beta") / "team.json").write_text("not valid json{{{", encoding="utf-8")
    report = team.status_report()
    assert "alpha" in report and "alice" in report
    assert "beta" in report and "ERROR:" in report
