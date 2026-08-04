import pytest

from pa import config, distill


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    d = config.vault() / "raw" / "sessions"
    d.mkdir(parents=True)
    for name in ["2026-08-01-fix-bug-aaaa1111.md",
                 "2026-08-02-write-docs-bbbb2222.md",
                 "2026-08-03-review-pr-cccc3333.md"]:
        (d / name).write_text("---\nsession_id: x\n---\ncontent")
    return tmp_path


def test_pending_lists_all_when_no_cursor():
    assert len(distill.pending()) == 3


def test_pending_respects_cursor():
    distill.advance("2026-08-02-write-docs-bbbb2222.md")
    names = [p.name for p in distill.pending()]
    assert names == ["2026-08-03-review-pr-cccc3333.md"]


def test_advance_then_pending_empty():
    distill.advance("2026-08-03-review-pr-cccc3333.md")
    assert distill.pending() == []


def test_wiki_put_writes_page_and_index():
    distill.wiki_put("concepts/testing.md",
                     "---\ndescription: How we test\n---\n\n# Testing\nnotes")
    page = config.vault() / "wiki" / "concepts" / "testing.md"
    assert page.exists()
    index = (config.vault() / "wiki" / "index.md").read_text()
    assert "concepts/testing.md — How we test" in index


def test_wiki_put_replaces_index_line_on_update():
    distill.wiki_put("concepts/t.md", "---\ndescription: v1\n---\nx")
    distill.wiki_put("concepts/t.md", "---\ndescription: v2\n---\ny")
    index = (config.vault() / "wiki" / "index.md").read_text()
    assert index.count("concepts/t.md") == 1
    assert "v2" in index


def test_raw_forget_deletes_by_sid():
    assert distill.raw_forget("bbbb2222")[0] is True
    d = config.vault() / "raw" / "sessions"
    assert len(list(d.glob("*.md"))) == 2
    assert distill.raw_forget("nope") == (False, 0)


def test_wiki_put_rejects_sibling_dir_escape():
    with pytest.raises(ValueError):
        distill.wiki_put("../wiki-evil/x.md", "---\ndescription: evil\n---\nbody")
    evil = config.vault() / "wiki-evil"
    assert not evil.exists()


def test_advance_after_vault_deletion_raises_and_does_not_recreate():
    distill.advance("2026-08-01-fix-bug-aaaa1111.md")
    vault_dir = config.vault()
    import shutil
    shutil.rmtree(vault_dir)
    with pytest.raises(RuntimeError):
        distill.advance("2026-08-02-write-docs-bbbb2222.md")
    assert not vault_dir.exists()
    assert (config.state_dir() / "vault_missing").exists()


def test_advance_with_unknown_marker_raises_and_cursor_unchanged():
    distill.advance("2026-08-01-fix-bug-aaaa1111.md")
    with pytest.raises(ValueError):
        distill.advance("2026-08-02-does-not-exist-zzzz9999.md")
    names = [p.name for p in distill.pending()]
    assert names == ["2026-08-02-write-docs-bbbb2222.md",
                      "2026-08-03-review-pr-cccc3333.md"]


def test_raw_forget_ambiguous_reports_match_count():
    d = config.vault() / "raw" / "sessions"
    (d / "2026-08-04-dup-2222extra.md").write_text("---\nsession_id: y\n---\nc")
    ok, n = distill.raw_forget("2222")
    assert ok is False
    assert n == 2


def test_wiki_put_index_line_survives_bak_companion_update():
    distill.wiki_put("concepts/t.md", "---\ndescription: v1\n---\nx")
    index_path = config.vault() / "wiki" / "index.md"
    with open(index_path, "a", encoding="utf-8") as f:
        f.write("- concepts/t.md.bak — backup copy\n")
    distill.wiki_put("concepts/t.md", "---\ndescription: v2\n---\ny")
    index = index_path.read_text()
    assert "concepts/t.md.bak — backup copy" in index
    assert index.count("concepts/t.md —") == 1
    assert "v2" in index


def test_description_body_line_does_not_outrank_frontmatter_or_heading():
    distill.wiki_put(
        "concepts/desc.md",
        "---\ndescription: real one\n---\n\n# Heading\ndescription: fake body line\n",
    )
    index = (config.vault() / "wiki" / "index.md").read_text()
    assert "concepts/desc.md — real one" in index
