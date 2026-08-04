"""Personalization memory: one card = one fact. Frontmatter is plain key: value
lines (stdlib only — no YAML dependency). Usage stats live in the frontmatter."""
import datetime as _dt
import re
from pathlib import Path

from pa import config

HOT_USES = 3
HOT_DAYS = 14
TYPES = ("preference", "feedback", "context")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _cards_dir() -> Path:
    # Deliberately does NOT mkdir: read paths must never resurrect a lost vault
    # (that would defeat config.vault_guard — spec §6). Directory creation
    # happens only behind a vault-exists check or the guard itself.
    return config.vault() / "memory" / "cards"


def _card_path(name: str) -> Path:
    if not _NAME_RE.match(name) or ".." in name:
        raise ValueError(f"invalid card name {name!r} — use letters, digits, dot, dash, underscore")
    return _cards_dir() / f"{name}.md"


def _index_path() -> Path:
    return config.vault() / "memory" / "MEMORY.md"


def _parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    meta = {}
    body = text
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    meta.setdefault("name", path.stem)
    try:
        meta["uses"] = int(meta.get("uses", 0))
    except (TypeError, ValueError):
        meta["uses"] = 0
    return {"meta": meta, "body": body}


def _write(name: str, meta: dict, body: str) -> None:
    lines = (["---"] + [f"{k}: {str(v).replace(chr(10), ' ').strip()}" for k, v in meta.items()]
              + ["---", "", body.strip(), ""])
    _card_path(name).write_text("\n".join(lines), encoding="utf-8")


def add(name: str, description: str, ctype: str, body: str) -> None:
    if ctype not in TYPES:
        raise ValueError(f"type must be one of {TYPES}")
    path = _card_path(name)  # validate name before any side effects
    if not config.vault_guard():
        raise RuntimeError("vault is missing — restore it or run `pa vault reinit`")
    _cards_dir().mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    meta = {"name": name, "description": description, "type": ctype,
            "created": today, "uses": 0, "last_used": today}
    if path.exists():
        existing = _parse(path)["meta"]
        meta["created"] = existing.get("created", today)
        meta["uses"] = existing.get("uses", 0)
        meta["last_used"] = existing.get("last_used", today)
    _write(name, meta, body)
    rebuild_index()


def _bump(path: Path) -> dict:
    # Unsynchronized read-modify-write: a lost increment under concurrent
    # sessions is acceptable for soft personalization counters like these.
    card = _parse(path)
    card["meta"]["uses"] = card["meta"]["uses"] + 1
    card["meta"]["last_used"] = _dt.date.today().isoformat()
    _write(path.stem, card["meta"], card["body"])
    return card


def show(name: str) -> str:
    path = _card_path(name)
    if not path.exists():
        return f"no card named {name!r}"
    card = _bump(path)
    rebuild_index()
    return f"# {name}\n{card['meta'].get('description', '')}\n\n{card['body'].strip()}"


def recall(keyword: str):
    kw = keyword.lower()
    hits = []
    if not _cards_dir().exists():
        return hits
    for path in sorted(_cards_dir().glob("*.md")):
        if not _NAME_RE.match(path.stem):
            continue  # skip, don't poison: a hand-authored bad filename can't be bumped/rewritten
        card = _parse(path)
        hay = f"{card['meta'].get('name','')} {card['meta'].get('description','')} {card['body']}".lower()
        if kw in hay:
            card = _bump(path)
            hits.append({"name": card["meta"]["name"],
                         "description": card["meta"].get("description", ""),
                         "body": card["body"].strip()})
    rebuild_index()
    return hits


def forget(name: str) -> bool:
    path = _card_path(name)
    if not path.exists():
        return False
    path.unlink()
    rebuild_index()
    return True


def stats(name: str) -> dict:
    return _parse(_card_path(name))["meta"]


def set_stats(name: str, uses: int, last_used: str) -> None:
    path = _card_path(name)
    card = _parse(path)
    card["meta"]["uses"] = uses
    card["meta"]["last_used"] = last_used
    _write(name, card["meta"], card["body"])


def _is_hot(meta: dict) -> bool:
    if meta["uses"] >= HOT_USES:
        return True
    try:
        last = _dt.date.fromisoformat(meta.get("last_used", ""))
    except ValueError:
        return True  # malformed date: keep visible rather than silently hide
    return (_dt.date.today() - last).days <= HOT_DAYS


def rebuild_index() -> None:
    if not config.vault().exists():
        return  # never resurrect a lost vault from a read path
    hot, cold = [], 0
    _cards_dir().mkdir(parents=True, exist_ok=True)
    for path in sorted(_cards_dir().glob("*.md")):
        meta = _parse(path)["meta"]
        if _is_hot(meta):
            hot.append(f"- {meta['name']} — {meta.get('description', '')}")
        else:
            cold += 1
    header = ("# Memory — hot index\n\n"
              f"{len(hot)} hot / {cold} cold. Fetch bodies with "
              "`pa memory show <name>` or `pa memory recall <keyword>`.\n\n")
    _index_path().parent.mkdir(parents=True, exist_ok=True)
    _index_path().write_text(header + "\n".join(hot) + "\n", encoding="utf-8")


def hot_index_text() -> str:
    p = _index_path()
    return p.read_text(encoding="utf-8") if p.exists() else ""
