import pytest
from pathlib import Path
from pa import config, team
from tests.team_helpers import fake_crypto, make_remote


def _home(monkeypatch, tmp_path, tag):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / f"home-{tag}"))
    config.set_value("vault", str(tmp_path / f"vault-{tag}"))


def write_wiki_page(rel, desc="desc", body="body"):
    """Write a shareable wiki page into the CURRENT home's vault."""
    from pa import distill
    distill.wiki_put(rel, f"---\ndescription: {desc}\n---\n\n{body}\n")


@pytest.fixture
def home(monkeypatch, tmp_path):
    def _set(tag):
        _home(monkeypatch, tmp_path, tag)
    return _set


@pytest.fixture
def team_env(monkeypatch, tmp_path):
    """Single-member leader team on a bare remote, one plaintext page shared,
    fake age. privacy is OFF at return."""
    fake_crypto(monkeypatch)
    _home(monkeypatch, tmp_path, "L")
    remote = make_remote(tmp_path)
    team.init_team("acme", str(remote), "alice")
    write_wiki_page("concepts/auth.md", "JWT", "SECRET")
    team.share("acme", "concepts/auth.md")
    return {"name": "acme", "remote": remote, "tmp": tmp_path}


import shutil
from pa import filenames


@pytest.fixture
def two_member_env(monkeypatch, tmp_path):
    """Leader alice (privacy ON, one hashed page 'concepts/auth.md') + member
    bob who shared a PLAINTEXT page 'notes/b.md' BEFORE privacy was turned on
    and has NOT accepted (no fnkey). Leaves current home = bob."""
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    _home(monkeypatch, tmp_path, "L")
    team.init_team("acme", str(remote), "alice")
    write_wiki_page("concepts/auth.md", "JWT", "SECRET-L")
    team.share("acme", "concepts/auth.md")
    key_v1 = tmp_path / "key-v1"; shutil.copy(team.key_path("acme"), key_v1)

    _home(monkeypatch, tmp_path, "B")
    team.join_team(str(remote), key_v1, "bob")
    write_wiki_page("notes/b.md", "Bob", "SECRET-B")
    team.share("acme", "notes/b.md")                 # plaintext, pre-privacy

    _home(monkeypatch, tmp_path, "L")
    team.privacy_on("acme")                          # team goes hashed
    fnkey_file = tmp_path / "handed.fnkey"
    shutil.copy(filenames.fnkey_path(team.team_dir("acme")), fnkey_file)

    _home(monkeypatch, tmp_path, "B")                # end as bob
    team.sync("acme", force=True)
    return {"name": "acme", "remote": remote, "fnkey_file": fnkey_file,
            "key_v1": key_v1, "tmp": tmp_path,
            "as_leader": lambda: _home(monkeypatch, tmp_path, "L"),
            "as_bob": lambda: _home(monkeypatch, tmp_path, "B")}


@pytest.fixture
def env_privacy_on_no_pages(monkeypatch, tmp_path):
    """Leader turned privacy ON with ZERO shared pages (empty manifest), member
    bob joined. Leaves current home = bob. Exercises the empty-manifest accept."""
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    _home(monkeypatch, tmp_path, "L")
    team.init_team("acme", str(remote), "alice")     # no share
    key_v1 = tmp_path / "key-v1"; shutil.copy(team.key_path("acme"), key_v1)
    team.privacy_on("acme")
    fnkey_file = tmp_path / "handed.fnkey"
    shutil.copy(filenames.fnkey_path(team.team_dir("acme")), fnkey_file)
    _home(monkeypatch, tmp_path, "B")
    team.join_team(str(remote), key_v1, "bob")
    return {"name": "acme", "fnkey_file": fnkey_file, "tmp": tmp_path}
