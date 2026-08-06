# tests/test_team_privacy_integration.py
import shutil
import subprocess
import pytest
from pathlib import Path
from pa import team, teamcrypto, config, filenames
from tests.team_helpers import fake_crypto, make_remote

needs_age = pytest.mark.skipif(not teamcrypto.have_age(), reason="needs age")


def _home(monkeypatch, tmp_path, tag):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / f"home-{tag}"))
    config.set_value("vault", str(tmp_path / f"vault-{tag}"))


def _put(rel, desc, body):
    from pa import distill
    distill.wiki_put(rel, f"---\ndescription: {desc}\n---\n\n{body}\n")


def _scenario(monkeypatch, tmp_path, use_fake):
    """alice init → alice share(plain 'concepts/auth.md') → bob join →
    bob share(plain 'notes/b.md') → alice privacy on → amy join →
    amy privacy-accept → amy share(hashed 'projects/x.md').
    Returns handles; homes are keyed by member name."""
    if use_fake:
        fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)

    _home(monkeypatch, tmp_path, "alice")
    team.init_team("acme", str(remote), "alice")
    _put("concepts/auth.md", "JWT", "SECRET-L")
    team.share("acme", "concepts/auth.md")
    key_v1 = tmp_path / "key-v1"; shutil.copy(team.key_path("acme"), key_v1)

    _home(monkeypatch, tmp_path, "bob")
    team.join_team(str(remote), key_v1, "bob")
    _put("notes/b.md", "Bob", "SECRET-B")
    team.share("acme", "notes/b.md")                 # plaintext, PRE-privacy

    _home(monkeypatch, tmp_path, "alice")
    team.privacy_on("acme")
    fnkey_file = tmp_path / "handed.fnkey"
    shutil.copy(filenames.fnkey_path(team.team_dir("acme")), fnkey_file)

    _home(monkeypatch, tmp_path, "amy")
    team.join_team(str(remote), key_v1, "amy")
    team.privacy_accept("acme", fnkey_file)
    _put("projects/x.md", "X", "SECRET-A")
    team.share("acme", "projects/x.md")

    def at(member): _home(monkeypatch, tmp_path, member)
    def sync(member): at(member); return team.sync("acme", force=True)
    def accept_privacy(member): at(member); return team.privacy_accept("acme", fnkey_file)
    def hashed_filenames(member):
        at(member)
        base = team.repo_dir("acme") / "members" / member / "wiki"
        return sorted(p.name for p in base.rglob("*.age"))
    def cache_has(member, rel):
        at(member); return (team.cache_dir("acme") / rel).exists()

    def rekey():
        at("alice"); team.rekey("acme")
        newkey = tmp_path / "key-v2"; shutil.copy(team.key_path("acme"), newkey)
        return newkey
    def accept_rekey(member, newkey): at(member); return team.rekey_accept("acme", newkey)
    def fresh_join_and_accept(member, newkey):
        at(member); team.join_team(str(remote), newkey, member)
        team.privacy_accept("acme", fnkey_file); team.sync("acme", force=True)

    return {"remote": remote, "fnkey_file": fnkey_file, "key_v1": key_v1,
            "at": at, "sync": sync, "accept_privacy": accept_privacy,
            "hashed_filenames": hashed_filenames, "cache_has": cache_has,
            "rekey": rekey, "accept_rekey": accept_rekey,
            "fresh_join_and_accept": fresh_join_and_accept}


def test_mixed_state_reads_and_block(monkeypatch, tmp_path):
    env = _scenario(monkeypatch, tmp_path, use_fake=True)
    # (a) amy (hashed, has fnkey) reads L's + A's hashed pages AND B's plaintext
    env["sync"]("amy")
    assert env["cache_has"]("amy", "members/alice/wiki/concepts/auth.md")
    assert env["cache_has"]("amy", "members/amy/wiki/projects/x.md")
    assert env["cache_has"]("amy", "members/bob/wiki/notes/b.md")     # plaintext member
    # (b) bob (no fnkey) still reads hashed pages via the age-key manifest
    env["sync"]("bob")
    assert env["cache_has"]("bob", "members/alice/wiki/concepts/auth.md")
    assert env["cache_has"]("bob", "members/amy/wiki/projects/x.md")
    # (c) bob's NEW share is blocked (privacy pending — no fnkey)
    env["at"]("bob"); _put("notes/new.md", "New", "n")
    with pytest.raises(team.TeamError, match="privacy"):
        team.share("acme", "notes/new.md")


@needs_age
def test_zero_plaintext_path_in_head_after_convergence(monkeypatch, tmp_path):
    env = _scenario(monkeypatch, tmp_path, use_fake=False)     # real age
    remote = env["remote"]
    work = tmp_path / "audit"; subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    tree = subprocess.run(["git", "-C", str(work), "ls-tree", "-r", "--name-only", "HEAD"],
                          capture_output=True, text=True).stdout
    assert "concepts/auth.md" not in tree            # alice's real path never appears
    assert "projects/x.md" not in tree               # amy's either
    assert "notes/b.md.age" in tree                  # bob un-converged (EXPECTED)
    env["accept_privacy"]("bob")                     # converge
    subprocess.run(["git", "-C", str(work), "pull", "-q"], check=True)
    tree2 = subprocess.run(["git", "-C", str(work), "ls-tree", "-r", "--name-only", "HEAD"],
                           capture_output=True, text=True).stdout
    leaves = tree2.splitlines()
    assert leaves                                     # non-empty guard (never a vacuous pass)
    for real in ("concepts/auth.md", "notes/b.md", "projects/x.md"):
        assert real not in tree2                      # whole tree now zero-plaintext
    for line in leaves:
        leaf = Path(line).name
        # strict: <32hex>.age via filenames.is_hashed_age (rejects non-hex 36-char leaves)
        assert leaf == "team.json" or leaf == "manifest.age" or filenames.is_hashed_age(leaf)


@needs_age
def test_rekey_keeps_filenames_and_reencrypts_manifest(monkeypatch, tmp_path):
    env = _scenario(monkeypatch, tmp_path, use_fake=False)
    before = env["hashed_filenames"]("alice")
    newkey = env["rekey"]()                            # leader rekeys
    env["accept_rekey"]("amy", newkey)
    assert env["hashed_filenames"]("alice") == before  # fnkey fixed → names stable
    # a brand-new joiner with only the NEW age key resolves paths (manifest rotated)
    env["fresh_join_and_accept"]("carol", newkey)
    assert env["cache_has"]("carol", "members/alice/wiki/concepts/auth.md")
