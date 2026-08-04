import json
from pathlib import Path

import pytest

from pa import capture, config

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUGAGENT_HOME", str(tmp_path / "home"))
    config.set_value("vault", str(tmp_path / "vault"))
    config.set_value("capture", "on")  # explicit consent, simulating post-onboarding state
    return tmp_path


def raw_files():
    d = config.vault() / "raw" / "sessions"
    return sorted(d.glob("*.md")) if d.exists() else []


def test_capture_writes_raw_and_log():
    capture.run(str(FIX / "transcript_ok.jsonl"))
    files = raw_files()
    assert len(files) == 1
    text = files[0].read_text()
    assert "session_id: abc12345" in text
    assert "Fix the login bug" in text
    assert "abc12345" in files[0].name
    log = (config.vault() / "wiki" / "log.md").read_text()
    assert "CAPTURE" in log


def test_same_session_id_updates_same_file():
    capture.run(str(FIX / "transcript_ok.jsonl"))
    capture.run(str(FIX / "transcript_ok.jsonl"))
    assert len(raw_files()) == 1


def test_unparseable_transcript_stores_pointer():
    capture.run(str(FIX / "transcript_bad.jsonl"))
    files = raw_files()
    assert len(files) == 1
    text = files[0].read_text()
    assert "parse_failed: true" in text
    assert "transcript_bad.jsonl" in text  # pointer to original


def test_capture_off_is_noop():
    config.set_value("capture", "off")
    capture.run(str(FIX / "transcript_ok.jsonl"))
    assert raw_files() == []


def test_excluded_cwd_is_noop(tmp_path):
    config.set_value("exclude", '["/Users/me/proj"]')
    capture.run(str(FIX / "transcript_ok.jsonl"))
    assert raw_files() == []


def test_missing_transcript_is_noop():
    capture.run("/nonexistent/path.jsonl")
    assert raw_files() == []


def test_first_run_creates_vault_and_marker():
    capture.run(str(FIX / "transcript_ok.jsonl"))
    assert config.vault().exists()
    assert (config.state_dir() / "vault_initialized").exists()


def test_lost_vault_is_never_recreated():
    import shutil
    capture.run(str(FIX / "transcript_ok.jsonl"))
    shutil.rmtree(config.vault())
    capture.run(str(FIX / "transcript_ok.jsonl"))
    assert not config.vault().exists()          # spec §6: never auto-recreate
    assert (config.state_dir() / "vault_missing").exists()


def test_cli_capture_exits_zero_even_on_internal_error(monkeypatch):
    from pa.__main__ import main
    monkeypatch.setattr("pa.capture.run", lambda p: 1 / 0)
    assert main(["capture", "--transcript", "whatever"]) == 0
    errors = (config.state_dir() / "errors.log").read_text()
    assert "ZeroDivisionError" in errors


def test_weird_shapes_fall_back_to_pointer():
    capture.run(str(FIX / "transcript_weird.jsonl"))
    files = raw_files()
    assert len(files) == 1
    assert "parse_failed: true" in files[0].read_text()


def test_sid8_collision_creates_two_files(tmp_path):
    a = tmp_path / "a.jsonl"; b = tmp_path / "b.jsonl"
    line = '{{"type":"user","sessionId":"{sid}","cwd":"/x","message":{{"role":"user","content":"hello"}}}}'
    a.write_text(line.format(sid="abcdef12-aaaa-1111-2222-333344445555"))
    b.write_text(line.format(sid="abcdef12-bbbb-1111-2222-333344445555"))
    capture.run(str(a)); capture.run(str(b))
    assert len(raw_files()) == 2


def test_exclusion_does_not_match_sibling_prefix():
    config.set_value("exclude", '["/Users/me/pro"]')
    capture.run(str(FIX / "transcript_ok.jsonl"))   # cwd is /Users/me/proj
    assert len(raw_files()) == 1


def test_pointer_path_does_not_overwrite_good_capture_on_sid8_substring_match(tmp_path):
    # Good capture first — full session_id abc12345-1111-2222-3333-444455556666.
    capture.run(str(FIX / "transcript_ok.jsonl"))

    # An unparseable transcript whose FILENAME stem sanitizes to the same first-8
    # chars ("abc12345") as the good session's id — the truncated pointer id must
    # not substring-match the good file's full session_id line and steal it.
    bad = tmp_path / "abc12345-replay-not-json.jsonl"
    bad.write_text("this is not json at all\n")
    capture.run(str(bad))

    files = raw_files()
    assert len(files) == 2
    good = next(f for f in files if "parse_failed: true" not in f.read_text())
    pointer = next(f for f in files if "parse_failed: true" in f.read_text())
    assert "Fix the login bug" in good.read_text()
    assert "session_id: abc12345-1111-2222-3333-444455556666" in good.read_text()
    assert pointer.read_text() != good.read_text()


def test_no_capture_without_explicit_consent(tmp_path):
    # Fresh install: a config.json exists (e.g. written by onboarding's naming
    # step) but capture was never explicitly recorded — the key is simply
    # absent, exactly as it would be before onboarding reaches the consent
    # question. The Stop hook fires unconditionally on session end, so the
    # only thing standing between "no consent yet" and "silent capture" is
    # config.load() falling back to an off default. Write that config by hand
    # (bypassing the autouse fixture's explicit capture="on") to prove it.
    config.config_path().write_text(json.dumps({
        "agent_name": "Nova",
        "vault": str(config.vault()),
    }))
    capture.run(str(FIX / "transcript_ok.jsonl"))
    assert raw_files() == []


def test_suffixed_collision_file_dedups_on_refire(tmp_path):
    def fire(name, sid):
        p = tmp_path / f"{name}.jsonl"
        p.write_text(json.dumps({"type": "user", "sessionId": sid, "cwd": "/x",
                                  "message": {"content": "same first message here"}}))
        capture.run(str(p))

    fire("a", "abcdef12-aaaa-1111-2222-333344445555")   # base file
    fire("b", "abcdef12-bbbb-1111-2222-333344445555")   # sid8 collides -> suffixed -2 file
    assert len(raw_files()) == 2

    fire("b2", "abcdef12-bbbb-1111-2222-333344445555")  # session B re-fires (resumed)
    files = raw_files()
    assert len(files) == 2                               # still 2 — no -3 created
    assert any("-2.md" in f.name for f in files)


def test_slash_command_transcript_produces_capped_slug(tmp_path):
    # Real-world case from the release smoke: a REAL Claude Code transcript
    # whose first user message is a slash-command invocation wrapped in
    # XML-ish tags, e.g. <command-message>plugagent:setup</command-message>.
    # _slug()'s regex strips `<`, `>`, and `-`, so the tag text merges into
    # one giant space-free "word" — previously producing a 100+ char
    # filename slug. It must now be capped.
    long_command = (
        "<command-message>plugagent:setup is running</command-message>"
        "<command-name>plugagent:setup</command-name>"
        "<command-args></command-args>"
    )
    assert len(long_command) > 100
    p = tmp_path / "slash.jsonl"
    p.write_text(json.dumps({
        "type": "user",
        "sessionId": "deadbeef-1111-2222-3333-444455556666",
        "cwd": "/x",
        "message": {"role": "user", "content": long_command},
    }))
    capture.run(str(p))
    files = raw_files()
    assert len(files) == 1
    name = files[0].name
    assert name.endswith("-deadbeef.md")
    slug = name[11:-len("-deadbeef.md")]  # strip leading "YYYY-MM-DD-" and trailing "-deadbeef.md"
    assert len(slug) <= 48
    assert "session_id: deadbeef-1111-2222-3333-444455556666" in files[0].read_text()
