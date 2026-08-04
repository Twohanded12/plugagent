"""Flow 1: token-free session capture. Called by the Stop hook via the dispatcher.

Never raises in normal operation paths that should no-op (off, excluded, missing
file). The dispatcher additionally guarantees exit 0 for the capture command.
"""
import datetime as _dt
import json
import re
from pathlib import Path

from pa import config

_EXCERPT_CHARS = 2000


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
        return "\n".join(p for p in parts if p)
    return ""


def parse_transcript(path: Path):
    """Return dict(session_id, cwd, messages=[(role, text)...]) or None if unusable."""
    session_id, cwd, messages = None, None, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        session_id = session_id or entry.get("sessionId")
        cwd = cwd or entry.get("cwd")
        if entry.get("type") in ("user", "assistant"):
            msg = entry.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            text = _text_of(content)
            if text.strip():
                messages.append((entry["type"], text.strip()))
    if not messages or not session_id:
        return None
    return {"session_id": str(session_id), "cwd": str(cwd or ""), "messages": messages}


def _slug(messages):
    first = next((t for r, t in messages if r == "user"), "session")
    words = re.sub(r"[^A-Za-z0-9가-힣 ]", "", first).split()[:5]
    return "-".join(words).lower()[:48].rstrip("-") or "session"


def _write_raw(vault: Path, session_id: str, body: str) -> Path:
    d = vault / "raw" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    sid8 = re.sub(r"[^A-Za-z0-9]", "", session_id)[:8] or "unknown0"
    id_line = f"session_id: {session_id}\n"
    path = None
    for candidate in d.glob(f"*-{sid8}*.md"):
        try:
            existing_text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if id_line in existing_text:
            path = candidate
            break
    if path is None:
        date = _dt.date.today().isoformat()
        base = d / f"{date}-{_slug_holder['slug']}-{sid8}.md"
        path = base
        if path.exists():
            n = 2
            while True:
                candidate = d / f"{date}-{_slug_holder['slug']}-{sid8}-{n}.md"
                if not candidate.exists():
                    path = candidate
                    break
                n += 1
    path.write_text(body, encoding="utf-8")
    return path


_slug_holder = {"slug": "session"}


def _log(vault: Path, line: str) -> None:
    wiki = vault / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(wiki / "log.md", "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")


def _is_excluded(cwd: str, patterns) -> bool:
    for x in patterns:
        if not x:
            continue
        base = str(Path(x).expanduser()).rstrip("/")
        if cwd == base or cwd.startswith(base + "/"):
            return True
    return False


def run(transcript_path: str) -> None:
    cfg = config.load()
    if cfg["capture"] != "on":
        return
    src = Path(transcript_path)
    if not src.exists():
        return
    if not config.vault_guard():
        return
    vault = config.vault()

    # Two accepted trade-offs, both in the lose-nothing direction:
    # 1. On parse failure cwd is unknowable, so the pointer fallback below runs
    #    before the exclusion check — an excluded project's unparseable
    #    transcript still leaves a pointer.
    # 2. vault_guard runs before the exclusion check, so the first-ever session
    #    in an excluded project may create an empty vault (nothing written to it).
    try:
        parsed = parse_transcript(src)
    except Exception:
        parsed = None
    if parsed is None:
        # Defensive fallback: keep a pointer, lose nothing, report success.
        sid = re.sub(r"[^a-z0-9]", "", src.stem.lower())[:8] or "unknown0"
        body = ("---\n"
                f"session_id: {sid}\n"
                "parse_failed: true\n"
                f"transcript: {src}\n"
                f"captured_at: {_dt.datetime.now():%Y-%m-%d %H:%M}\n"
                "---\n\n"
                "Transcript could not be parsed; original preserved at the path above.\n")
        _slug_holder["slug"] = "unparsed"
        _write_raw(vault, sid, body)
        _log(vault, f"CAPTURE parse-failed pointer for {src.name}")
        return

    if _is_excluded(parsed["cwd"], cfg["exclude"]):
        return

    _slug_holder["slug"] = _slug(parsed["messages"])
    lines = ["---",
             f"session_id: {parsed['session_id']}",
             f"cwd: {parsed['cwd']}",
             f"captured_at: {_dt.datetime.now():%Y-%m-%d %H:%M}",
             f"message_count: {len(parsed['messages'])}",
             "---", ""]
    for role, text in parsed["messages"]:
        lines.append(f"## {'User' if role == 'user' else 'Assistant'}\n")
        lines.append(text[:_EXCERPT_CHARS] + ("\n…(truncated)" if len(text) > _EXCERPT_CHARS else ""))
        lines.append("")
    path = _write_raw(vault, parsed["session_id"], "\n".join(lines))
    _log(vault, f"CAPTURE {path.name} ({len(parsed['messages'])} messages)")
