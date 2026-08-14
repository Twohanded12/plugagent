"""A manifest value is content written by whichever member owns that namespace.
Before it is joined onto a local cache path it must be validated, or a teammate
can write outside the cache or crash everyone's sync permanently."""
import subprocess

from pa import team, teamcrypto


def _poison_manifest(name, member, value):
    """Point a hashed member's manifest at `value`, commit a matching blob."""
    repo = team.repo_dir(name)
    meta = team._read_committed_meta(repo)
    h = "a" * 32
    team._write_manifest(repo / "members" / member / "manifest.age",
                         meta["recipient"], {h: value})
    blob = repo / "members" / member / "wiki" / (h + ".age")
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(teamcrypto.encrypt(meta["recipient"], b"payload"))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "poison"],
                   check=True, capture_output=True)
    return h


def _failed(name, h):
    return any(h in f for f in team.load_local(name)["decrypt_failures"])


def test_an_absolute_manifest_value_is_rejected(team_env, tmp_path):
    """Unguarded this wrote decrypted content to an arbitrary absolute path
    outside the cache — arbitrary file write from any team member."""
    team.privacy_on("acme")
    escape = tmp_path / "pwned.md"
    h = _poison_manifest("acme", "alice", str(escape))
    team.sync("acme", force=True)
    assert not escape.exists()
    assert _failed("acme", h)


def test_a_traversal_manifest_value_is_rejected(team_env):
    team.privacy_on("acme")
    h = _poison_manifest("acme", "alice", "../../escape.md")
    team.sync("acme", force=True)
    assert not (team.cache_dir("acme") / "members" / "escape.md").exists()
    assert _failed("acme", h)


def test_a_nul_manifest_value_is_rejected(team_env):
    """Unguarded this crashed sync with ValueError: embedded null byte."""
    team.privacy_on("acme")
    h = _poison_manifest("acme", "alice", "notes\x00.md")
    team.sync("acme", force=True)          # must not raise
    assert _failed("acme", h)


def test_an_empty_manifest_value_is_rejected(team_env):
    """"" and "." collapse the join back to the member root, and write_bytes
    then raises IsADirectoryError. sync() is contractually soft-failing, so one
    bad entry from any teammate would crash sync for every member, forever."""
    team.privacy_on("acme")
    h = _poison_manifest("acme", "alice", "")
    out = team.sync("acme", force=True)    # must not raise
    assert "synced" in out
    assert _failed("acme", h)


def test_a_dot_manifest_value_is_rejected(team_env):
    team.privacy_on("acme")
    h = _poison_manifest("acme", "alice", ".")
    out = team.sync("acme", force=True)
    assert "synced" in out
    assert _failed("acme", h)


def test_a_legitimate_nested_value_still_syncs(team_env):
    """The guard must not reject ordinary nested wiki paths."""
    team.sync("acme", force=True)
    assert (team.cache_dir("acme") / "members" / "alice" / "wiki"
            / "concepts" / "auth.md").exists()
