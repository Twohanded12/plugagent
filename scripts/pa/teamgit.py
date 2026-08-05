"""Git operations for the team layer. Pure mechanism: no team policy here
except the plaintext-leak allowlist, which is a security invariant (spec §4.1)."""
from __future__ import annotations  # PEP 604 unions below must not break Py3.9

import subprocess
from pathlib import Path

PUSH_ATTEMPTS = 3


class LeakGuardError(Exception):
    pass


class PushError(Exception):
    pass


class GitError(Exception):
    pass


def _first_line(text: str) -> str:
    lines = (text or "").strip().splitlines()
    return lines[0] if lines else ""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    if check and out.returncode != 0:
        raise GitError(f"git {args[0]} failed: {_first_line(out.stderr)}")
    return out


def clone(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "clone", "-q", url, str(dest)],
                       capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        # Never echo the URL — it can embed credentials/tokens.
        raise GitError(f"clone failed: {_first_line(e.stderr)}")
    # Local identity so commits work on machines/CI without global git config
    for k, v in (("user.email", "plugagent@local"), ("user.name", "plugagent")):
        out = subprocess.run(["git", "-C", str(dest), "config", "--get", k],
                             capture_output=True, text=True)
        if not out.stdout.strip():
            subprocess.run(["git", "-C", str(dest), "config", k, v],
                           capture_output=True, text=True, check=True)


def head_commit(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def unpushed_files(repo: Path) -> list[str]:
    """Every path touched by any commit that would leave on the next push."""
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "@{u}", check=False)
    rev_range = "@{u}..HEAD" if upstream.returncode == 0 else "HEAD"
    out = _git(repo, "log", "--format=", "--name-only", "-z", rev_range, check=False)
    if out.returncode != 0:      # unborn HEAD — nothing committed yet
        return []
    return sorted({f for f in out.stdout.split("\0") if f})


def leak_violations(repo: Path) -> list[str]:
    """Allowlist check (spec §4.1): only root team.json and non-empty *.age
    paths may leave. Checked against every commit in the unpushed range."""
    bad = []
    for f in unpushed_files(repo):
        if f == "team.json":
            continue
        if f.endswith(".age") and len(Path(f).name) > 4:
            continue
        bad.append(f)
    return bad


def push_with_rebase(repo: Path) -> None:
    """Fast-path push; on non-fast-forward reject, pull --rebase and retry.
    The leak guard runs before EVERY attempt (spec §4.1: nothing but the
    allowlist ever leaves the machine)."""
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch == "HEAD":
        raise PushError("detached HEAD — check out a branch first")
    last_err = ""
    for _ in range(PUSH_ATTEMPTS):
        bad = leak_violations(repo)
        if bad:
            raise LeakGuardError(
                "refusing to push plaintext files: " + ", ".join(sorted(bad)))
        pushed = _git(repo, "push", "-q", "-u", "origin", branch, check=False)
        if pushed.returncode == 0:
            return
        last_err = _first_line(pushed.stderr)
        rebased = _git(repo, "pull", "-q", "--rebase", "origin", branch, check=False)
        if rebased.returncode != 0:
            _git(repo, "rebase", "--abort", check=False)
            raise PushError(f"pull --rebase failed: {_first_line(rebased.stderr)}")
    raise PushError(f"push failed after {PUSH_ATTEMPTS} attempts: {last_err}")


def changed_age_files(repo: Path, since_commit: str | None) -> list[tuple[str, str]]:
    """(.age path, status) pairs changed since a commit; None baseline = all .age.
    NUL-delimited to survive non-ASCII paths; renames report the vacated .age
    path as a "D" so callers can drop the stale copy."""
    if since_commit is None:
        out = _git(repo, "ls-files", "-z")
        return [(f, "A") for f in out.stdout.split("\0") if f.endswith(".age")]
    out = _git(repo, "diff", "--name-status", "-z", f"{since_commit}..HEAD")
    tokens = out.stdout.split("\0")
    result, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        status = tok[:1]
        if status in ("R", "C"):
            old, new = tokens[i + 1], tokens[i + 2]
            i += 3
            if new.endswith(".age"):
                result.append((new, status))
            if old.endswith(".age") and not new.endswith(".age"):
                result.append((old, "D"))   # renamed away: caller must drop stale copy
        else:
            path = tokens[i + 1]
            i += 2
            if path.endswith(".age"):
                result.append((path, status))
    return result
