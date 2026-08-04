"""Config + durable machine state paths. The only module that knows where things live."""
import json
import os
from pathlib import Path

# schema_version is stored but not migrated in v1 — there is nothing older to
# migrate from. Migration logic arrives with the first schema change (spec §6).
SCHEMA_VERSION = 1
DEFAULTS = {
    "schema_version": SCHEMA_VERSION,
    "agent_name": None,
    "vault": "~/PlugAgent",
    # consent-first: capture stays off until onboarding records an explicit choice
    "capture": "off",
    "exclude": [],
}
RESERVED_NAMES = {"claude", "plugagent", "assistant", "agent", "pa"}


def home() -> Path:
    return Path(os.environ.get("PLUGAGENT_HOME", "~/.plugagent")).expanduser()


def config_path() -> Path:
    return home() / "config.json"


def state_dir() -> Path:
    d = home() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass  # corrupt config behaves like first run; status surfaces it
    return cfg


def save(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def set_value(key: str, raw: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unknown config key: {key}")
    if key == "capture" and raw not in ("on", "off"):
        raise ValueError("capture must be 'on' or 'off'")
    if key == "agent_name":
        err = name_error(raw)
        if err:
            raise ValueError(err)
    value = raw
    if isinstance(DEFAULTS[key], list):
        value = json.loads(raw)
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a JSON list")
    cfg = load()
    cfg[key] = value
    save(cfg)


def vault() -> Path:
    return Path(load()["vault"]).expanduser()


def name_error(name: str):
    """Return a human-readable rejection reason, or None if the name is usable."""
    n = (name or "").strip()
    if not n:
        return "name must not be empty"
    if n.lower() in RESERVED_NAMES:
        return f"{n!r} is reserved — pick a distinctive name"
    return None


def vault_guard() -> bool:
    """Gate for every component that would CREATE vault directories.
    First run: create the vault and stamp the marker. A vault that existed
    before but is now gone is NEVER recreated (spec §6) — flag it and refuse.
    A restored vault clears the flag automatically."""
    v = vault()
    init = state_dir() / "vault_initialized"
    missing = state_dir() / "vault_missing"
    if v.exists():
        if not init.exists():
            init.write_text(str(v) + "\n", encoding="utf-8")
        if missing.exists():
            missing.unlink()
        return True
    if init.exists():
        missing.write_text(str(v) + "\n", encoding="utf-8")
        return False
    v.mkdir(parents=True, exist_ok=True)
    init.write_text(str(v) + "\n", encoding="utf-8")
    return True


def vault_reinit() -> None:
    """Explicit user-approved reset: forget the old vault's markers so the
    next write performs first-run creation again."""
    for name in ("vault_initialized", "vault_missing"):
        m = state_dir() / name
        if m.exists():
            m.unlink()
