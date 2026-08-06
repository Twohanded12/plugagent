import json

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


def test_committed_meta_defaults_key_version_to_1(joined):
    # init writes no key_version → reads as generation 1 (legacy migration)
    meta = team._read_committed_meta(team.repo_dir("alpha"))
    assert meta["key_version"] == 1
    # schema_version must stay 1 (additive field only)
    raw = json.loads((team.repo_dir("alpha") / "team.json").read_text())
    assert raw["schema_version"] == 1


def test_local_generation_defaults_to_1(joined):
    assert team._local_generation(team.load_local("alpha")) == 1


def test_prev_key_path(joined):
    assert team.prev_key_path("alpha").name == "team.key.prev"
    assert team.prev_key_path("alpha").parent == team.team_dir("alpha")
