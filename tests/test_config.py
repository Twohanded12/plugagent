import json

import pytest

from pa import config


@pytest.fixture(autouse=True)
def pa_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    return tmp_path


def test_load_returns_defaults_when_no_file():
    cfg = config.load()
    assert cfg["schema_version"] == config.SCHEMA_VERSION
    assert cfg["agent_name"] is None
    assert cfg["capture"] == "off"
    assert cfg["exclude"] == []


def test_set_and_get_roundtrip():
    config.set_value("agent_name", "Nova")
    assert config.load()["agent_name"] == "Nova"
    assert json.loads(config.config_path().read_text())["agent_name"] == "Nova"


def test_exclude_list_parsed_as_json():
    config.set_value("exclude", '["/tmp/secret", "/work/private"]')
    assert config.load()["exclude"] == ["/tmp/secret", "/work/private"]


def test_unknown_key_rejected():
    with pytest.raises(KeyError):
        config.set_value("nope", "x")


def test_vault_expands_user(tmp_path):
    config.set_value("vault", str(tmp_path / "vault"))
    assert config.vault() == tmp_path / "vault"


def test_reserved_names_rejected():
    assert config.name_error("Claude") is not None
    assert config.name_error("plugagent") is not None
    assert config.name_error("") is not None
    assert config.name_error("Nova") is None


def test_vault_guard_first_run_creates_then_refuses_after_loss(tmp_path):
    import shutil
    config.set_value("vault", str(tmp_path / "vault"))
    assert config.vault_guard() is True          # first run: creates + marker
    assert config.vault().exists()
    shutil.rmtree(config.vault())
    assert config.vault_guard() is False         # lost vault: never recreate
    assert not config.vault().exists()
    assert (config.state_dir() / "vault_missing").exists()


def test_vault_reinit_allows_fresh_start(tmp_path):
    import shutil
    config.set_value("vault", str(tmp_path / "vault"))
    config.vault_guard()
    shutil.rmtree(config.vault())
    config.vault_guard()                         # sets vault_missing
    config.vault_reinit()
    assert config.vault_guard() is True          # treated as first run again
    assert config.vault().exists()


def test_restored_vault_clears_missing_flag(tmp_path):
    import shutil
    config.set_value("vault", str(tmp_path / "vault"))
    config.vault_guard()
    shutil.rmtree(config.vault())
    config.vault_guard()                         # sets vault_missing
    config.vault().mkdir(parents=True)           # user restores the vault
    assert config.vault_guard() is True
    assert not (config.state_dir() / "vault_missing").exists()


def test_capture_toggle_rejects_invalid_values():
    with pytest.raises(ValueError):
        config.set_value("capture", "offf")
    config.set_value("capture", "off")
    assert config.load()["capture"] == "off"


def test_set_agent_name_rejects_reserved_via_cli_path():
    with pytest.raises(ValueError):
        config.set_value("agent_name", "Claude")
    config.set_value("agent_name", "Nova")
    assert config.load()["agent_name"] == "Nova"
