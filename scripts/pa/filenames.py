"""Pure-stdlib filename-privacy primitives (spec §2–§4). No age, no git — so
the security-critical hashing logic runs in CI without the age binary.

filename = HMAC-SHA256(fnkey, canonical root-relative path), truncated to 16
bytes (32 hex chars), plus ".age". Real paths never appear in a hashed
filename; they live only inside the age-encrypted manifest."""
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

# Highest team.json schema this client understands: 1 = plain, 2 = filename
# privacy on, 3 = the team has at least one shared memory card. The read gate
# accepts anything <= this and refuses higher (a future schema it can't read)
# — see team._read_committed_meta.
MAX_KNOWN_SCHEMA = 3   # 1 = plain, 2 = filename privacy, 3 = memory cards present

# The source roots a member namespace may contain. The root is always taken
# from the git DIRECTORY (members/<m>/<root>/…), never from manifest contents —
# manifest values are written by whoever owns the namespace, and letting them
# choose the root would let a member decide whether their content auto-loads
# into everyone else's session-start context (spec §4 invariant 6).
SHARED_ROOTS = ("wiki", "memory")


def hash_input(root: str, rel: str) -> str:
    """The HMAC input for a blob in `root` with root-relative path `rel`.

    wiki keeps 0.4.0's bare `rel` (so existing hashed teams need no migration);
    other roots are domain-separated by a NUL, which cannot occur in a POSIX
    path, so the input spaces are provably disjoint. A "memory/" prefix would
    NOT be disjoint: a legitimate wiki page at wiki/memory/notes.md has
    rel == "memory/notes.md" and would collide with a card named notes.

    This is the ONLY definition. share_card, _rebase_to_hashed and
    _validate_fnkey must all call it — never inline the rule. (`share`'s wiki
    path is exempt: its input IS the bare rel by definition, which is what
    keeps 0.4.0 hashed teams resolvable.)

    Disjointness holds for rels derived from the filesystem, which cannot carry
    a NUL. A rel read back out of manifest JSON could, so callers that resolve
    a manifest value MUST reject embedded NUL alongside absolute/`..` paths
    before using it."""
    return rel if root == "wiki" else f"{root}\x00{rel}"


_HASHED_RE = re.compile(r"^[0-9a-f]{32}\.age$")


def hmac_filename(fnkey: bytes, relpath: str) -> str:
    """32-hex keyed hash of a canonical root-relative path (no extension)."""
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
    if not all(isinstance(v, str) for v in obj.values()):
        # Validate the VALUE TYPE once, here at the boundary, rather than at each
        # consumer. A manifest is content written by whichever member owns that
        # namespace, and JSON admits ints, nulls, lists and objects. Consumers
        # assume strings in ways that raise rather than refuse: Path(12345) is a
        # TypeError, set.add((root, ["a"])) is unhashable, and "x".encode() on an
        # int is an AttributeError — each of which kills sync mid-run, leaving
        # last_synced_commit unadvanced so the next sync re-reads the same
        # manifest and dies again, forever, for every member. Rejecting the whole
        # manifest routes the member into bad_manifest_members, which is the
        # right semantics: this is a structurally invalid manifest, not one bad
        # entry, and skip-don't-poison keeps their last-good cache.
        raise ValueError("manifest values must be strings")
    return obj
