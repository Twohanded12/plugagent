import subprocess
from pathlib import Path

import pytest

from pa import teamgit


@pytest.fixture()
def bare_remote(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    return remote


def clone_of(remote, dest):
    teamgit.clone(str(remote), dest)
    subprocess.run(["git", "-C", str(dest), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.name", "t"], check=True)
    return dest


def commit_file(repo: Path, relpath: str, data: bytes):
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", relpath], check=True)


def test_clone_and_first_push(bare_remote, tmp_path):
    repo = clone_of(bare_remote, tmp_path / "a")
    commit_file(repo, "team.json", b"{}")
    teamgit.push_with_rebase(repo)
    assert teamgit.unpushed_files(repo) == []


def test_leak_guard_allows_only_teamjson_and_age(bare_remote, tmp_path):
    repo = clone_of(bare_remote, tmp_path / "a")
    commit_file(repo, "team.json", b"{}")
    commit_file(repo, "members/alice/wiki/x.md.age", b"blob")
    assert teamgit.leak_violations(repo) == []
    commit_file(repo, "members/alice/wiki/PLAIN.md", b"secret")
    assert teamgit.leak_violations(repo) == ["members/alice/wiki/PLAIN.md"]
    commit_file(repo, "stray-note.md", b"secret at root")
    assert "stray-note.md" in teamgit.leak_violations(repo)


def test_push_refuses_on_leak_violation(bare_remote, tmp_path):
    repo = clone_of(bare_remote, tmp_path / "a")
    commit_file(repo, "plain.md", b"secret")
    with pytest.raises(teamgit.LeakGuardError):
        teamgit.push_with_rebase(repo)
    # nothing reached the remote
    out = subprocess.run(["git", "-C", str(bare_remote), "rev-list", "--all", "--count"],
                         capture_output=True, text=True)
    assert out.stdout.strip() == "0"


def test_push_race_rebases_and_succeeds(bare_remote, tmp_path):
    a = clone_of(bare_remote, tmp_path / "a")
    b = clone_of(bare_remote, tmp_path / "b")
    commit_file(a, "team.json", b"{}")
    teamgit.push_with_rebase(a)
    subprocess.run(["git", "-C", str(b), "pull", "-q", "--rebase"], check=True)
    commit_file(a, "members/alice/wiki/one.md.age", b"1")
    teamgit.push_with_rebase(a)
    # b commits without pulling first -> non-fast-forward, must rebase+push
    commit_file(b, "members/bob/wiki/two.md.age", b"2")
    teamgit.push_with_rebase(b)
    subprocess.run(["git", "-C", str(a), "pull", "-q", "--rebase"], check=True)
    assert (a / "members/bob/wiki/two.md.age").exists()


def test_changed_age_files_since(bare_remote, tmp_path):
    a = clone_of(bare_remote, tmp_path / "a")
    commit_file(a, "team.json", b"{}")
    base = teamgit.head_commit(a)
    commit_file(a, "members/alice/wiki/x.md.age", b"1")
    commit_file(a, "members/alice/wiki/y.md.age", b"2")
    changed = teamgit.changed_age_files(a, base)
    assert sorted(p for p, s in changed) == [
        "members/alice/wiki/x.md.age", "members/alice/wiki/y.md.age"]
    assert all(s in ("A", "M") for _p, s in changed)


def test_changed_age_files_none_baseline_lists_all(bare_remote, tmp_path):
    a = clone_of(bare_remote, tmp_path / "a")
    commit_file(a, "members/alice/wiki/x.md.age", b"1")
    assert teamgit.changed_age_files(a, None) == [("members/alice/wiki/x.md.age", "A")]


# --- Regression tests: full-range leak guard, NUL-safe paths, rebase-abort cleanup, strict allowlist ---


def test_leak_guard_catches_add_then_delete_secret(bare_remote, tmp_path):
    """A secret added then deleted within the unpushed range nets zero in an
    endpoint diff, but its blob is still recoverable from the remote once
    pushed. The guard must scan every commit in the range, not just the
    net diff (spec §4.1)."""
    repo = clone_of(bare_remote, tmp_path / "a")
    commit_file(repo, "team.json", b"{}")
    commit_file(repo, "secret.md", b"leaked")
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "secret.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "remove secret"], check=True)
    assert "secret.md" in teamgit.leak_violations(repo)
    with pytest.raises(teamgit.LeakGuardError):
        teamgit.push_with_rebase(repo)
    out = subprocess.run(["git", "-C", str(bare_remote), "rev-list", "--all", "--count"],
                         capture_output=True, text=True)
    assert out.stdout.strip() == "0"


def test_korean_filename_handled(bare_remote, tmp_path):
    repo = clone_of(bare_remote, tmp_path / "a")
    commit_file(repo, "team.json", b"{}")
    base = teamgit.head_commit(repo)
    commit_file(repo, "members/alice/wiki/회의록.md.age", b"data")
    assert teamgit.leak_violations(repo) == []
    changed = teamgit.changed_age_files(repo, base)
    assert ("members/alice/wiki/회의록.md.age", "A") in changed


def test_nested_teamjson_flagged(bare_remote, tmp_path):
    """Only the ROOT team.json is exempt; a nested one is not the file the
    team layer manages and must not slip through on basename alone."""
    repo = clone_of(bare_remote, tmp_path / "a")
    commit_file(repo, "team.json", b"{}")
    commit_file(repo, "sub/team.json", b"{}")
    assert "sub/team.json" in teamgit.leak_violations(repo)


def test_bare_age_filename_flagged(bare_remote, tmp_path):
    """A bare `.age` filename has no plaintext-derived stem and is not a
    real encrypted artifact from this tool — must not be waved through."""
    repo = clone_of(bare_remote, tmp_path / "a")
    commit_file(repo, ".age", b"data")
    assert ".age" in teamgit.leak_violations(repo)


def test_rename_age_to_txt_reported_and_flagged(bare_remote, tmp_path):
    repo = clone_of(bare_remote, tmp_path / "a")
    commit_file(repo, "team.json", b"{}")
    commit_file(repo, "members/alice/wiki/x.md.age", b"1")
    teamgit.push_with_rebase(repo)
    base = teamgit.head_commit(repo)
    subprocess.run(["git", "-C", str(repo), "mv", "members/alice/wiki/x.md.age",
                    "members/alice/wiki/x.md.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "rename"], check=True)
    changed = teamgit.changed_age_files(repo, base)
    assert ("members/alice/wiki/x.md.age", "D") in changed
    assert "members/alice/wiki/x.md.txt" in teamgit.leak_violations(repo)


def test_rebase_conflict_aborts_cleanly(bare_remote, tmp_path):
    a = clone_of(bare_remote, tmp_path / "a")
    commit_file(a, "team.json", b'{"v": 0}')
    teamgit.push_with_rebase(a)
    b = clone_of(bare_remote, tmp_path / "b")
    commit_file(a, "team.json", b'{"v": "from-a"}')
    teamgit.push_with_rebase(a)
    # b, still on the pre-"from-a" snapshot, edits the same line differently
    commit_file(b, "team.json", b'{"v": "from-b"}')
    with pytest.raises(teamgit.PushError):
        teamgit.push_with_rebase(b)
    assert not (b / ".git" / "rebase-merge").exists()
