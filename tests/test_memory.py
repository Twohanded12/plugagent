import datetime

import pytest

from pa import config, memory


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    return tmp_path


def test_add_creates_card_and_hot_index():
    memory.add("prefers-tabs", "User prefers tabs over spaces", "preference",
               "Stated explicitly on 2026-08-04.")
    card = config.vault() / "memory" / "cards" / "prefers-tabs.md"
    assert card.exists()
    assert "prefers-tabs" in (config.vault() / "memory" / "MEMORY.md").read_text()


def test_show_bumps_uses_and_returns_body():
    memory.add("a-card", "desc", "feedback", "body text")
    out = memory.show("a-card")
    assert "body text" in out
    assert memory.stats("a-card")["uses"] == 1


def test_recall_matches_and_bumps():
    memory.add("likes-korean", "Responds in Korean when addressed in Korean", "preference", "")
    hits = memory.recall("korean")
    assert [h["name"] for h in hits] == ["likes-korean"]
    assert memory.stats("likes-korean")["uses"] == 1


def test_forget_removes_card_and_index_line():
    memory.add("temp", "temporary", "context", "")
    memory.forget("temp")
    assert not (config.vault() / "memory" / "cards" / "temp.md").exists()
    assert "temp" not in (config.vault() / "memory" / "MEMORY.md").read_text()


def test_old_unused_card_goes_cold():
    memory.add("stale", "old fact", "context", "")
    old = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    memory.set_stats("stale", uses=0, last_used=old)
    memory.rebuild_index()
    assert "stale" not in memory.hot_index_text()


def test_heavily_used_old_card_stays_hot():
    memory.add("workhorse", "used a lot", "preference", "")
    old = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    memory.set_stats("workhorse", uses=5, last_used=old)
    memory.rebuild_index()
    assert "workhorse" in memory.hot_index_text()


def test_reads_on_lost_vault_do_not_recreate_it():
    import shutil
    memory.add("x", "a fact", "context", "")
    shutil.rmtree(config.vault())
    memory.rebuild_index()                       # read paths must all no-op
    assert memory.recall("fact") == []
    assert memory.hot_index_text() == ""
    assert not config.vault().exists()           # spec §6: no resurrection


def test_traversal_names_rejected(tmp_path):
    with pytest.raises(ValueError):
        memory.add("../evil", "d", "context", "")
    with pytest.raises(ValueError):
        memory.show("../../secret")
    with pytest.raises(ValueError):
        memory.forget("../victim")
    assert not list(tmp_path.rglob("evil.md"))


def test_newline_in_description_cannot_inject_keys():
    memory.add("nl", "line1\nname: hijack\nuses: 500", "context", "body")
    card = memory.stats("nl")
    assert card["name"] == "nl"
    assert card["uses"] == 0
    # NOTE: deviates from the coordinator's literal `"hijack" not in
    # hot_index_text()` — the collapsed description legitimately still
    # contains the substring "hijack" as user-supplied text (now safely
    # embedded in the single "description" line rather than parsed as its
    # own "name:" key). Asserting no bare substring would require scrubbing
    # real content, not fixing the injection. The actual security property —
    # no structural key hijack — is what these two lines check instead.
    assert "- nl —" in memory.hot_index_text()
    assert "- hijack —" not in memory.hot_index_text()


def test_malformed_uses_does_not_poison_index():
    memory.add("ok", "fine", "context", "")
    bad = config.vault() / "memory" / "cards" / "bad.md"
    bad.write_text("---\nname: bad\ndescription: broken\nuses: many\nlast_used: 2026-08-01\n---\n\nx\n")
    memory.rebuild_index()                      # must not raise
    assert memory.recall("fine")                # must not raise, finds ok


def test_recall_skips_invalid_card_stems():
    memory.add("ok", "fine card", "context", "")
    bad = config.vault() / "memory" / "cards" / "my card.md"
    bad.write_text("---\nname: my card\ndescription: bad filename\nuses: 0\nlast_used: 2026-08-01\n---\n\nbody\n")
    hits = memory.recall("fine")                # must not raise despite the bad-stem file
    assert [h["name"] for h in hits] == ["ok"]


def test_readd_preserves_usage_stats():
    memory.add("keep", "v1", "preference", "")
    memory.show("keep")
    memory.add("keep", "v2", "preference", "new body")
    assert memory.stats("keep")["uses"] == 1
    assert "v2" in memory.hot_index_text()
