"""Pure-stdlib filename-privacy primitives (spec §2–§4). No age, no git — so
the security-critical hashing logic runs in CI without the age binary.

filename = HMAC-SHA256(fnkey, canonical wiki-relative path), truncated to 16
bytes (32 hex chars), plus ".age". Real paths never appear in a hashed
filename; they live only inside the age-encrypted manifest."""
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

# Highest team.json schema this client understands. Plain teams are schema 1
# (Phase 2/3); a team that has turned on filename privacy is schema 2. The
# read gate accepts anything <= this and refuses higher (a future schema it
# can't read) — see team._read_committed_meta.
MAX_KNOWN_SCHEMA = 2

_HASHED_RE = re.compile(r"^[0-9a-f]{32}\.age$")


def hmac_filename(fnkey: bytes, relpath: str) -> str:
    """32-hex keyed hash of a canonical wiki-relative path (no extension)."""
    digest = hmac.new(fnkey, relpath.encode("utf-8"), hashlib.sha256).digest()
    return digest[:16].hex()


def is_hashed_age(name: str) -> bool:
    """True iff `name` is a hashed page filename (<32hex>.age). Deliberately
    False for `manifest.age` and for plaintext page names like
    `concepts/auth.md.age`, so sync can dispatch per-file by shape."""
    return bool(_HASHED_RE.fullmatch(name))


def gen_fnkey() -> bytes:
    """A fresh independent 32-byte filename key (NOT derived from the age key —
    spec §4: deriving it would let any age-key holder recompute filenames and
    defeat the read/write split)."""
    return os.urandom(32)


def fnkey_path(team_dir: Path) -> Path:
    return team_dir / "fnkey"


def privacy_marker(team_dir: Path) -> Path:
    """Local-only, never-committed record that a privacy transition is
    in-flight (mirrors team._rekey_marker's .rekey-target)."""
    return team_dir / ".privacy-target"


def manifest_to_bytes(mapping: dict) -> bytes:
    """Canonical (sorted-key) JSON bytes of a {hash: relpath} map."""
    return (json.dumps(mapping, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def bytes_to_manifest(data: bytes) -> dict:
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("manifest is not a JSON object")
    return obj
