"""Shared fixtures/helpers for the team layer tests (join, sync, share).
Moved verbatim out of test_team_join.py so test_team_sync_share.py can reuse
them without duplicating the fake age boundary or the bare-remote setup."""
import re as _re
from pathlib import Path

from pa import teamcrypto


def fake_crypto(monkeypatch):
    # NOTE: this fake models key *generation* (the trailing v{N}), not full
    # key identity — two distinct real-age keys never interoperate, but
    # same-generation fake keys do; fine for single-team rekey, do NOT write
    # cross-team key-isolation tests against it.
    monkeypatch.setattr(teamcrypto, "require_age", lambda: None)
    monkeypatch.setattr(teamcrypto, "have_age", lambda: True)

    def _keygen(dest_dir: Path):
        # mirror real keygen: refuse to overwrite; write into dest_dir/team.key
        dest_dir.mkdir(parents=True, exist_ok=True)
        key = dest_dir / "team.key"
        if key.exists():
            raise RuntimeError(f"refusing to overwrite existing key {key}")
        # each generated key is a fresh generation, tracked by a per-fixture
        # counter (reset each fake_crypto call)
        _keygen.n += 1
        gen = _keygen.n
        key.write_text(f"FAKEKEY-v{gen}")
        return f"age1fake-v{gen}", key
    _keygen.n = 0
    monkeypatch.setattr(teamcrypto, "keygen", _keygen)

    def _encrypt(recipient, data):
        m = _re.search(r"v(\d+)$", recipient)
        if not m:
            raise teamcrypto.EncryptError(f"invalid recipient {recipient!r}")
        return b"FAKEAGE:v" + m.group(1).encode() + b":" + data
    monkeypatch.setattr(teamcrypto, "encrypt", _encrypt)

    def _decrypt(identity, blob):
        km = _re.search(r"v(\d+)$", Path(identity).read_text())
        bm = _re.match(rb"FAKEAGE:v(\d+):", blob)
        if not km or not bm or km.group(1) != bm.group(1).decode():
            raise teamcrypto.DecryptError("bad blob or wrong generation")
        return blob[bm.end():]
    monkeypatch.setattr(teamcrypto, "decrypt", _decrypt)

    def _verify_key(identity, recipient):
        try:
            return _decrypt(identity, _encrypt(recipient, b"probe")) == b"probe"
        except (teamcrypto.DecryptError, teamcrypto.EncryptError):
            return False
    monkeypatch.setattr(teamcrypto, "verify_key", _verify_key)


def make_remote(tmp_path):
    import subprocess
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    return remote
