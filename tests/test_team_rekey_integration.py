import shutil
import subprocess
from pathlib import Path

import pytest

from pa import config, team, teamcrypto
from tests.team_helpers import fake_crypto, make_remote

needs_age = pytest.mark.skipif(shutil.which("age") is None, reason="age not installed")


def _home(monkeypatch, tmp_path, tag):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / f"home-{tag}"))
    config.set_value("vault", str(tmp_path / f"vault-{tag}"))


def _put_page(rel, desc, body):
    from pa import distill
    distill.wiki_put(rel, f"---\ndescription: {desc}\n---\n\n{body}\n")


def _cycle(tmp_path, monkeypatch, use_fake):
    if use_fake:
        fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)

    # Leader L init + share; capture v1 key for distribution
    _home(monkeypatch, tmp_path, "L")
    team.init_team("acme", str(remote), "lead")
    _put_page("concepts/auth.md", "JWT", "SECRET-L1")
    team.share("acme", "concepts/auth.md")
    key_v1 = tmp_path / "key-v1"; shutil.copy(team.key_path("acme"), key_v1)

    # Members A, B join at v1 and share
    _home(monkeypatch, tmp_path, "A")
    team.join_team(str(remote), key_v1, "amy")
    _put_page("notes/a.md", "Amy", "SECRET-A1")
    team.share("acme", "notes/a.md")
    _home(monkeypatch, tmp_path, "B")
    team.join_team(str(remote), key_v1, "ben")
    _put_page("notes/b.md", "Ben", "SECRET-B1")
    team.share("acme", "notes/b.md")

    # Leader rekeys to v2
    _home(monkeypatch, tmp_path, "L")
    team.rekey("acme")
    key_v2 = tmp_path / "key-v2"; shutil.copy(team.key_path("acme"), key_v2)

    # (a) A, pre-accept, syncs: L's re-encrypted v2 page can't be decrypted yet
    # (A holds only v1) -> skip-don't-poison keeps A's last-good cached copy; the
    # rekey-detected notice is surfaced. A's own unchanged v1 pages stay readable.
    _home(monkeypatch, tmp_path, "A")
    out = team.sync("acme", force=True)
    assert "rekeyed to v2" in out
    # (b) A accepts, then can share again
    team.rekey_accept("acme", key_v2)
    _put_page("notes/a2.md", "Amy2", "SECRET-A2")
    assert "shared" in team.share("acme", "notes/a2.md")
    # (c) B still v1: status pending, share blocked
    _home(monkeypatch, tmp_path, "B")
    team.sync("acme", force=True)
    assert "rekey pending" in team.status_report()
    _put_page("notes/b2.md", "Ben2", "SECRET-B2")
    with pytest.raises(team.TeamError, match="rekeyed"):
        team.share("acme", "notes/b2.md")

    if not use_fake:
        # (d) zero-plaintext through the rekey: dump every object, raw bytes
        dump = subprocess.run(
            ["git", "-C", str(remote), "cat-file", "--batch-all-objects", "--batch"],
            capture_output=True, check=True).stdout
        assert b"auth.md.age" in dump                    # positive control (basename)
        assert b"a.md.age" in dump
        for secret in (b"SECRET-L1", b"SECRET-A1", b"SECRET-B1", b"SECRET-A2"):
            assert secret not in dump
        # (e) forward secrecy: the v1 key cannot open L's re-encrypted v2 page
        # (read from A's clone which is on v2)
        _home(monkeypatch, tmp_path, "A")
        blob = (team.repo_dir("acme") / "members/lead/wiki/concepts/auth.md.age").read_bytes()
        with pytest.raises(teamcrypto.DecryptError):
            teamcrypto.decrypt(key_v1, blob)


def test_rekey_cycle_fake_crypto(tmp_path, monkeypatch):
    _cycle(tmp_path, monkeypatch, use_fake=True)


@needs_age
def test_rekey_cycle_real_age(tmp_path, monkeypatch):
    _cycle(tmp_path, monkeypatch, use_fake=False)
