"""Shared fixtures/helpers for the team layer tests (join, sync, share).
Moved verbatim out of test_team_join.py so test_team_sync_share.py can reuse
them without duplicating the fake age boundary or the bare-remote setup."""
import subprocess
from pathlib import Path

from pa import teamcrypto


def fake_crypto(monkeypatch):
    monkeypatch.setattr(teamcrypto, "require_age", lambda: None)
    monkeypatch.setattr(teamcrypto, "have_age", lambda: True)
    monkeypatch.setattr(teamcrypto, "keygen",
                        lambda d: ("age1fake", _write_fake_key(d)))
    monkeypatch.setattr(teamcrypto, "encrypt",
                        lambda r, data: b"FAKEAGE:" + data)
    monkeypatch.setattr(
        teamcrypto, "decrypt",
        lambda i, blob: blob[len(b"FAKEAGE:"):] if blob.startswith(b"FAKEAGE:")
        else (_ for _ in ()).throw(teamcrypto.DecryptError("bad blob")))
    monkeypatch.setattr(teamcrypto, "verify_key",
                        lambda i, r: i.read_text().strip() == "FAKEKEY" and r == "age1fake")


def _write_fake_key(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / "team.key"
    p.write_text("FAKEKEY")
    return p


def make_remote(tmp_path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    return remote
