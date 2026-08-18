# tests/test_team_memory_integration.py
import shutil
import subprocess
import pytest
from pa import config, memory, team
from tests.team_helpers import fake_crypto, make_remote

needs_age = pytest.mark.skipif(shutil.which("age") is None, reason="age not installed")


def _home(monkeypatch, tmp_path, tag):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / f"home-{tag}"))
    config.set_value("vault", str(tmp_path / f"vault-{tag}"))
    # First-run vault creation, exactly as onboarding does it. The privacy
    # harness gets this for free because every member writes a wiki page; here
    # a RECEIVER may own no personal card at all, and rebuild_index
    # deliberately no-ops on a missing vault (spec §6: a read path never
    # resurrects one). Without this the receiver assertions would fail for a
    # reason that has nothing to do with card sharing.
    config.vault_guard()


def _scenario(monkeypatch, tmp_path, use_fake):
    """alice holds THREE personal cards and promotes exactly ONE; bob joins."""
    if use_fake:
        fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    _home(monkeypatch, tmp_path, "alice")
    team.init_team("acme", str(remote), "alice")
    memory.add("secret-card-1", "Private one", "context", "do not share this")
    memory.add("secret-card-2", "Private two", "context", "do not share this")
    memory.add("shared-card", "Team norm", "feedback", "shared body")
    team.share_card("acme", "shared-card", confirm_schema_bump=True)
    key_v1 = tmp_path / "key-v1"; shutil.copy(team.key_path("acme"), key_v1)
    _home(monkeypatch, tmp_path, "bob")
    team.join_team(str(remote), key_v1, "bob")

    def at(member): _home(monkeypatch, tmp_path, member)
    def rekey():
        at("alice"); team.rekey("acme")
        newkey = tmp_path / "key-v2"; shutil.copy(team.key_path("acme"), newkey)
        return newkey
    return {"remote": remote, "at": at, "rekey": rekey, "key_v1": key_v1}


def test_only_the_promoted_card_reaches_the_team(monkeypatch, tmp_path):
    env = _scenario(monkeypatch, tmp_path, use_fake=True)
    env["at"]("bob"); team.sync("acme", force=True); memory.rebuild_index()
    index = memory.hot_index_text()
    assert "shared-card — Team norm (team: alice)" in index
    assert "secret-card-1" not in index and "secret-card-2" not in index


def test_receiver_personal_card_wins_and_is_untouched(monkeypatch, tmp_path):
    env = _scenario(monkeypatch, tmp_path, use_fake=True)
    env["at"]("bob")
    memory.add("shared-card", "Bob's own", "preference", "bob body")
    before = memory._card_path("shared-card").read_bytes()
    team.sync("acme", force=True); memory.rebuild_index()
    assert "- shared-card — Bob's own" in memory.hot_index_text()
    assert "shadowed" in memory.hot_index_text()
    assert memory._card_path("shared-card").read_bytes() == before
    assert "bob body" in memory.show("shared-card")          # personal wins


def test_unshare_removes_it_from_the_receiver(monkeypatch, tmp_path):
    env = _scenario(monkeypatch, tmp_path, use_fake=True)
    env["at"]("bob"); team.sync("acme", force=True); memory.rebuild_index()
    assert "shared-card" in memory.hot_index_text()
    env["at"]("alice"); team.unshare_card("acme", "shared-card")
    env["at"]("bob"); team.sync("acme", force=True); memory.rebuild_index()
    assert "shared-card" not in memory.hot_index_text()
    assert not (team.cache_dir("acme") / "members" / "alice" / "memory"
                / "shared-card.md").exists()


def test_rekey_keeps_team_cards_readable(monkeypatch, tmp_path):
    env = _scenario(monkeypatch, tmp_path, use_fake=True)
    env["at"]("bob"); team.sync("acme", force=True)
    newkey = env["rekey"]()
    env["at"]("bob"); team.rekey_accept("acme", newkey)
    team.sync("acme", force=True); memory.rebuild_index()
    assert "shared-card" in memory.hot_index_text()     # memory/ rotated too


@needs_age
def test_zero_unpromoted_cards_and_zero_statistics_in_all_objects(monkeypatch, tmp_path):
    env = _scenario(monkeypatch, tmp_path, use_fake=False)
    dump = subprocess.run(
        "git rev-list --objects --all | cut -d' ' -f1 | git cat-file --batch",
        cwd=env["remote"], shell=True, capture_output=True).stdout
    assert b"secret-card-1" not in dump          # unpromoted card names absent
    assert b"do not share this" not in dump      # unpromoted bodies absent
    assert b"uses:" not in dump                  # statistics stripped
    assert b"last_used:" not in dump
    # positive control: a silently no-op share_card must NOT pass this test
    env["at"]("bob"); team.sync("acme", force=True)
    cached = team.cache_dir("acme") / "members" / "alice" / "memory" / "shared-card.md"
    assert cached.exists() and "shared body" in cached.read_text(encoding="utf-8")
