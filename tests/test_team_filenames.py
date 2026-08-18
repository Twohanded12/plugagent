import re
import pytest
from pa import filenames as fn


def test_hmac_filename_is_deterministic_and_idempotent():
    key = b"\x11" * 32
    a = fn.hmac_filename(key, "concepts/auth.md")
    b = fn.hmac_filename(key, "concepts/auth.md")
    assert a == b


def test_hmac_filename_is_32_lowercase_hex():
    key = b"\x11" * 32
    h = fn.hmac_filename(key, "concepts/auth.md")
    assert re.fullmatch(r"[0-9a-f]{32}", h)


def test_different_fnkey_yields_different_filename():
    h1 = fn.hmac_filename(b"\x11" * 32, "concepts/auth.md")
    h2 = fn.hmac_filename(b"\x22" * 32, "concepts/auth.md")
    assert h1 != h2


def test_different_path_yields_different_filename():
    key = b"\x11" * 32
    assert fn.hmac_filename(key, "a.md") != fn.hmac_filename(key, "b.md")


def test_is_hashed_age_true_only_for_32hex_dot_age():
    assert fn.is_hashed_age("0123456789abcdef0123456789abcdef.age")
    assert not fn.is_hashed_age("manifest.age")
    assert not fn.is_hashed_age("concepts/auth.md.age")
    assert not fn.is_hashed_age("0123456789abcdef0123456789abcdef.md")
    assert not fn.is_hashed_age("0123456789ABCDEF0123456789abcdef.age")


def test_gen_fnkey_is_32_random_bytes():
    a, b = fn.gen_fnkey(), fn.gen_fnkey()
    assert isinstance(a, bytes) and len(a) == 32
    assert a != b


def test_manifest_codec_round_trips():
    m = {"0123456789abcdef0123456789abcdef": "concepts/auth.md",
         "fedcba9876543210fedcba9876543210": "projects/x.md"}
    assert fn.bytes_to_manifest(fn.manifest_to_bytes(m)) == m


def test_manifest_to_bytes_is_canonical_sorted():
    m1 = {"b" * 32: "b.md", "a" * 32: "a.md"}
    m2 = {"a" * 32: "a.md", "b" * 32: "b.md"}
    assert fn.manifest_to_bytes(m1) == fn.manifest_to_bytes(m2)


def test_bytes_to_manifest_rejects_non_object():
    with pytest.raises(ValueError):
        fn.bytes_to_manifest(b"[]")


def test_shared_roots_are_wiki_and_memory():
    assert fn.SHARED_ROOTS == ("wiki", "memory")


def test_hash_input_wiki_is_the_bare_rel_for_0_4_0_compat():
    # wiki entries must hash EXACTLY as they did in 0.4.0, or every existing
    # hashed team's filenames become unresolvable.
    assert fn.hash_input("wiki", "concepts/auth.md") == "concepts/auth.md"


def test_hash_input_memory_is_nul_separated():
    assert fn.hash_input("memory", "lint.md") == "memory\x00lint.md"


def test_hash_input_domain_separation_is_injective():
    # The collision the "memory/" prefix scheme would have: a legitimate wiki
    # page at wiki/memory/notes.md vs a memory card named notes.
    wiki_page = fn.hash_input("wiki", "memory/notes.md")
    memory_card = fn.hash_input("memory", "notes.md")
    assert wiki_page != memory_card
    assert fn.hmac_filename(b"\x11" * 32, wiki_page) != \
        fn.hmac_filename(b"\x11" * 32, memory_card)


def test_hash_input_nul_cannot_come_from_a_real_path(tmp_path):
    # NUL is the separator precisely because the OS refuses it in a filename, so
    # no rel walked off disk can forge a memory-form input. This asserts the
    # platform premise the disjointness proof rests on, not a Python literal.
    with pytest.raises(ValueError):                 # rejected before the syscall
        (tmp_path / "memory\x00notes.md").write_text("x")
    page = tmp_path / "memory" / "notes.md"
    page.parent.mkdir()
    page.write_text("x")
    rel = page.relative_to(tmp_path).as_posix()     # "memory/notes.md"
    assert "\x00" not in rel
    assert fn.hash_input("wiki", rel) != fn.hash_input("memory", "notes.md")


@pytest.mark.parametrize("bad", [12345, None, ["a"], {"a": 1}, True])
def test_bytes_to_manifest_rejects_non_string_values(bad):
    # Each of these kills a different consumer if it gets through: Path() raises
    # TypeError, set.add() raises unhashable, .encode() raises AttributeError.
    import json as _json
    blob = _json.dumps({"a" * 32: bad}).encode("utf-8")
    with pytest.raises(ValueError, match="strings"):
        fn.bytes_to_manifest(blob)


def test_bytes_to_manifest_accepts_a_normal_manifest():
    import json as _json
    m = {"a" * 32: "concepts/auth.md"}
    assert fn.bytes_to_manifest(_json.dumps(m).encode("utf-8")) == m

