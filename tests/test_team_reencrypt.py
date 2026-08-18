import pytest

from pa import config, team, teamcrypto
from tests.team_helpers import fake_crypto, make_remote


@pytest.fixture()
def joined(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    team.init_team("alpha", str(remote), "lead")
    return tmp_path, remote


def _put_blob(name, member, rel, recipient, data):
    dest = team.repo_dir(name) / "members" / member / "wiki" / (rel + ".age")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(teamcrypto.encrypt(recipient, data))
    return dest


def test_reencrypt_rewrites_and_is_idempotent(joined):
    # seal a page with gen-1 recipient, then re-encrypt to gen-2
    v1_key = team.key_path("alpha")                 # FAKEKEY-v1
    v2_recipient, v2_key = teamcrypto.keygen(team.team_dir("alpha") / "stage")
    blob_path = _put_blob("alpha", "lead", "concepts/a", "age1fake-v1", b"BODY")
    failures = team._reencrypt_namespace(
        team.repo_dir("alpha"), "lead", new_key=v2_key, prev_key=v1_key,
        new_recipient=v2_recipient)
    assert failures == []
    assert teamcrypto.decrypt(v2_key, blob_path.read_bytes()) == b"BODY"
    # idempotent: running again with the same keys skips (already v2), no failure
    assert team._reencrypt_namespace(
        team.repo_dir("alpha"), "lead", new_key=v2_key, prev_key=v1_key,
        new_recipient=v2_recipient) == []


def test_reencrypt_skips_corrupt_without_losing_original(joined):
    v1_key = team.key_path("alpha")
    v2_recipient, v2_key = teamcrypto.keygen(team.team_dir("alpha") / "stage")
    good = _put_blob("alpha", "lead", "good", "age1fake-v1", b"GOOD")
    bad = team.repo_dir("alpha") / "members/lead/wiki/bad.md.age"
    bad.write_bytes(b"NOT-A-VALID-BLOB")
    failures = team._reencrypt_namespace(
        team.repo_dir("alpha"), "lead", new_key=v2_key, prev_key=v1_key,
        new_recipient=v2_recipient)
    assert "members/lead/wiki/bad.md.age" in failures
    assert bad.read_bytes() == b"NOT-A-VALID-BLOB"        # original untouched
    assert teamcrypto.decrypt(v2_key, good.read_bytes()) == b"GOOD"


def test_reencrypt_only_touches_the_members_namespace(joined):
    v1_key = team.key_path("alpha")
    v2_recipient, v2_key = teamcrypto.keygen(team.team_dir("alpha") / "stage")
    mine = _put_blob("alpha", "lead", "mine", "age1fake-v1", b"MINE")
    theirs = _put_blob("alpha", "bob", "theirs", "age1fake-v1", b"THEIRS")
    team._reencrypt_namespace(team.repo_dir("alpha"), "lead",
                              new_key=v2_key, prev_key=v1_key, new_recipient=v2_recipient)
    assert teamcrypto.decrypt(v2_key, mine.read_bytes()) == b"MINE"
    # bob's page is NOT re-encrypted (still v1)
    assert teamcrypto.decrypt(v1_key, theirs.read_bytes()) == b"THEIRS"


def test_reencrypt_refuses_symlinked_age(joined, tmp_path):
    v1_key = team.key_path("alpha")
    v2_recipient, v2_key = teamcrypto.keygen(team.team_dir("alpha") / "stage")
    outside = tmp_path / "outside-secret"
    outside.write_bytes(b"OUTSIDE")
    base = team.repo_dir("alpha") / "members/lead/wiki"
    base.mkdir(parents=True, exist_ok=True)
    link = base / "sneaky.md.age"
    link.symlink_to(outside)
    failures = team._reencrypt_namespace(
        team.repo_dir("alpha"), "lead", new_key=v2_key, prev_key=v1_key,
        new_recipient=v2_recipient)
    assert "members/lead/wiki/sneaky.md.age" in failures
    assert link.is_symlink() and link.resolve() == outside.resolve()  # not followed/rewritten
    assert outside.read_bytes() == b"OUTSIDE"                          # target untouched


def test_reencrypt_rotates_manifest_above_wiki(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    repo = tmp_path / "repo"
    ns = repo / "members" / "alice"
    (ns / "wiki").mkdir(parents=True)
    r1, k1 = teamcrypto.keygen(tmp_path / "g1")
    (ns / "wiki" / ("a" * 32 + ".age")).write_bytes(teamcrypto.encrypt(r1, b"# page"))
    team._write_manifest(ns / "manifest.age", r1, {"a" * 32: "concepts/auth.md"})
    r2, k2 = teamcrypto.keygen(tmp_path / "g2")
    team._reencrypt_namespace(repo, "alice", new_key=k2, prev_key=k1,
                              new_recipient=r2)
    assert team._read_manifest(ns / "manifest.age", k2, None) == {"a" * 32: "concepts/auth.md"}


def test_reencrypt_manifest_is_idempotent(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    repo = tmp_path / "repo"
    ns = repo / "members" / "alice"
    (ns / "wiki").mkdir(parents=True)
    r2, k2 = teamcrypto.keygen(tmp_path / "g2")
    team._write_manifest(ns / "manifest.age", r2, {"a" * 32: "x.md"})   # already gen 2
    before = (ns / "manifest.age").read_bytes()
    team._reencrypt_namespace(repo, "alice", new_key=k2, prev_key=k2, new_recipient=r2)
    assert (ns / "manifest.age").read_bytes() == before


def test_reencrypt_rotates_the_memory_root(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    repo = tmp_path / "repo"
    ns = repo / "members" / "alice"
    (ns / "memory").mkdir(parents=True)
    r1, k1 = teamcrypto.keygen(tmp_path / "g1")
    (ns / "memory" / "lint.md.age").write_bytes(teamcrypto.encrypt(r1, b"card"))
    r2, k2 = teamcrypto.keygen(tmp_path / "g2")
    team._reencrypt_namespace(repo, "alice", new_key=k2, prev_key=k1, new_recipient=r2)
    assert teamcrypto.decrypt(k2, (ns / "memory" / "lint.md.age").read_bytes()) == b"card"
