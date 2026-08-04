"""Diagnostics: the error-visibility ladder's rungs 2 and 3 read from here."""
from pa import config


def _error_lines():
    p = config.state_dir() / "errors.log"
    if not p.exists():
        return []
    try:
        return p.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return [f"(errors.log unreadable: {e})"]


def _vault_state() -> str:
    v = config.vault()
    if v.exists():
        return "ok"
    # state_dir() mkdirs ~/.plugagent/state — deliberate: machine-state home,
    # not the vault; the §6 never-create rule is scoped to the vault.
    if (config.state_dir() / "vault_missing").exists() or \
       (config.state_dir() / "vault_initialized").exists():
        return f"MISSING (was {v})"
    return "not created yet"


def one_line() -> str:
    cfg = config.load()
    if not cfg["agent_name"]:
        return "PlugAgent: not onboarded yet — say hi to begin, or run /plugagent:setup"
    return (f"{cfg['agent_name']} — capture: {cfg['capture']}, "
            f"vault: {_vault_state()}, errors: {len(_error_lines())}")


def _cursor_text(cursor_path) -> str:
    if not cursor_path.exists():
        return "(none)"
    try:
        return cursor_path.read_text().strip()
    except OSError:
        return "(unreadable)"


def full() -> str:
    cfg = config.load()
    vault = config.vault()
    raw = vault / "raw" / "sessions"
    cards = vault / "memory" / "cards"
    cursor_path = vault / ".state" / "cursor"
    newest = max(raw.glob("*.md"), key=lambda p: p.stat().st_mtime, default=None) if raw.exists() else None
    lines = [
        one_line(),
        f"vault path: {vault}",
        f"last capture: {newest.name if newest else '(never)'}",
        f"raw sessions: {len(list(raw.glob('*.md'))) if raw.exists() else 0}",
        f"memory cards: {len(list(cards.glob('*.md'))) if cards.exists() else 0}",
        f"cursor: {_cursor_text(cursor_path)}",
        f"exclusions: {cfg['exclude'] or '(none)'}",
    ]
    errs = _error_lines()
    if errs:
        lines.append(f"recent errors (last 3 of {len(errs)}):")
        lines.extend(f"  {e}" for e in errs[-3:])
    return "\n".join(lines)
