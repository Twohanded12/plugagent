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
