import json
import subprocess

import pytest

from pa import config, team
from tests.team_helpers import fake_crypto, make_remote


@pytest.fixture()
def joined(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    team.init_team("alpha", str(remote), "lead")
    return tmp_path, remote


def test_status_shows_key_version(joined):
    assert "key v1" in team.status_report()


def test_status_shows_rekey_pending_when_behind(joined):
    tmp_path, remote = joined
    d = tmp_path / "o"; subprocess.run(["git", "clone", "-q", str(remote), str(d)], check=True)
    for k, v in (("user.email", "o@o"), ("user.name", "o")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    (d / "team.json").write_text(json.dumps(
        {"name": "alpha", "recipient": "age1fake-v2", "key_version": 2,
         "schema_version": 1}, indent=2) + "\n")
    subprocess.run(["git", "-C", str(d), "commit", "-aqm", "rekey: v2"], check=True)
    subprocess.run(["git", "-C", str(d), "push", "-q"], check=True)
    # local is still v1; a sync pulls the new team.json into the local clone
    team.sync("alpha", force=True)
    report = team.status_report()
    assert "rekey pending" in report and "you v1" in report
