import shutil
import subprocess
from pathlib import Path

import pytest

from pa import config, distill, team
from tests.team_helpers import fake_crypto, make_remote

needs_age = pytest.mark.skipif(shutil.which("age") is None, reason="age not installed")


def _home(monkeypatch, tmp_path, tag):
    home = tmp_path / f"home-{tag}"
    monkeypatch.setenv("PLUGAGENT_HOME", str(home))
    config.set_value("vault", str(tmp_path / f"vault-{tag}"))
    return home


def _full_cycle(tmp_path, monkeypatch, use_fake):
    if use_fake:
        fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)

    # Leader A: init (claims the "lead" namespace in one step), share two pages
    _home(monkeypatch, tmp_path, "a")
    team.init_team("alpha", str(remote), "lead")
    distill.wiki_put("concepts/auth.md", "---\ndescription: JWT decision\n---\n\nSECRET-BODY-ONE\n")
    distill.wiki_put("decisions/retro.md", "---\ndescription: Retro cadence\n---\n\nSECRET-BODY-TWO\n")
    team.share("alpha", "concepts/auth.md")
    team.share("alpha", "decisions/retro.md")
    leader_key = team.key_path("alpha")
    received = tmp_path / "received.key"
    shutil.copy(leader_key, received)

    # Member B: join from a second home, sync, read
    _home(monkeypatch, tmp_path, "b")
    team.join_team(str(remote), received, "bob")
    cache = team.cache_dir("alpha")
    assert (cache / "members/lead/wiki/concepts/auth.md").read_text().count("SECRET-BODY-ONE") == 1
    index = (cache / "index.md").read_text()
    assert "JWT decision (lead)" in index

    # ★ Invariant 2 pinned: not one plaintext byte in the bare repo object
    # store. Only meaningful with REAL crypto — the fake prepends FAKEAGE: to
    # the plaintext, so these greps run only in the real-age variant. Dump
    # every object in the store (trees+blobs), raw bytes — catches
    # binary-framed plaintext too.
    if not use_fake:
        dump = subprocess.run(
            ["git", "-C", str(remote), "cat-file", "--batch-all-objects", "--batch"],
            capture_output=True, check=True).stdout
        # positive controls: tree objects store per-directory basenames, not
        # full paths, so assert on basenames — one per shared file, closing
        # the vacuousness gap for SECRET-BODY-TWO's source file too.
        assert b"auth.md.age" in dump
        assert b"retro.md.age" in dump
        for secret in (b"SECRET-BODY-ONE", b"SECRET-BODY-TWO"):
            assert secret not in dump

    # B shares back; A syncs and reads with attribution
    distill.wiki_put("notes/tips.md", "---\ndescription: Bob tips\n---\n\nSECRET-BODY-THREE\n")
    team.share("alpha", "notes/tips.md")
    _home(monkeypatch, tmp_path, "a")
    team.sync("alpha", force=True)
    a_cache = team.cache_dir("alpha")
    assert "SECRET-BODY-THREE" in (a_cache / "members/bob/wiki/notes/tips.md").read_text()
    if not use_fake:
        dump = subprocess.run(
            ["git", "-C", str(remote), "cat-file", "--batch-all-objects", "--batch"],
            capture_output=True, check=True).stdout
        assert b"tips.md.age" in dump  # positive control: basename, not full path
        assert b"SECRET-BODY-THREE" not in dump


def test_full_cycle_with_fake_crypto(tmp_path, monkeypatch):
    # Pipeline correctness without age (join/share/sync/cache/attribution);
    # the zero-plaintext confidentiality greps run only in the real-age variant.
    _full_cycle(tmp_path, monkeypatch, use_fake=True)


@needs_age
def test_full_cycle_with_real_age(tmp_path, monkeypatch):
    _full_cycle(tmp_path, monkeypatch, use_fake=False)
