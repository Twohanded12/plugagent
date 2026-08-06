import json
import pytest
from pathlib import Path
from pa import team


def _repo_with_meta(tmp_path, meta) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "team.json").write_text(json.dumps(meta), encoding="utf-8")
    return repo


def test_schema_1_plain_team_is_accepted(tmp_path):
    repo = _repo_with_meta(tmp_path, {"name": "t", "recipient": "age1x",
                                      "schema_version": 1})
    meta = team._read_committed_meta(repo)
    assert meta["privacy"] == "plain"


def test_schema_2_hashed_team_is_accepted(tmp_path):
    repo = _repo_with_meta(tmp_path, {"name": "t", "recipient": "age1x",
                                      "schema_version": 2, "privacy": "hashed"})
    meta = team._read_committed_meta(repo)
    assert meta["privacy"] == "hashed"


def test_future_schema_is_refused(tmp_path):
    repo = _repo_with_meta(tmp_path, {"name": "t", "recipient": "age1x",
                                      "schema_version": 3})
    with pytest.raises(team.TeamError):
        team._read_committed_meta(repo)


def test_missing_schema_version_refused_cleanly_not_typeerror(tmp_path):
    repo = _repo_with_meta(tmp_path, {"name": "t", "recipient": "age1x"})
    with pytest.raises(team.TeamError):
        team._read_committed_meta(repo)


from tests.team_helpers import fake_crypto


def test_manifest_write_then_read_round_trips(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    from pa import teamcrypto, filenames
    recipient, key = teamcrypto.keygen(tmp_path)           # gen 1
    man = tmp_path / "manifest.age"
    mapping = {"a" * 32: "concepts/auth.md"}
    team._write_manifest(man, recipient, mapping)
    assert filenames.is_hashed_age(man.name) is False      # it's manifest.age
    assert team._read_manifest(man, key, None) == mapping


def test_manifest_read_falls_back_to_prev_key(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    from pa import teamcrypto
    r1, k1 = teamcrypto.keygen(tmp_path / "g1")            # gen 1 (old)
    man = tmp_path / "manifest.age"
    team._write_manifest(man, r1, {"a" * 32: "x.md"})      # encrypted to gen 1
    r2, k2 = teamcrypto.keygen(tmp_path / "g2")            # gen 2 (new)
    assert team._read_manifest(man, k2, k1) == {"a" * 32: "x.md"}


def test_manifest_read_raises_when_undecryptable(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    from pa import teamcrypto
    teamcrypto.keygen(tmp_path / "g1")                     # consume gen 1
    _, k2 = teamcrypto.keygen(tmp_path / "g2")            # gen 2 (new)
    man = tmp_path / "manifest.age"
    man.write_bytes(b"FAKEAGE:v1:" + b'{"a":"x.md"}')      # gen-1 blob
    with pytest.raises(teamcrypto.DecryptError):
        team._read_manifest(man, k2, None)                 # no prev => can't open


def test_rekey_refuses_while_privacy_marker_present(team_env):
    name = team_env["name"]
    from pa import filenames, team
    filenames.privacy_marker(team.team_dir(name)).write_text("{}")
    with pytest.raises(team.TeamError, match="privacy"):
        team.rekey(name)


import subprocess
from tests.team_helpers import fake_crypto, make_remote


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)


def test_rebase_to_hashed_renames_and_builds_manifest(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    from pa import teamcrypto, filenames
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", repo], check=True)
    _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    ns = repo / "members" / "alice" / "wiki"
    ns.mkdir(parents=True)
    r1, k1 = teamcrypto.keygen(tmp_path / "g1")
    page = ns / "concepts" / "auth.md.age"
    page.parent.mkdir(parents=True)
    page.write_bytes(teamcrypto.encrypt(r1, b"# auth"))
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "seed")

    fnkey = b"\x11" * 32
    team._rebase_to_hashed(repo, "alice", fnkey, r1, k1, None)

    h = filenames.hmac_filename(fnkey, "concepts/auth.md")
    hashed = repo / "members" / "alice" / "wiki" / (h + ".age")
    assert hashed.exists()
    assert not page.exists()
    assert hashed.read_bytes() == teamcrypto.encrypt(r1, b"# auth")
    man = team._read_manifest(repo / "members" / "alice" / "manifest.age", k1, None)
    assert man == {h: "concepts/auth.md"}


def test_rebase_to_hashed_empty_namespace_is_noop(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    from pa import teamcrypto
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", repo], check=True)
    _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "members" / "bob").mkdir(parents=True)
    r1, k1 = teamcrypto.keygen(tmp_path / "g1")
    team._rebase_to_hashed(repo, "bob", b"\x11" * 32, r1, k1, None)
    man = repo / "members" / "bob" / "manifest.age"
    assert man.exists()
    assert team._read_manifest(man, k1, None) == {}


def test_rebase_to_hashed_is_idempotent_preserving_manifest(tmp_path, monkeypatch):
    fake_crypto(monkeypatch)
    from pa import teamcrypto, filenames
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", repo], check=True)
    _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    ns = repo / "members" / "alice" / "wiki"; ns.mkdir(parents=True)
    r1, k1 = teamcrypto.keygen(tmp_path / "g1")
    page = ns / "concepts" / "auth.md.age"; page.parent.mkdir(parents=True)
    page.write_bytes(teamcrypto.encrypt(r1, b"# auth"))
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "seed")
    fnkey = b"\x11" * 32
    m1 = team._rebase_to_hashed(repo, "alice", fnkey, r1, k1, None)
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "hashed")
    m2 = team._rebase_to_hashed(repo, "alice", fnkey, r1, k1, None)   # re-run, all hashed now
    assert m2 == m1 and m2 != {}


def test_privacy_on_turns_team_hashed(team_env):
    name = team_env["name"]
    from pa import filenames
    out = team.privacy_on(name)
    repo = team.repo_dir(name)
    meta = team._read_committed_meta(repo)
    assert meta["privacy"] == "hashed" and meta["schema_version"] == 2
    wiki = repo / "members" / "alice" / "wiki"
    assert not (wiki / "concepts" / "auth.md.age").exists()
    assert any(filenames.is_hashed_age(p.name) for p in wiki.iterdir())
    assert (repo / "members" / "alice" / "manifest.age").exists()
    assert filenames.fnkey_path(team.team_dir(name)).exists()
    assert "never" in out.lower()


def test_privacy_on_is_idempotent_noop_when_already_hashed(team_env):
    name = team_env["name"]
    team.privacy_on(name)
    out = team.privacy_on(name)
    assert "already" in out.lower()


def test_privacy_on_refused_if_rekey_marker_present(team_env):
    name = team_env["name"]
    team._rekey_marker(name).write_text("{}")
    with pytest.raises(team.TeamError, match="re-?key"):
        team.privacy_on(name)


def test_privacy_on_leak_guard_lets_only_age_and_teamjson(team_env):
    name = team_env["name"]
    team.privacy_on(name)
    from pa import teamgit
    assert teamgit.leak_violations(team.repo_dir(name)) == []


def test_privacy_on_resumes_after_push_failure_and_converges(team_env, monkeypatch):
    name = team_env["name"]
    from pa import teamgit, filenames
    real = teamgit.push_with_rebase
    n = {"c": 0}
    def flaky(repo):
        # let _pull_or_fail's push (call 1) through; blow up the commit-landing
        # push (call 2) — mirrors the established rekey flaky-push tests.
        n["c"] += 1
        if n["c"] == 2:
            raise teamgit.PushError("boom")
        return real(repo)
    monkeypatch.setattr(teamgit, "push_with_rebase", flaky)
    with pytest.raises(team.TeamError):
        team.privacy_on(name)
    assert filenames.privacy_marker(team.team_dir(name)).exists()
    out = team.privacy_on(name)
    assert not filenames.privacy_marker(team.team_dir(name)).exists()
    assert team._read_committed_meta(team.repo_dir(name))["privacy"] == "hashed"
    assert "never" in out.lower()


def test_privacy_on_resume_after_commit_emits_guidance(team_env):
    name = team_env["name"]
    team.privacy_on(name)
    team._privacy_marker(name).write_text("{}\n")
    out = team.privacy_on(name)
    assert "never" in out.lower() and "fnkey" in out.lower()
    assert not team._privacy_marker(name).exists()


def test_privacy_on_second_call_without_marker_is_terse_noop(team_env):
    name = team_env["name"]
    team.privacy_on(name)
    out = team.privacy_on(name)
    assert "already" in out.lower()


def test_privacy_accept_member_rebases_own_namespace(two_member_env):
    # current home is bob (fixture leaves it there); bob has a pre-privacy
    # plaintext page and no fnkey yet.
    env = two_member_env
    from pa import filenames
    out = team.privacy_accept("acme", env["fnkey_file"])   # bob accepts
    repo = team.repo_dir("acme")
    wiki = repo / "members" / "bob" / "wiki"
    assert any(filenames.is_hashed_age(p.name) for p in wiki.iterdir())
    assert not (wiki / "notes" / "b.md.age").exists()      # bob's page rebased
    assert (repo / "members" / "bob" / "manifest.age").exists()
    assert filenames.fnkey_path(team.team_dir("acme")).exists()


def test_privacy_accept_rejects_wrong_fnkey(two_member_env, tmp_path):
    env = two_member_env
    bad = tmp_path / "bad.fnkey"; bad.write_bytes(b"\x00" * 32)
    with pytest.raises(team.TeamError, match="fnkey"):
        team.privacy_accept("acme", bad)
    # no local change: bob still has no fnkey installed
    from pa import filenames
    assert not filenames.fnkey_path(team.team_dir("acme")).exists()


def test_privacy_accept_on_plain_team_refuses(team_env, tmp_path):
    name = team_env["name"]           # privacy NOT on
    f = tmp_path / "f"; f.write_bytes(b"\x11" * 32)
    with pytest.raises(team.TeamError, match="not.*enabled|enabled"):
        team.privacy_accept(name, f)


def test_privacy_accept_empty_manifest_installs_with_warning(env_privacy_on_no_pages, tmp_path):
    # leader turned privacy on with ZERO shared pages → every manifest empty →
    # nothing to trial-HMAC → install + warn.
    env = env_privacy_on_no_pages
    out = team.privacy_accept("acme", env["fnkey_file"])
    assert "couldn't verify" in out.lower() or "warn" in out.lower()
    from pa import filenames
    assert filenames.fnkey_path(team.team_dir("acme")).exists()


from tests.conftest import write_wiki_page      # helper (writes to the current home's vault)


def test_share_on_hashed_team_writes_hashed_name_and_updates_manifest(team_env):
    name = team_env["name"]
    team.privacy_on(name)
    write_wiki_page("projects/x.md", "X", "x")   # NEW page in alice's vault
    team.share(name, "projects/x.md")
    from pa import filenames
    fnkey = filenames.fnkey_path(team.team_dir(name)).read_bytes()
    h = filenames.hmac_filename(fnkey, "projects/x.md")
    repo = team.repo_dir(name)
    assert (repo / "members" / "alice" / "wiki" / (h + ".age")).exists()
    man = team._read_manifest(repo / "members" / "alice" / "manifest.age",
                              team.key_path(name), None)
    assert man[h] == "projects/x.md"


def test_share_without_fnkey_on_hashed_team_is_blocked(two_member_env):
    # current home is bob: on a hashed team, no fnkey (never accepted)
    write_wiki_page("notes/new.md", "New", "n")   # bob authors a new page
    with pytest.raises(team.TeamError, match="privacy"):
        team.share("acme", "notes/new.md")        # blocked at the fnkey check


def test_share_refuses_manifest_hash_collision(team_env, monkeypatch):
    name = team_env["name"]
    team.privacy_on(name)
    # force two different rels to the same h → refuse the second
    monkeypatch.setattr("pa.filenames.hmac_filename", lambda k, r: "c" * 32)
    write_wiki_page("a.md", "A", "a"); team.share(name, "a.md")
    write_wiki_page("b.md", "B", "b")
    with pytest.raises(team.TeamError, match="collision|already"):
        team.share(name, "b.md")


def test_plain_team_share_is_unchanged(team_env):
    name = team_env["name"]           # privacy OFF
    write_wiki_page("notes/y.md", "Y", "y")
    team.share(name, "notes/y.md")
    repo = team.repo_dir(name)
    assert (repo / "members" / "alice" / "wiki" / "notes" / "y.md.age").exists()


def test_sync_places_hashed_pages_under_real_paths(two_member_env):
    env = two_member_env            # alice hashed w/ a page; bob reads
    team.sync("acme", force=True)   # bob syncs
    cache = team.cache_dir("acme")
    assert (cache / "members" / "alice" / "wiki" / "concepts" / "auth.md").exists()
    # manifest.age is NOT written into the cache as a page
    assert not list(cache.rglob("manifest"))
    assert not list(cache.rglob("manifest.age"))


def test_orphan_sweep_keeps_freshly_synced_hashed_page(two_member_env):
    # regression for the _remove_cache_orphans <rel>.age reverse-map bug:
    # a just-synced hashed page must survive the sweep in the SAME sync.
    team.sync("acme", force=True)
    cache = team.cache_dir("acme")
    assert (cache / "members" / "alice" / "wiki" / "concepts" / "auth.md").exists()
    team.sync("acme", force=True)   # second sync must not delete it
    assert (cache / "members" / "alice" / "wiki" / "concepts" / "auth.md").exists()


def _commit_push_alice(env, repo, msg):
    """Stage everything in alice's repo, commit, push to the shared remote."""
    import subprocess
    from pa import teamgit
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", msg],
                   check=True, capture_output=True)
    teamgit.push_with_rebase(repo)


def test_orphan_sweep_removes_page_dropped_from_manifest(two_member_env):
    env = two_member_env
    from pa import filenames
    cache = team.cache_dir("acme")
    team.sync("acme", force=True)                      # bob caches alice's page
    assert (cache / "members" / "alice" / "wiki" / "concepts" / "auth.md").exists()
    # alice drops the page: remove <h>.age and rewrite an empty manifest, push
    env["as_leader"]()
    repo = team.repo_dir("acme")
    meta = team._read_committed_meta(repo)
    fnkey = filenames.fnkey_path(team.team_dir("acme")).read_bytes()
    h = filenames.hmac_filename(fnkey, "concepts/auth.md")
    (repo / "members" / "alice" / "wiki" / (h + ".age")).unlink()
    team._write_manifest(repo / "members" / "alice" / "manifest.age", meta["recipient"], {})
    _commit_push_alice(env, repo, "drop auth")
    env["as_bob"]()
    team.sync("acme", force=True)
    assert not (cache / "members" / "alice" / "wiki" / "concepts" / "auth.md").exists()


def test_reader_without_fnkey_still_reads_hashed_pages(two_member_env):
    # bob has NO fnkey but reads alice's hashed pages via the age-key manifest
    from pa import filenames
    assert not filenames.fnkey_path(team.team_dir("acme")).exists()  # bob, pre-accept
    team.sync("acme", force=True)
    assert (team.cache_dir("acme") / "members" / "alice" / "wiki" / "concepts" / "auth.md").exists()


def test_sync_skips_member_with_undecryptable_manifest(two_member_env):
    # CRIT #2 regression: a transiently-undecryptable manifest must NOT wipe the
    # last-good cache (skip-don't-poison), and sync must still succeed.
    env = two_member_env
    cache = team.cache_dir("acme")
    team.sync("acme", force=True)                      # bob caches alice's page
    good = cache / "members" / "alice" / "wiki" / "concepts" / "auth.md"
    assert good.exists()
    # corrupt alice's manifest in the remote (a blob no key here can open)
    env["as_leader"]()
    repo = team.repo_dir("acme")
    (repo / "members" / "alice" / "manifest.age").write_bytes(b"FAKEAGE:v9:garbage")
    _commit_push_alice(env, repo, "corrupt manifest")
    env["as_bob"]()
    out = team.sync("acme", force=True)               # must not raise
    assert good.exists()                               # last-good cache preserved
    assert "fail" in out.lower() or "failed" in out.lower()   # failure counted, not fatal


def test_status_shows_privacy_hashed_and_pending(two_member_env):
    env = two_member_env
    out_bob = team.status_report()            # current home is bob (no fnkey)
    assert "privacy: hashed" in out_bob and "privacy pending" in out_bob
    env["as_leader"]()                         # switch to alice (has fnkey)
    out_alice = team.status_report()
    assert "privacy: hashed" in out_alice and "privacy pending" not in out_alice


def test_cli_routes_privacy_on_and_accept(monkeypatch):
    from pa import __main__ as m
    calls = {}
    monkeypatch.setattr("pa.team.privacy_on", lambda name: calls.setdefault("on", name) or "ok")
    monkeypatch.setattr("pa.team.resolve_team", lambda n: "acme")
    assert m.main(["team", "privacy", "on"]) == 0
    assert calls["on"] == "acme"
    monkeypatch.setattr("pa.team.privacy_accept", lambda name, f: calls.setdefault("acc", (name, str(f))) or "ok")
    assert m.main(["team", "privacy-accept", "--fnkey", "/tmp/f"]) == 0
    assert calls["acc"][0] == "acme"
