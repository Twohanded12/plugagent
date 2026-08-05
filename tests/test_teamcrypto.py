import shutil
import stat

import pytest

from pa import teamcrypto

needs_age = pytest.mark.skipif(
    shutil.which("age") is None or shutil.which("age-keygen") is None,
    reason="age not installed")


def test_have_age_reports_boolean():
    assert isinstance(teamcrypto.have_age(), bool)


def test_missing_age_raises_actionable_error(monkeypatch):
    monkeypatch.setattr(teamcrypto, "have_age", lambda: False)
    with pytest.raises(RuntimeError, match="brew install age"):
        teamcrypto.require_age()


def test_keygen_refuses_existing_key(tmp_path, monkeypatch):
    monkeypatch.setattr(teamcrypto, "require_age", lambda: None)

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(teamcrypto.subprocess, "run", _boom)
    dest = tmp_path / "dest"
    dest.mkdir(parents=True)
    (dest / "team.key").write_text("existing key material", encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing to overwrite existing key"):
        teamcrypto.keygen(dest)


def test_encrypt_rejects_bad_recipient(monkeypatch):
    monkeypatch.setattr(teamcrypto, "require_age", lambda: None)
    with pytest.raises(teamcrypto.EncryptError):
        teamcrypto.encrypt("notage", b"data")


@needs_age
def test_keygen_encrypt_decrypt_roundtrip(tmp_path):
    recipient, identity = teamcrypto.keygen(tmp_path)
    assert recipient.startswith("age1")
    assert identity.exists()
    assert stat.S_IMODE(identity.stat().st_mode) == 0o600
    src = tmp_path / "page.md"
    src.write_text("secret plaintext body", encoding="utf-8")
    blob = teamcrypto.encrypt(recipient, src.read_bytes())
    assert b"secret plaintext body" not in blob
    assert teamcrypto.decrypt(identity, blob) == src.read_bytes()


@needs_age
def test_verify_key_detects_mismatch(tmp_path):
    recipient_a, identity_a = teamcrypto.keygen(tmp_path / "a")
    _recipient_b, identity_b = teamcrypto.keygen(tmp_path / "b")
    assert teamcrypto.verify_key(identity_a, recipient_a) is True
    assert teamcrypto.verify_key(identity_b, recipient_a) is False


@needs_age
def test_decrypt_corrupt_blob_raises(tmp_path):
    recipient, identity = teamcrypto.keygen(tmp_path)
    with pytest.raises(teamcrypto.DecryptError):
        teamcrypto.decrypt(identity, b"not an age blob at all")
