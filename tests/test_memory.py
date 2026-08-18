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


def test_promotion_keeps_only_name_description_type_and_body():
    memory.add("lint", "Run the linter", "feedback", "Always lint first.")
    memory.set_stats("lint", uses=7, last_used="2026-01-02")
    blob = memory.build_promotion("lint")
    text = blob.decode("utf-8")
    assert "uses:" not in text          # invariant 2: zero behavioral data
    assert "last_used:" not in text
    assert "created:" not in text
    assert "name: lint" in text
    assert "description: Run the linter" in text
    assert "type: feedback" in text
    assert "Always lint first." in text


def test_promotion_key_order_and_trailing_shape_are_pinned():
    memory.add("lint", "Run the linter", "feedback", "Body here.")
    assert memory.build_promotion("lint").decode("utf-8") == (
        "---\n"
        "name: lint\n"
        "description: Run the linter\n"
        "type: feedback\n"
        "---\n"
        "\n"
        "Body here.\n"
    )


def test_promotion_refuses_a_missing_card():
    with pytest.raises(ValueError, match="no card"):
        memory.build_promotion("nope")


def test_promotion_refuses_an_invalid_name():
    with pytest.raises(ValueError):
        memory.build_promotion("../escape")


def test_promotion_does_not_touch_the_personal_original():
    memory.add("lint", "Run the linter", "feedback", "Body.")
    memory.set_stats("lint", uses=5, last_used="2026-01-02")
    before = memory._card_path("lint").read_bytes()
    memory.build_promotion("lint")
    assert memory._card_path("lint").read_bytes() == before   # invariant 1


def _fake_cards(monkeypatch, cards):
    monkeypatch.setattr(memory, "_team_cards", lambda: cards)


def test_team_section_renders_with_attribution(monkeypatch):
    memory.add("mine", "My card", "preference", "body")
    _fake_cards(monkeypatch, [{"name": "pytest-only", "description": "Use pytest",
                               "member": "alice", "team": "acme"}])
    memory.rebuild_index()
    text = memory.hot_index_text()
    assert "## Team cards (read-only)" in text
    assert "- pytest-only — Use pytest (team: alice)" in text


def test_repeated_rebuild_keeps_the_team_section(monkeypatch):
    # round-1 Critical: `pa memory add` must not wipe team cards.
    _fake_cards(monkeypatch, [{"name": "t", "description": "d",
                               "member": "alice", "team": "acme"}])
    memory.rebuild_index()
    memory.add("new-personal", "desc", "preference", "body")   # calls rebuild_index
    assert "## Team cards (read-only)" in memory.hot_index_text()


def test_personal_card_shadows_a_same_named_team_card(monkeypatch):
    memory.add("lint", "Mine wins", "preference", "body")
    _fake_cards(monkeypatch, [{"name": "lint", "description": "Theirs",
                               "member": "alice", "team": "acme"}])
    memory.rebuild_index()
    text = memory.hot_index_text()
    assert "- lint — Mine wins" in text
    assert "shadowed" in text                       # team line marked, not dropped


def test_cross_member_collision_lists_both(monkeypatch):
    # No personal card here, so nothing else creates the vault — and rebuild_index
    # deliberately no-ops on a missing one (spec §6: read paths never resurrect it).
    config.vault().mkdir(parents=True, exist_ok=True)
    _fake_cards(monkeypatch, [
        {"name": "lint", "description": "A", "member": "alice", "team": "acme"},
        {"name": "lint", "description": "B", "member": "bob", "team": "acme"},
    ])
    memory.rebuild_index()
    text = memory.hot_index_text()
    assert "(team: alice)" in text and "(team: bob)" in text


def test_no_team_cards_omits_the_section(monkeypatch):
    _fake_cards(monkeypatch, [])
    memory.add("mine", "d", "preference", "b")
    assert "## Team cards" not in memory.hot_index_text()


def test_hot_cold_counter_counts_personal_cards_only(monkeypatch):
    memory.add("mine", "d", "preference", "b")
    _fake_cards(monkeypatch, [{"name": "t", "description": "d",
                               "member": "alice", "team": "acme"}])
    memory.rebuild_index()
    assert "1 hot / 0 cold" in memory.hot_index_text()


def test_provider_swallows_an_absent_team_layer(monkeypatch):
    # `import` raises ImportError when sys.modules holds a None entry.
    import sys, pa
    monkeypatch.setitem(sys.modules, "pa.team", None)
    monkeypatch.delattr(pa, "team", raising=False)
    assert memory._team_cards() == []            # personal-only install must not crash


def test_provider_swallows_a_broken_team_layer(monkeypatch):
    # The branch that actually fires in production: pa.team imports fine (same
    # package) but cards_for_index blows up. Fold-in must degrade, never break
    # the personal index.
    # A RAISING setattr (Task 4 landed the attribute), so this now also guards
    # against `cards_for_index` being renamed or dropped.
    from pa import team
    monkeypatch.setattr(team, "cards_for_index", lambda: 1 / 0)
    assert memory._team_cards() == []


def test_a_broken_team_layer_still_writes_the_personal_index(monkeypatch):
    from pa import team
    monkeypatch.setattr(team, "cards_for_index", lambda: 1 / 0)
    memory.add("mine", "d", "preference", "b")
    assert "- mine — d" in memory.hot_index_text()


# --- Task 12: read-only, attributed team fallback in show/recall ---


def _fake_bodies(monkeypatch, cards):
    monkeypatch.setattr(memory, "_team_card_bodies", lambda: cards)


def test_show_falls_back_to_a_team_card_with_attribution(monkeypatch):
    _fake_bodies(monkeypatch, [{"name": "t", "description": "d", "body": "team body",
                                "member": "alice", "team": "acme"}])
    out = memory.show("t")
    assert "team body" in out and "alice" in out


def test_team_fallback_never_writes_into_the_personal_vault(monkeypatch):
    # The `_bump` trap: _bump -> _write -> _card_path -> _cards_dir() always
    # targets the PERSONAL vault, so routing a team hit through it would
    # materialize a teammate's card as the receiver's own — which they could
    # then re-promote under their own name.
    _fake_bodies(monkeypatch, [{"name": "t", "description": "d", "body": "b",
                                "member": "alice", "team": "acme"}])
    memory.show("t")
    assert not memory._card_path("t").exists()      # no counter, no materialization


def test_show_requires_from_on_a_cross_member_collision(monkeypatch):
    _fake_bodies(monkeypatch, [
        {"name": "t", "description": "d", "body": "A", "member": "alice", "team": "acme"},
        {"name": "t", "description": "d", "body": "B", "member": "bob", "team": "acme"},
    ])
    assert "--from" in memory.show("t")
    assert "A" in memory.show("t", member="alice")


def test_personal_card_wins_over_a_team_card(monkeypatch):
    memory.add("t", "mine", "preference", "personal body")
    _fake_bodies(monkeypatch, [{"name": "t", "description": "d", "body": "team body",
                                "member": "alice", "team": "acme"}])
    assert "personal body" in memory.show("t")


def test_show_on_a_name_nobody_has_still_reports_the_miss(monkeypatch):
    _fake_bodies(monkeypatch, [{"name": "other", "description": "d", "body": "b",
                                "member": "alice", "team": "acme"}])
    assert "no card named" in memory.show("t")


def test_recall_appends_team_matches_without_bumping(monkeypatch):
    memory.add("mine", "personal desc", "preference", "a shared keyword")
    _fake_bodies(monkeypatch, [{"name": "theirs", "description": "d",
                                "body": "a shared keyword", "member": "alice",
                                "team": "acme"}])
    hits = memory.recall("shared keyword")
    assert [(h["name"], h["member"]) for h in hits] == [("mine", None), ("theirs", "alice")]
    assert memory.stats("mine")["uses"] == 1            # the personal hit still bumps
    assert not memory._card_path("theirs").exists()     # the team hit never materializes


def test_cli_show_takes_from_and_recall_prints_the_attribution(monkeypatch, capsys):
    from pa import __main__ as m
    seen = []
    monkeypatch.setattr(memory, "show",
                        lambda name, member=None: seen.append((name, member)) or "X")
    assert m.main(["memory", "show", "t", "--from", "alice"]) == 0
    assert seen == [("t", "alice")]
    assert m.main(["memory", "show", "t"]) == 0
    assert seen[-1] == ("t", None)
    monkeypatch.setattr(memory, "recall", lambda kw: [
        {"name": "p", "description": "d", "body": "b", "member": None},
        {"name": "t", "description": "d", "body": "b", "member": "alice"}])
    assert m.main(["memory", "recall", "kw"]) == 0
    out = capsys.readouterr().out
    assert "## p — d\n" in out                       # personal: no attribution suffix
    assert "## t — d (team: alice)\n" in out
