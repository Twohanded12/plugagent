import pytest

from pa import config, status


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    return tmp_path


def test_status_before_onboarding_says_so():
    line = status.one_line()
    assert "not onboarded" in line


def test_status_reports_name_capture_and_errors(tmp_path):
    config.set_value("agent_name", "Nova")
    config.set_value("capture", "on")  # explicit consent, simulating post-onboarding state
    (config.vault() / "raw" / "sessions").mkdir(parents=True)
    with open(config.state_dir() / "errors.log", "a") as f:
        f.write("2026-08-04 10:00:00 capture: boom\n")
    line = status.one_line()
    assert "Nova" in line and "capture: on" in line and "errors: 1" in line


def test_full_status_includes_cursor_and_counts(tmp_path):
    config.set_value("agent_name", "Nova")
    d = config.vault() / "raw" / "sessions"
    d.mkdir(parents=True)
    (d / "2026-08-01-x-aaaa1111.md").write_text("x")
    full = status.full()
    assert "raw sessions: 1" in full
    assert "cursor:" in full
    assert "last capture: 2026-08-01-x-aaaa1111.md" in full


def test_vault_missing_vs_not_created_distinguished(tmp_path):
    config.set_value("agent_name", "Nova")
    config.set_value("vault", str(tmp_path / "vault"))
    assert "not created yet" in status.one_line()
    config.vault_guard()                       # first run creates
    assert "ok" in status.one_line()
    import shutil
    shutil.rmtree(config.vault())
    assert "MISSING" in status.one_line()


def test_unreadable_errors_log_degrades_gracefully():
    config.set_value("agent_name", "Nova")
    log = config.state_dir() / "errors.log"
    log.write_text("boom\n")
    log.chmod(0)
    try:
        line = status.one_line()               # must not raise
        assert "Nova" in line
        assert any("unreadable" in l for l in status.full().splitlines())
    finally:
        log.chmod(0o644)


def test_errors_tail_shows_last_three():
    config.set_value("agent_name", "Nova")
    (config.vault()).mkdir(parents=True, exist_ok=True)
    with open(config.state_dir() / "errors.log", "a") as f:
        for i in range(5):
            f.write(f"err{i}\n")
    full = status.full()
    assert "last 3 of 5" in full and "err4" in full and "err0" not in full
