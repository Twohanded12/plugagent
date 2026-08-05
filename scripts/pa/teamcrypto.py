"""age subprocess wrapper — the ONLY crypto boundary. We implement no crypto.

Team mode requires the `age` and `age-keygen` binaries; personal mode never
imports this module's operational functions.
"""
import re
import shutil
import subprocess
from pathlib import Path


class DecryptError(Exception):
    pass


class EncryptError(Exception):
    pass


def have_age() -> bool:
    return bool(shutil.which("age") and shutil.which("age-keygen"))


def require_age() -> None:
    if not have_age():
        raise RuntimeError(
            "team mode needs the 'age' encryption tool — install it with "
            "`brew install age` (macOS) and retry")


def keygen(dest_dir: Path) -> tuple[str, Path]:
    """Generate a team keypair. Returns (recipient, identity_path)."""
    require_age()
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = dest_dir / "team.key"
    if identity.exists():
        raise RuntimeError(
            f"refusing to overwrite existing key {identity} — move it away first")
    out = subprocess.run(
        ["age-keygen", "-o", str(identity)],
        capture_output=True, text=True, check=True)
    identity.chmod(0o600)
    text = out.stdout + out.stderr + identity.read_text(encoding="utf-8")
    m = re.search(r"(age1[0-9a-z]+)", text)
    if not m:
        raise RuntimeError("age-keygen succeeded but no recipient found")
    return m.group(1), identity


def encrypt(recipient: str, data: bytes) -> bytes:
    require_age()
    if not recipient.startswith("age1"):
        raise EncryptError(f"invalid recipient {recipient!r}")
    out = subprocess.run(["age", "-r", recipient],
                         input=data, capture_output=True)
    if out.returncode != 0:
        raise EncryptError(out.stderr.decode(errors="replace").strip())
    return out.stdout


def decrypt(identity: Path, blob: bytes) -> bytes:
    require_age()
    out = subprocess.run(["age", "-d", "-i", str(identity)],
                         input=blob, capture_output=True)
    if out.returncode != 0:
        raise DecryptError(out.stderr.decode(errors="replace").strip())
    return out.stdout


def verify_key(identity: Path, recipient: str) -> bool:
    """Trial round-trip: does this identity decrypt what this recipient encrypts?"""
    probe = b"plugagent-key-verification-probe"
    try:
        return decrypt(identity, encrypt(recipient, probe)) == probe
    except (DecryptError, EncryptError, subprocess.CalledProcessError):
        return False
