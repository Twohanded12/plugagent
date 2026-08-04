import json
import subprocess
from pathlib import Path

SHIM = Path(__file__).parent.parent / "hooks" / "stop_capture.sh"
FIX = Path(__file__).parent / "fixtures"


def run_shim(payload: str, tmp_path, extra_env=None, path_override=None):
    import os
    env = dict(os.environ)
    env["PLUGAGENT_HOME"] = str(tmp_path / "home")
    env["CLAUDE_PLUGIN_ROOT"] = str(SHIM.parent.parent)
    if path_override is not None:
        env["PATH"] = path_override
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["/bin/sh", str(SHIM)], input=payload, text=True,
                          capture_output=True, env=env)


def test_happy_path_exits_zero_and_captures(tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps(
        {"vault": str(tmp_path / "vault"), "capture": "on"}))
    payload = json.dumps({"transcript_path": str(FIX / "transcript_ok.jsonl")})
    r = run_shim(payload, tmp_path)
    assert r.returncode == 0
    assert list((tmp_path / "vault" / "raw" / "sessions").glob("*.md"))


def test_empty_payload_exits_zero(tmp_path):
    assert run_shim("", tmp_path).returncode == 0


def test_garbage_payload_exits_zero(tmp_path):
    assert run_shim("not json {{{", tmp_path).returncode == 0


def test_no_python3_exits_zero_and_logs(tmp_path):
    # A bare bogus PATH would also remove cat/sed/head, making the shim bail
    # at the transcript guard before reaching the python3 check. Build a PATH
    # that has every tool the shim needs EXCEPT python3.
    import shutil
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("cat", "sed", "head", "mkdir", "date"):
        src = shutil.which(tool)
        assert src, f"{tool} missing on test host"
        (bin_dir / tool).symlink_to(src)
    payload = json.dumps({"transcript_path": "/tmp/x.jsonl"})
    r = run_shim(payload, tmp_path, path_override=str(bin_dir))
    assert r.returncode == 0
    errors = tmp_path / "home" / "state" / "errors.log"
    assert errors.exists() and "python3 not found" in errors.read_text()


def test_missing_transcript_file_exits_zero(tmp_path):
    (tmp_path / "home").mkdir(parents=True)
    (tmp_path / "home" / "config.json").write_text(json.dumps(
        {"vault": str(tmp_path / "vault")}))
    payload = json.dumps({"transcript_path": "/nonexistent/t.jsonl"})
    assert run_shim(payload, tmp_path).returncode == 0


def test_cli_crash_exits_zero_and_logs(tmp_path):
    plugin_root = tmp_path / "plugin_root"
    pa_dir = plugin_root / "scripts" / "pa"
    pa_dir.mkdir(parents=True)
    (pa_dir / "__init__.py").write_text("")
    (pa_dir / "__main__.py").write_text("import sys; sys.exit(3)")
    payload = json.dumps({"transcript_path": str(FIX / "transcript_ok.jsonl")})
    r = run_shim(payload, tmp_path, extra_env={"CLAUDE_PLUGIN_ROOT": str(plugin_root)})
    assert r.returncode == 0
    errors = tmp_path / "home" / "state" / "errors.log"
    assert errors.exists() and "python invocation failed" in errors.read_text()
