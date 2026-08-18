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


PROMOTED_KEYS = ("name", "description", "type")


def build_promotion(name: str) -> bytes:
    """Serialize a personal card as a TEAM card: name/description/type + body,
    with every usage statistic (uses, last_used, created) STRIPPED.

    ALLOWLIST, not a denylist: the loop iterates PROMOTED_KEYS, so any key the
    card carries that is not in it — including hand-added ones like `author:` or
    `client:` — is dropped. Rewriting this as "remove the stats" would silently
    start leaking such keys.

    Those fields are a working-hours side channel — removing them here means the
    channel does not exist downstream (spec §4 invariant 2). Read-only: the
    personal original is never modified (invariant 1)."""
    path = _card_path(name)                      # validates the name
    if not path.exists():
        raise ValueError(f"no card named {name!r}")
    card = _parse(path)
    meta = card["meta"]
    lines = ["---"]
    for k in PROMOTED_KEYS:
        lines.append(f"{k}: {str(meta.get(k, '')).replace(chr(10), ' ').strip()}")
    lines += ["---", "", card["body"].strip(), ""]
    return "\n".join(lines).encode("utf-8")


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


def show(name: str, member=None) -> str:
    path = _card_path(name)                  # validates the name before anything else
    if path.exists():                        # personal wins (shadowing)
        card = _bump(path)
        rebuild_index()
        return f"# {name}\n{card['meta'].get('description', '')}\n\n{card['body'].strip()}"
    # TEAM FALLBACK — a SEPARATE, READ-ONLY path. It must never route through
    # _bump: _bump -> _write -> _card_path -> _cards_dir() always writes into the
    # PERSONAL vault, so bumping a team hit would silently materialize a
    # teammate's card as the receiver's own — which they could then re-promote
    # under their own name (spec §3).
    hits = [c for c in _team_card_bodies()
            if c.get("name") == name and (member is None or c.get("member") == member)]
    if not hits:
        return f"no card named {name!r}"
    if len(hits) > 1:
        who = ", ".join(sorted(str(h.get("member")) for h in hits))
        return (f"{name!r} is shared by more than one member ({who}) — "
                f"use `pa memory show {name} --from <member>`")
    c = hits[0]
    return (f"# {c['name']} (team: {c.get('member')}, read-only)\n"
            f"{c.get('description', '')}\n\n{c.get('body', '')}")


def recall(keyword: str):
    kw = keyword.lower()
    hits = []
    if _cards_dir().exists():
        for path in sorted(_cards_dir().glob("*.md")):
            if not _NAME_RE.match(path.stem):
                continue  # skip, don't poison: a hand-authored bad filename can't be bumped/rewritten
            card = _parse(path)
            hay = f"{card['meta'].get('name','')} {card['meta'].get('description','')} {card['body']}".lower()
            if kw in hay:
                card = _bump(path)
                hits.append({"name": card["meta"]["name"],
                             "description": card["meta"].get("description", ""),
                             "body": card["body"].strip(),
                             "member": None})          # None == mine
        rebuild_index()
    # Team matches are APPENDED, read-only and unbumped — same reason as show's
    # fallback above. Personal hits keep coming first, so shadowing shows through
    # in the ordering as well as in the attribution.
    for c in _team_card_bodies():
        hay = f"{c.get('name','')} {c.get('description','')} {c.get('body','')}".lower()
        if kw in hay:
            hits.append({"name": c.get("name", ""),
                         "description": c.get("description", ""),
                         "body": (c.get("body") or "").strip(),
                         "member": c.get("member")})
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


def _team_cards() -> list:
    """[{name, description, member, team}] for cached team cards, or [] when the
    team layer is absent, unconfigured, or disabled.

    The team import happens INSIDE the function so the personal layer keeps its
    module-level imports at `pa.config` alone and personal-only installs never
    hard-depend on the team layer."""
    try:
        from pa import team
    except ImportError:
        return []
    try:
        return team.cards_for_index()
    except Exception:
        return []          # fold-in must never break the personal index


def _team_card_bodies() -> list:
    """Same shape as _team_cards, plus `body` — the read-only source for show's
    and recall's team fallback. Degrades to [] on a personal-only install or a
    broken team layer, exactly as _team_cards does."""
    try:
        from pa import team
    except ImportError:
        return []
    try:
        return team.card_bodies_for_lookup()
    except Exception:
        return []          # a lookup must never break the personal path


def rebuild_index() -> None:
    if not config.vault().exists():
        return  # never resurrect a lost vault from a read path
    hot, cold, personal_names = [], 0, set()
    _cards_dir().mkdir(parents=True, exist_ok=True)
    for path in sorted(_cards_dir().glob("*.md")):
        meta = _parse(path)["meta"]
        personal_names.add(meta["name"])
        if _is_hot(meta):
            hot.append(f"- {meta['name']} — {meta.get('description', '')}")
        else:
            cold += 1
    header = ("# Memory — hot index\n\n"
              f"{len(hot)} hot / {cold} cold. Fetch bodies with "
              "`pa memory show <name>` or `pa memory recall <keyword>`.\n\n")
    body = "\n".join(hot) + "\n"
    # Team cards fold in HERE — rebuild_index is the ONLY writer of MEMORY.md,
    # so a later `pa memory add` cannot wipe the section (spec §2 Fold-in seam).
    # personal_names is collected during the loop above rather than re-parsed out
    # of the rendered hot lines, so shadowing does not silently break if the line
    # format changes — and a COLD personal card shadows a team card too.
    team_lines = []
    for c in _team_cards():
        name = c.get("name")
        if not name:
            continue          # a malformed provider entry must not break the index
        suffix = " (shadowed by your card)" if name in personal_names else ""
        team_lines.append(
            f"- {name} — {c.get('description', '')} (team: {c.get('member', '?')}){suffix}")
    if team_lines:
        body += "\n## Team cards (read-only)\n\n" + "\n".join(team_lines) + "\n"
    _index_path().parent.mkdir(parents=True, exist_ok=True)
    _index_path().write_text(header + body, encoding="utf-8")


def hot_index_text() -> str:
    p = _index_path()
    return p.read_text(encoding="utf-8") if p.exists() else ""
