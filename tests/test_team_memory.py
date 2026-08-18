import json
import subprocess

import pytest

from pathlib import Path

from pa import team, memory
from tests.team_helpers import fake_crypto, make_remote
from tests.conftest import write_wiki_page


def _seed_team_card(name, member, card, desc="d", body="b"):
    """Write a decrypted team card straight into the team cache."""
    p = team.cache_dir(name) / "members" / member / "memory" / f"{card}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {card}\ndescription: {desc}\ntype: feedback\n---\n\n{body}\n",
                 encoding="utf-8")
    return p


def test_cards_for_index_reads_the_memory_root(team_env):
    path = _seed_team_card("acme", "alice", "pytest-only", desc="Use pytest")
    cards = team.cards_for_index()
    # `path` is carried from the start so Task 12's body lookup is exact rather
    # than reconstructed from the frontmatter `name` (which may differ from the
    # filename). Adding it later would break this assertion.
    assert {"name": "pytest-only", "description": "Use pytest", "member": "alice",
            "team": "acme", "path": str(path)} in cards


def test_every_card_carries_the_full_provider_contract(team_env):
    # The T3 review's contract: rebuild_index tolerates a malformed entry, but
    # the provider must still emit all five keys on EVERY card — including one
    # whose frontmatter omits name/description entirely.
    _seed_team_card("acme", "alice", "complete", desc="Use pytest")
    bare = team.cache_dir("acme") / "members" / "alice" / "memory" / "bare.md"
    bare.write_text("no frontmatter at all\n", encoding="utf-8")
    cards = team.cards_for_index()
    assert len(cards) == 2
    for c in cards:
        assert set(c) == {"name", "description", "member", "team", "path"}


def test_cards_for_index_ignores_the_wiki_root(team_env):
    p = team.cache_dir("acme") / "members" / "alice" / "wiki" / "page.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nname: page\ndescription: a page\n---\n\nbody\n", encoding="utf-8")
    assert team.cards_for_index() == []


def test_cards_for_index_honors_team_memory_off(team_env):
    _seed_team_card("acme", "alice", "c")
    cfg = team.load_local("acme"); cfg["team_memory"] = False
    team.save_local("acme", cfg)
    assert team.cards_for_index() == []


def test_cards_for_index_skips_an_unparseable_card(team_env):
    _seed_team_card("acme", "alice", "good", desc="ok")
    bad = team.cache_dir("acme") / "members" / "alice" / "memory" / "bad.md"
    bad.write_bytes(b"\xff\xfe not utf-8 at all")
    names = [c["name"] for c in team.cards_for_index()]
    assert names == ["good"]


def test_cards_for_index_with_no_cache_is_empty(team_env):
    assert team.cards_for_index() == []


def test_a_crafted_body_cannot_inject_frontmatter(team_env):
    # build_promotion's framing is only safe because the RECEIVER's parse is
    # anchored at offset 0 and non-greedy, so the FIRST "\n---\n" closes the
    # block. Pin that here, at the parser that enforces it: a swap to a greedy
    # pattern or an unanchored re.search would break it.
    #
    # The crafted block RE-DECLARES `description` on purpose. Injecting keys the
    # provider never reads (uses/author) proves nothing — the returned dict is a
    # fixed five-key literal, so those can never leak in whatever the regex does.
    # Only a field the provider DOES read can be hijacked, and under a greedy
    # pattern the second block's line wins.
    p = team.cache_dir("acme") / "members" / "alice" / "memory" / "evil.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nname: evil\ndescription: real\ntype: feedback\n---\n\n"
                 "---\ndescription: hijacked\nuses: 999\nauthor: mallory\n---\n\nbody\n",
                 encoding="utf-8")
    # A body-only fake block, with NO real frontmatter, pins the anchoring: an
    # unanchored search would promote it to this card's metadata.
    q = team.cache_dir("acme") / "members" / "alice" / "memory" / "sneaky.md"
    q.write_text("just a body\n\n---\nname: injected\ndescription: hijacked\n---\n",
                 encoding="utf-8")
    cards = team.cards_for_index()
    card = [c for c in cards if c["name"] == "evil"][0]
    assert card["description"] == "real"          # not "" and not overridden
    assert "uses" not in card and "author" not in card
    sneaky = [c for c in cards if c["path"] == str(q)][0]
    assert sneaky == {"name": "sneaky", "description": "", "member": "alice",
                      "team": "acme", "path": str(q)}


def test_path_is_the_real_source_not_reconstructed_from_the_name(team_env):
    # `name` is sender-controlled content decrypted out of a teammate's blob, and
    # Task 12 dereferences `path` to read the body. If `path` were rebuilt as
    # "<dir>/<name>.md", a crafted `name:` would steer that read. Pin it with a
    # card whose frontmatter name differs from its filename.
    p = team.cache_dir("acme") / "members" / "alice" / "memory" / "on-disk-name.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nname: renamed-card\ndescription: d\ntype: feedback\n---\n\nbody\n",
                 encoding="utf-8")
    card = [c for c in team.cards_for_index() if c["name"] == "renamed-card"][0]
    assert card["path"] == str(p)          # the real file, not <dir>/renamed-card.md


def test_cards_for_index_with_no_cache_at_all_is_empty(team_env):
    # team_env's share already created cache/members/alice/wiki/, so the
    # members_root guard is only reached once the cache is really gone.
    import shutil as _sh
    _sh.rmtree(team.cache_dir("acme"))
    assert team.cards_for_index() == []


def test_a_corrupt_team_config_does_not_break_other_teams(team_env):
    # cards_for_index runs on EVERY `pa memory add`, so one unreadable team must
    # not take the personal index down with it.
    _seed_team_card("acme", "alice", "good", desc="ok")
    broken = team.team_dir("broken")
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "team.json").write_text("{ not json", encoding="utf-8")
    assert [c["name"] for c in team.cards_for_index()] == ["good"]


def _seed_memory_blob(name, member, card, body=b"card body"):
    """Seed an ENCRYPTED card blob straight into members/<m>/memory/ and commit.

    share_card does not exist until Task 9, so Task 5's rebase/validate tests
    seed the blob directly (the pattern tests/test_team_reencrypt.py already
    uses). That keeps this task self-contained and still exercises
    _rebase_to_hashed / _validate_fnkey."""
    from pa import teamcrypto
    repo = team.repo_dir(name)
    meta = team._read_committed_meta(repo)
    dest = repo / "members" / member / "memory" / f"{card}.md.age"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(teamcrypto.encrypt(meta["recipient"], body))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", f"seed {card}"],
                   check=True, capture_output=True)
    return dest


def test_privacy_on_rebases_the_memory_root(team_env):
    from pa import filenames
    _seed_memory_blob("acme", "alice", "lint")
    team.privacy_on("acme")
    mem = team.repo_dir("acme") / "members" / "alice" / "memory"
    assert list(mem.glob("*.age"))                      # the card is still there
    assert all(filenames.is_hashed_age(p.name) for p in mem.glob("*.age"))


def test_rebase_uses_the_memory_hash_input(team_env):
    # round-3 (viii), rebase half: the name _rebase_to_hashed produces must be
    # hash_input("memory", rel) — NOT a bare rel (the "third form" drift).
    from pa import filenames
    _seed_memory_blob("acme", "alice", "lint")
    team.privacy_on("acme")
    fnkey = filenames.fnkey_path(team.team_dir("acme")).read_bytes()
    h = filenames.hmac_filename(fnkey, filenames.hash_input("memory", "lint.md"))
    repo = team.repo_dir("acme")
    assert (repo / "members" / "alice" / "memory" / (h + ".age")).exists()
    mapping = team._read_manifest(repo / "members" / "alice" / "manifest.age",
                                  team.key_path("acme"), None)
    assert mapping[h] == "lint.md"          # value stays root-relative


def test_validate_fnkey_accepts_a_memory_only_manifest(team_env):
    # _validate_fnkey returns "ok" on the FIRST match, so a wiki entry would mask
    # a broken memory form. Use a team whose manifest has ONLY a memory entry.
    from pa import filenames
    _seed_memory_blob("acme", "alice", "lint")
    repo = team.repo_dir("acme")
    # drop the wiki page team_env shared, so only the card remains
    for p in (repo / "members" / "alice" / "wiki").rglob("*.age"):
        p.unlink()
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "wiki gone"],
                   check=True, capture_output=True)
    team.privacy_on("acme")
    fnkey = filenames.fnkey_path(team.team_dir("acme")).read_bytes()
    assert team._validate_fnkey(repo, fnkey, team.key_path("acme"), None) == "ok"


def test_domain_separation_survives_privacy_on(team_env):
    # round-2 (i): a wiki page at wiki/memory/notes.md and a card named notes
    # must NOT collide. team_env already shared concepts/auth.md, so THREE
    # entries must survive.
    write_wiki_page("memory/notes.md", "A wiki page", "wiki body")
    team.share("acme", "memory/notes.md")
    _seed_memory_blob("acme", "alice", "notes")
    team.privacy_on("acme")
    repo = team.repo_dir("acme")
    mapping = team._read_manifest(repo / "members" / "alice" / "manifest.age",
                                  team.key_path("acme"), None)
    assert sorted(mapping.values()) == ["concepts/auth.md", "memory/notes.md", "notes.md"]
    assert len(mapping) == 3          # three distinct hashes — no silent overwrite


def test_sync_places_a_memory_card_under_the_memory_root(two_member_memory_env):
    team.sync("acme", force=True)                # bob
    cache = team.cache_dir("acme")
    assert (cache / "members" / "alice" / "memory" / "lint.md").exists()
    assert (cache / "members" / "alice" / "wiki" / "concepts" / "auth.md").exists()


def test_manifest_age_never_becomes_a_counted_failure(two_member_memory_env):
    # round-2 (iv). join_team already synced, so force a FULL re-enumeration —
    # otherwise changed+retry is empty, the loop never runs, and this passes
    # even with the root check wrongly ordered before the manifest.age skip.
    # The fixture is a HASHED team, so members/alice/manifest.age really exists
    # and changed_age_files WILL yield it (on a plain team there is none, and the
    # assertion would be trivially true).
    cfg = team.load_local("acme"); cfg["last_synced_commit"] = None
    team.save_local("acme", cfg)
    team.sync("acme", force=True)
    assert not any(f.endswith("manifest.age")
                   for f in team.load_local("acme")["decrypt_failures"])


def test_a_repo_root_stray_age_is_skipped_not_a_crash(team_env):
    # round-2 (v): len(parts) > 2 guard.
    repo = team.repo_dir("acme")
    (repo / "stray.age").write_bytes(b"whatever")
    subprocess.run(["git", "-C", str(repo), "add", "stray.age"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "stray"],
                   check=True, capture_output=True)
    out = team.sync("acme", force=True)          # must not raise IndexError
    assert "synced" in out


def test_an_unknown_root_is_skipped(team_env):
    # The blob must be VALIDLY ENCRYPTED — an undecryptable one lands in failures
    # anyway, so the root guard would not be what prevented the cache write.
    from pa import teamcrypto
    repo = team.repo_dir("acme")
    meta = team._read_committed_meta(repo)
    odd = repo / "members" / "alice" / "notes" / "x.age"
    odd.parent.mkdir(parents=True, exist_ok=True)
    odd.write_bytes(teamcrypto.encrypt(meta["recipient"], b"readable"))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "odd"],
                   check=True, capture_output=True)
    team.sync("acme", force=True)
    assert not (team.cache_dir("acme") / "members" / "alice" / "notes").exists()


def test_a_traversal_manifest_value_is_rejected(team_env):
    from pa import teamcrypto
    team.privacy_on("acme")
    repo, cache = team.repo_dir("acme"), team.cache_dir("acme")
    meta = team._read_committed_meta(repo)
    man = repo / "members" / "alice" / "manifest.age"
    # T6 carry-over: KEEP the fixture's legitimate entry instead of clobbering
    # the manifest. A clobbered manifest makes every cache entry an orphan, so
    # the sweep deleted a leaked escape.md as a side effect and the first
    # assertion below could never fail — it was load-free. With a live entry
    # present the sweep has real work to preserve, so a leak SURVIVES and the
    # rejection is asserted at the point of the join.
    mapping = team._read_manifest(man, team.key_path("acme"), None)
    assert "concepts/auth.md" in mapping.values()      # fixture page, stays live
    mapping["a" * 32] = "../../escape.md"
    team._write_manifest(man, meta["recipient"], mapping)
    (repo / "members" / "alice" / "wiki" / ("a" * 32 + ".age")).write_bytes(
        teamcrypto.encrypt(meta["recipient"], b"x"))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "evil"],
                   check=True, capture_output=True)
    team.sync("acme", force=True)
    # The sweep ran and had something to keep — so it is NOT what removes the
    # escape below.
    assert (cache / "members" / "alice" / "wiki" / "concepts" / "auth.md").exists()
    # dest would be cache/members/alice/wiki/../../escape.md == cache/members/escape.md
    assert not (cache / "members" / "escape.md").exists()
    assert any("a" * 32 in f for f in team.load_local("acme")["decrypt_failures"])


def _poison_manifest(name, member, value):
    """Point a hashed member's manifest at `value` and commit a matching blob."""
    from pa import teamcrypto
    repo = team.repo_dir(name)
    meta = team._read_committed_meta(repo)
    h = "a" * 32
    team._write_manifest(repo / "members" / member / "manifest.age", meta["recipient"],
                         {h: value})
    (repo / "members" / member / "wiki" / (h + ".age")).write_bytes(
        teamcrypto.encrypt(meta["recipient"], b"payload"))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "poison"],
                   check=True, capture_output=True)
    return h


def test_an_absolute_manifest_value_is_rejected(team_env, tmp_path):
    # Pre-Phase-5 this wrote decrypted content to an arbitrary ABSOLUTE path
    # outside the cache — a real arbitrary-file-write from a teammate.
    team.privacy_on("acme")
    escape = tmp_path / "pwned.md"
    h = _poison_manifest("acme", "alice", str(escape))
    team.sync("acme", force=True)
    assert not escape.exists()
    assert any(h in f for f in team.load_local("acme")["decrypt_failures"])


def test_a_nul_manifest_value_is_rejected(team_env):
    # Pre-Phase-5 this crashed sync with ValueError: embedded null byte.
    team.privacy_on("acme")
    h = _poison_manifest("acme", "alice", "memory\x00notes.md")
    team.sync("acme", force=True)          # must not raise
    assert any(h in f for f in team.load_local("acme")["decrypt_failures"])


def test_an_empty_manifest_value_is_rejected(team_env):
    # "" and "." collapse the join to the member root, and write_bytes then
    # raises IsADirectoryError — one bad entry would permanently crash sync for
    # every member, since sync() is contractually soft-failing.
    team.privacy_on("acme")
    h = _poison_manifest("acme", "alice", "")
    out = team.sync("acme", force=True)    # must not raise
    assert "synced" in out
    assert any(h in f for f in team.load_local("acme")["decrypt_failures"])


# --- Task 7: live-set from a FULL enumeration + manifest-aware orphan sweep ---


def test_second_sync_with_no_changes_deletes_nothing(two_member_memory_env):
    # round-3 (vi): proves the live-set comes from a FULL repo enumeration.
    team.sync("acme", force=True)
    before = sorted(p.name for p in team.cache_dir("acme").rglob("*.md"))
    # NOT decoration: join_team already left bob's cursor at HEAD, so the FIRST
    # sync above has an empty changed+retry too. A live-set built from that loop
    # empties the cache right here, `before` becomes just ["index.md"], and the
    # equality below then holds empty-vs-empty — the very defect this test
    # exists to catch would pass. Pin the snapshot's contents so it cannot.
    assert "lint.md" in before and "auth.md" in before
    team.sync("acme", force=True)
    assert sorted(p.name for p in team.cache_dir("acme").rglob("*.md")) == before


def test_undecryptable_manifest_keeps_the_whole_namespace(two_member_memory_env):
    # round-3 (vii): Phase 4 skip-don't-poison survives the live-set change.
    team.sync("acme", force=True)
    cached = team.cache_dir("acme") / "members" / "alice" / "memory" / "lint.md"
    assert cached.exists()
    repo = team.repo_dir("acme")
    (repo / "members" / "alice" / "manifest.age").write_bytes(b"FAKEAGE:v9:garbage")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "corrupt"],
                   check=True, capture_output=True)
    team.sync("acme", force=True)
    assert cached.exists()                       # last-good kept, never swept


def test_sweep_removes_a_card_whose_blob_is_gone(two_member_memory_env):
    # The sweep half of round-2 (iii), testable without unshare_card. On a HASHED
    # team no wiki-copy trick is needed: deleting the blob while leaving the
    # manifest entry STALE is the stronger trap. The old sweep resolves liveness
    # from manifest VALUES (stale entry present -> kept); the new one from a full
    # BLOB enumeration (blob gone -> swept).
    from pa import filenames
    env = two_member_memory_env
    team.sync("acme", force=True)
    cached = team.cache_dir("acme") / "members" / "alice" / "memory" / "lint.md"
    assert cached.exists()
    env["as_leader"]()
    repo = team.repo_dir("acme")
    fnkey = filenames.fnkey_path(team.team_dir("acme")).read_bytes()
    h = filenames.hmac_filename(fnkey, filenames.hash_input("memory", "lint.md"))
    (repo / "members" / "alice" / "memory" / (h + ".age")).unlink()   # manifest left STALE
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "drop card blob"],
                   check=True, capture_output=True)
    from pa import teamgit as _tg; _tg.push_with_rebase(repo)
    env["as_bob"]()
    team.sync("acme", force=True)
    assert not cached.exists()          # value-based liveness would have kept it


# --- Task 8: the memory root is invisible to wiki-only consumers ---


def test_team_wiki_index_excludes_memory_cards(team_env):
    _seed_team_card("acme", "alice", "lint")
    team._rebuild_index("acme")
    index = (team.cache_dir("acme") / "index.md").read_text(encoding="utf-8")
    assert "lint" not in index          # else skills/recall cites it, bypassing the off switch
    # keep-side anchor: an over-broad guard (e.g. skipping every members/ path)
    # would satisfy the absence assertion alone.
    assert "wiki/concepts/auth.md" in index


def test_status_cached_pages_excludes_memory_cards(team_env):
    # team_env's share already cached one wiki page, so the wiki-only count is 1.
    # Asserting 1 (not 0) proves the card was excluded WITHOUT zeroing the page count.
    _seed_team_card("acme", "alice", "lint")
    team._rebuild_index("acme")
    assert "cached pages: 1" in team.status_report()


def test_status_reports_shared_and_received_card_counts(team_env):
    _seed_team_card("acme", "bob", "theirs")            # received
    repo = team.repo_dir("acme")                        # shared (own namespace)
    own = repo / "members" / "alice" / "memory" / "mine.md.age"
    own.parent.mkdir(parents=True, exist_ok=True); own.write_bytes(b"x")
    assert "team cards: 1 shared / 1 received" in team.status_report()


def test_status_shows_the_off_switch(team_env):
    # set_team_memory lands in Task 11, so set the local flag directly here.
    cfg = team.load_local("acme"); cfg["team_memory"] = False
    team.save_local("acme", cfg)
    assert "team memory off" in team.status_report()


# --- Task 9: share_card — promotion, idempotence, consent-gated schema bump ---


def test_share_card_writes_the_blob_and_keeps_the_original(team_env):
    memory.add("lint", "Run the linter", "feedback", "body")
    before = memory._card_path("lint").read_bytes()
    team.share_card("acme", "lint", confirm_schema_bump=True)
    repo = team.repo_dir("acme")
    assert (repo / "members" / "alice" / "memory" / "lint.md.age").exists()
    assert memory._card_path("lint").read_bytes() == before      # invariant 1


def test_share_card_strips_statistics_in_the_committed_blob(team_env):
    from pa import teamcrypto
    memory.add("lint", "Run the linter", "feedback", "body")
    memory.set_stats("lint", uses=9, last_used="2026-01-02")
    team.share_card("acme", "lint", confirm_schema_bump=True)
    blob = (team.repo_dir("acme") / "members" / "alice" / "memory" / "lint.md.age").read_bytes()
    plain = teamcrypto.decrypt(team.key_path("acme"), blob).decode("utf-8")
    assert "uses" not in plain and "last_used" not in plain and "created" not in plain      # invariant 2


def test_first_promotion_requires_consent(team_env):
    memory.add("lint", "d", "feedback", "b")
    with pytest.raises(team.TeamError, match="schema"):
        team.share_card("acme", "lint")                          # no confirm flag
    repo = team.repo_dir("acme")
    assert team._read_committed_meta(repo)["schema_version"] < 3  # team.json untouched


def test_refused_promotion_leaves_no_side_effects_and_retry_works(team_env):
    # The gate MUST run before any write. Otherwise the refused call leaves the
    # blob on disk, the retry's idempotence check says "already up to date", and
    # the card never ships — the first promotion on every team would be stuck.
    memory.add("lint", "d", "feedback", "b")
    repo = team.repo_dir("acme")
    with pytest.raises(team.TeamError):
        team.share_card("acme", "lint")
    assert not (repo / "members" / "alice" / "memory").exists()   # no blob written
    assert not team._is_dirty(repo)                               # no dirty tree
    out = team.share_card("acme", "lint", confirm_schema_bump=True)
    assert out.startswith("promoted card")   # not the push-failed variant
    assert (repo / "members" / "alice" / "memory" / "lint.md.age").exists()
    assert team._read_committed_meta(repo)["schema_version"] == 3


def test_second_promotion_needs_no_consent_and_leaves_team_json_alone(team_env):
    memory.add("a", "d", "feedback", "b")
    memory.add("b2", "d", "feedback", "b")
    team.share_card("acme", "a", confirm_schema_bump=True)
    repo = team.repo_dir("acme")
    before = (repo / "team.json").read_bytes()
    team.share_card("acme", "b2")                                # no flag needed
    assert (repo / "team.json").read_bytes() == before


def test_share_card_is_idempotent_via_decrypt_compare(team_env, monkeypatch):
    # round-2 (viii): the fake encrypt is DETERMINISTIC, so a byte/git comparison
    # would pass vacuously. Make the ciphertext differ per call — and wrap the
    # ORIGINAL decrypt so the plaintext still round-trips — so that ONLY a
    # decrypt-compare can detect "unchanged".
    import re as _re
    from pa import teamcrypto
    real_encrypt = teamcrypto.encrypt
    real_decrypt = teamcrypto.decrypt          # capture BEFORE patching
    n = {"i": 0}

    def nondeterministic(recipient, data):
        n["i"] += 1
        return real_encrypt(recipient, data) + f"#{n['i']}".encode()

    def tolerant(identity, blob):
        return real_decrypt(identity, _re.sub(rb"#\d+\Z", b"", blob))

    monkeypatch.setattr(teamcrypto, "encrypt", nondeterministic)
    monkeypatch.setattr(teamcrypto, "decrypt", tolerant)
    # pin the premise: two encryptions of the same plaintext differ byte-wise,
    # so a byte/git comparison could not be what short-circuits below.
    assert nondeterministic("age1fake-v1", b"x") != nondeterministic("age1fake-v1", b"x")
    memory.add("lint", "d", "feedback", "b")
    team.share_card("acme", "lint", confirm_schema_bump=True)
    dest = team.repo_dir("acme") / "members" / "alice" / "memory" / "lint.md.age"
    first = dest.read_bytes()
    out = team.share_card("acme", "lint")
    assert "already up to date" in out
    assert dest.read_bytes() == first      # short-circuited BEFORE any write


def test_share_card_refuses_a_missing_card(team_env):
    with pytest.raises(team.TeamError, match="no such card|nearby"):
        team.share_card("acme", "nope", confirm_schema_bump=True)


def test_share_card_blocked_without_fnkey_on_a_hashed_team(two_member_env):
    memory.add("x", "d", "feedback", "b")
    with pytest.raises(team.TeamError, match="privacy"):
        team.share_card("acme", "x", confirm_schema_bump=True)    # bob has no fnkey


def test_schema_monotonicity_privacy_on_does_not_downgrade(team_env):
    # round-2 (ii)
    memory.add("lint", "d", "feedback", "b")
    team.share_card("acme", "lint", confirm_schema_bump=True)
    team.privacy_on("acme")
    assert team._read_committed_meta(team.repo_dir("acme"))["schema_version"] == 3


def test_share_card_and_rebase_produce_the_same_hash(team_env):
    # round-3 (viii), the OTHER half (Task 5 covered rebase alone): promote on a
    # PLAIN team, then privacy_on rebases it. If share_card and _rebase_to_hashed
    # disagreed on the hash input, the rebased name would differ from what a
    # later share_card writes and receivers could not resolve it.
    from pa import filenames
    memory.add("lint", "d", "feedback", "b")
    team.share_card("acme", "lint", confirm_schema_bump=True)   # plain: lint.md.age
    team.privacy_on("acme")                                      # rebases to <h>.age
    fnkey = filenames.fnkey_path(team.team_dir("acme")).read_bytes()
    h = filenames.hmac_filename(fnkey, filenames.hash_input("memory", "lint.md"))
    repo = team.repo_dir("acme")
    assert (repo / "members" / "alice" / "memory" / (h + ".age")).exists()
    # and a fresh share_card on the now-hashed team writes THAT same name
    memory.add("lint", "d2", "feedback", "b2")
    team.share_card("acme", "lint")
    assert (repo / "members" / "alice" / "memory" / (h + ".age")).exists()
    assert len(list((repo / "members" / "alice" / "memory").glob("*.age"))) == 1


# --- Task 10: unshare_card — withdrawal without an fnkey ---


def test_unshare_card_removes_blob_and_manifest_entry(team_env):
    memory.add("lint", "d", "feedback", "b")
    team.privacy_on("acme")
    team.share_card("acme", "lint", confirm_schema_bump=True)
    team.unshare_card("acme", "lint")
    repo = team.repo_dir("acme")
    assert not list((repo / "members" / "alice" / "memory").glob("*.age"))
    mapping = team._read_manifest(repo / "members" / "alice" / "manifest.age",
                                  team.key_path("acme"), None)
    assert "lint.md" not in mapping.values()


def test_unshare_card_works_without_an_fnkey(team_env):
    # A member who never accepted privacy must still be able to withdraw.
    from pa import filenames
    memory.add("lint", "d", "feedback", "b")
    team.privacy_on("acme")
    team.share_card("acme", "lint", confirm_schema_bump=True)
    filenames.fnkey_path(team.team_dir("acme")).unlink()        # drop the fnkey
    out = team.unshare_card("acme", "lint")
    assert out.startswith("withdrew card")        # not the push-failed variant
    # the point is the WITHDRAWAL, not the message
    assert not list((team.repo_dir("acme") / "members" / "alice" / "memory").glob("*.age"))


def test_unshare_card_on_a_card_that_was_never_shared(team_env):
    with pytest.raises(team.TeamError, match="not shared"):
        team.unshare_card("acme", "ghost")


def test_cross_root_alias_does_not_keep_a_withdrawn_card(two_member_memory_env):
    # round-2 (iii) in full: alice has BOTH a wiki page lint.md and a card lint,
    # which share the root-relative value "lint.md". A root-blind sweep would see
    # "lint.md" still in the manifest via the wiki page and keep bob's cached
    # card forever, so it would keep folding into his hot index.
    env = two_member_memory_env
    env["as_leader"]()
    write_wiki_page("lint.md", "A wiki page", "wiki body")
    team.share("acme", "lint.md")
    env["as_bob"](); team.sync("acme", force=True)
    cached = team.cache_dir("acme") / "members" / "alice" / "memory" / "lint.md"
    assert cached.exists()
    env["as_leader"]()
    team.unshare_card("acme", "lint")
    env["as_bob"](); team.sync("acme", force=True)
    assert not cached.exists()                                   # the card is gone
    assert (team.cache_dir("acme") / "members" / "alice" / "wiki" / "lint.md").exists()


def test_unshare_card_on_a_plain_team(team_env):
    # All the other removal tests run on hashed teams; the plain branch (no
    # manifest involved) would otherwise regress green.
    memory.add("lint", "d", "feedback", "b")
    team.share_card("acme", "lint", confirm_schema_bump=True)
    repo = team.repo_dir("acme")
    assert (repo / "members" / "alice" / "memory" / "lint.md.age").exists()
    out = team.unshare_card("acme", "lint")
    assert out.startswith("withdrew card")
    assert not (repo / "members" / "alice" / "memory" / "lint.md.age").exists()
    assert not (repo / "members" / "alice" / "manifest.age").exists()   # never created


# --- Task 11: the local-only off switch + CLI dispatch for the card commands ---


def test_team_memory_toggle_is_local_only(team_env):
    team.set_team_memory("acme", False)
    assert team.load_local("acme")["team_memory"] is False
    repo = team.repo_dir("acme")
    assert "team_memory" not in (repo / "team.json").read_text(encoding="utf-8")


def test_cli_routes_the_three_new_commands(monkeypatch):
    from pa import __main__ as m
    calls = {}
    monkeypatch.setattr("pa.team.resolve_team", lambda n: "acme")
    monkeypatch.setattr("pa.team.share_card",
                        lambda name, card, confirm_schema_bump=False:
                        calls.setdefault("share", (name, card, confirm_schema_bump)) or "ok")
    monkeypatch.setattr("pa.team.unshare_card",
                        lambda name, card: calls.setdefault("unshare", (name, card)) or "ok")
    monkeypatch.setattr("pa.team.set_team_memory",
                        lambda name, on: calls.setdefault("toggle", (name, on)) or "ok")
    assert m.main(["team", "share-card", "lint", "--confirm-schema-bump"]) == 0
    assert calls["share"] == ("acme", "lint", True)
    assert m.main(["team", "unshare-card", "lint"]) == 0
    assert calls["unshare"] == ("acme", "lint")
    assert m.main(["team", "memory", "off"]) == 0
    assert calls["toggle"] == ("acme", False)
    # `on` is a separate literal in the dispatch, so pin it too — with a fresh
    # recorder, since the setdefault above would keep the `off` tuple forever.
    on_calls = []
    monkeypatch.setattr("pa.team.set_team_memory",
                        lambda name, on: on_calls.append((name, on)) or "ok")
    assert m.main(["team", "memory", "on"]) == 0
    assert on_calls == [("acme", True)]


# --- Task 12: the REAL fallback, end to end ---


def test_show_falls_back_through_the_real_team_reader(team_env):
    # Every fallback test in tests/test_memory.py monkeypatches
    # `_team_card_bodies` away, so card_bodies_for_lookup itself would never
    # run. This one wires the whole chain: a card on disk in the team cache ->
    # cards_for_index -> card_bodies_for_lookup -> memory.show.
    _seed_team_card("acme", "alice", "pytest-only", desc="Use pytest",
                    body="always run pytest first")
    out = memory.show("pytest-only")
    assert "always run pytest first" in out          # the real body, read off disk
    assert "alice" in out and "read-only" in out     # attributed, not passed off as mine
    assert not memory._card_path("pytest-only").exists()   # never materialized locally


def test_the_off_switch_also_turns_off_the_show_fallback(team_env):
    # The off switch is inherited from cards_for_index — pin that it really is.
    _seed_team_card("acme", "alice", "pytest-only", body="always run pytest first")
    team.set_team_memory("acme", False)
    assert "no card named" in memory.show("pytest-only")


def test_the_off_switch_takes_effect_immediately(team_env):
    # MEMORY.md is what a session reads at start-up, so `off` must rebuild it now
    # rather than waiting for the next unrelated memory operation.
    from pa import memory
    _seed_team_card("acme", "alice", "pytest-only", desc="Use pytest")
    memory.add("mine", "d", "preference", "b")          # creates the vault + index
    assert "pytest-only" in memory.hot_index_text()
    team.set_team_memory("acme", False)
    assert "pytest-only" not in memory.hot_index_text()  # no further command needed
    team.set_team_memory("acme", True)
    assert "pytest-only" in memory.hot_index_text()


# --- final-review regressions ---

@pytest.mark.parametrize("bad", [12345, None, ["a"], {"a": 1}])
def test_a_non_string_manifest_value_does_not_crash_sync(team_env, bad):
    # bytes_to_manifest only checks that the JSON is an object, so a value like
    # 12345 reached Path() and raised TypeError BEFORE the guard could fire —
    # killing sync mid-loop. last_synced_commit then never advances, so the next
    # sync re-reads the same manifest and dies again, forever, for every member.
    from pa import teamcrypto
    team.privacy_on("acme")
    repo = team.repo_dir("acme")
    meta = team._read_committed_meta(repo)
    h = "b" * 32
    # NB: list/dict are the classes that crashed _live_pairs (unhashable in
    # set.add), which the join-site isinstance term alone did NOT cover.
    team._write_manifest(repo / "members" / "alice" / "manifest.age",
                         meta["recipient"], {h: bad})
    (repo / "members" / "alice" / "wiki" / (h + ".age")).write_bytes(
        teamcrypto.encrypt(meta["recipient"], b"payload"))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "hostile"],
                   check=True, capture_output=True)
    out = team.sync("acme", force=True)          # must NOT raise
    assert "synced" in out
    # A structurally invalid manifest is rejected at the boundary, so the member
    # is skipped wholesale (skip-don't-poison) and their manifest counted.
    assert any("manifest.age" in f
               for f in team.load_local("acme")["decrypt_failures"])


def test_an_untracked_blob_does_not_short_circuit_the_promotion(team_env):
    # An interrupt between dest.write_bytes and `git add` leaves an untracked,
    # plaintext-identical blob. Without a tracked-ness check every later run
    # returned "already up to date" before the add, the schema bump and the
    # commit — permanently, silently, and un-clearable via unshare_card.
    memory.add("lint", "d", "feedback", "b")
    repo = team.repo_dir("acme")
    dest = repo / "members" / "alice" / "memory" / "lint.md.age"
    dest.parent.mkdir(parents=True, exist_ok=True)
    from pa import teamcrypto
    meta = team._read_committed_meta(repo)
    dest.write_bytes(teamcrypto.encrypt(meta["recipient"], memory.build_promotion("lint")))
    assert dest.exists()                          # the interrupted state
    out = team.share_card("acme", "lint", confirm_schema_bump=True)
    assert out.startswith("promoted card")        # not "already up to date"
    assert team._read_committed_meta(repo)["schema_version"] == 3
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch",
                              "--", "members/alice/memory/lint.md.age"],
                             capture_output=True)
    assert tracked.returncode == 0                # actually committed now

