"""Flow 3 machinery: cursor-aware raw listing, wiki writes, cursor advance,
and the one sanctioned raw deletion path."""
import datetime as _dt
import re
import sys
from pathlib import Path

from pa import config


def _raw_dir() -> Path:
    return config.vault() / "raw" / "sessions"


def _cursor_path() -> Path:
    """Path to the cursor file. Does NOT create `.state` — reads must never
    resurrect vault structure; only `advance()` (after its vault_guard check)
    is allowed to create it."""
    return config.vault() / ".state" / "cursor"


def pending():
    d = _raw_dir()
    if not d.exists():
        return []
    cp = _cursor_path()
    cursor = cp.read_text().strip() if cp.exists() else ""
    return [p for p in sorted(d.glob("*.md")) if p.name > cursor]


def advance(marker: str) -> None:
    if not config.vault_guard():
        raise RuntimeError("vault is missing — restore it or run `pa vault reinit`")
    if not (_raw_dir() / marker).exists():
        raise ValueError(f"unknown raw file {marker!r} — cursor not moved")
    cp = _cursor_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(marker + "\n", encoding="utf-8")
    _log(f"DISTILL cursor -> {marker}")


def _description_of(content: str) -> str:
    """description: is only honored inside the leading frontmatter block —
    a `description:`-looking line in the page body must never outrank it.
    Falls back to the document's first heading."""
    fm = re.match(r"^---\n(.*?)\n---", content, re.S)
    if fm:
        m = re.search(r"^description:\s*(.+)$", fm.group(1), re.M)
        if m:
            return m.group(1).strip()
    m = re.search(r"^#\s+(.+)$", content, re.M)
    return m.group(1).strip() if m else ""


def wiki_put(relpath: str, content: str) -> Path:
    if not relpath or relpath == "index.md":
        raise ValueError("invalid wiki relpath")
    if not config.vault_guard():
        raise RuntimeError("vault is missing — restore it or run `pa vault reinit`")
    wiki = config.vault() / "wiki"
    page = wiki / relpath
    if not page.resolve().is_relative_to(wiki.resolve()):
        raise ValueError("relpath escapes the wiki directory")
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(content, encoding="utf-8")

    index = wiki / "index.md"
    line = f"- {relpath} — {_description_of(content)}"
    lines = index.read_text(encoding="utf-8").splitlines() if index.exists() else ["# Wiki Index", ""]
    lines = [l for l in lines if not l.startswith(f"- {relpath} ")]
    lines.append(line)
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"DISTILL wrote {relpath}")
    return page


def raw_forget(sid_fragment: str):
    """Delete the one raw file matching sid_fragment. Returns (ok,
    match_count): ok is False on zero or ambiguous matches, so callers can
    distinguish "no match" from "too many matches"."""
    d = _raw_dir()
    matches = [p for p in d.glob("*.md") if sid_fragment in p.name] if d.exists() else []
    if len(matches) != 1:
        return False, len(matches)
    matches[0].unlink()
    _log(f"RAW-FORGET {matches[0].name} (explicit user request)")
    return True, 1


def _log(line: str) -> None:
    wiki = config.vault() / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(wiki / "log.md", "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")


def put_from_stdin(relpath: str) -> Path:
    return wiki_put(relpath, sys.stdin.read())
