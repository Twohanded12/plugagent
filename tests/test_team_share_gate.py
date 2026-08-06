import json
import subprocess

import pytest

from pa import config, team, teamgit
from tests.team_helpers import fake_crypto, make_remote


@pytest.fixture()
def joined(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    fake_crypto(monkeypatch)
    remote = make_remote(tmp_path)
    team.init_team("alpha", str(remote), "lead")
    return tmp_path, remote


def _bump_remote_generation(remote, tmp_path):
    """A leader on another machine rekeys to v2 on the remote."""
    d = tmp_path / "leaderclone"
    subprocess.run(["git", "clone", "-q", str(remote), str(d)], check=True)
    for k, v in (("user.email", "l@l"), ("user.name", "l")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    (d / "team.json").write_text(json.dumps(
        {"name": "alpha", "recipient": "age1fake-v2", "key_version": 2,
         "schema_version": 1}, indent=2) + "\n")
    subprocess.run(["git", "-C", str(d), "commit", "-aqm", "rekey: v2"], check=True)
    subprocess.run(["git", "-C", str(d), "push", "-q"], check=True)


def _put_page(rel, desc, body):
    from pa import distill
    distill.wiki_put(rel, f"---\ndescription: {desc}\n---\n\n{body}\n")


def test_share_refuses_when_behind_after_pull(joined):
    tmp_path, remote = joined
    _bump_remote_generation(remote, tmp_path)   # remote is v2; our local clone is still v1
    _put_page("concepts/x.md", "d", "b")
    with pytest.raises(team.TeamError, match="rekeyed"):
        team.share("alpha", "concepts/x.md")    # must pull, see v2 > local v1, refuse


def test_share_still_works_at_matching_generation(joined):
    _put_page("concepts/y.md", "d", "b")
    assert "shared" in team.share("alpha", "concepts/y.md")
