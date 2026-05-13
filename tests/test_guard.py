import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "hooks" / "guard.py"


def run_guard(
    state_path: Path,
    payload: dict,
    env: dict | None = None,
    config_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(GUARD), "--state", str(state_path)]
    if config_path is not None:
        args.extend(["--config", str(config_path)])
    return subprocess.run(
        args,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_session_start_records_model(tmp_path):
    state = tmp_path / "state.json"
    result = run_guard(
        state,
        {
            "hook_event_name": "SessionStart",
            "session_id": "s1",
            "model": "deepseek-v4-flash",
        },
    )

    assert result.returncode == 0
    assert json.loads(state.read_text(encoding="utf-8"))["s1"]["model"] == "deepseek-v4-flash"


def test_pre_tool_use_blocks_non_deepseek_model(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__web_search",
        },
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    output = response["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    assert "DeepSeek" in output["permissionDecisionReason"]


def test_pre_tool_use_allows_deepseek_model(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "deepseek-v4-pro[1m]"}}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__fetch_url",
        },
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_blocks_hyphenated_cc_web_tool_name(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc-web__web_search",
        },
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_tool_use_allows_deepseek_environment_alias(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"s1": {"model": "sonnet"}}), encoding="utf-8")
    env = {**os.environ, "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]"}

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__web_search",
        },
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_allows_configured_non_deepseek_model(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "qwen3-coder"}}), encoding="utf-8")
    config.write_text(json.dumps({"allowed_model_patterns": ["deepseek", "qwen"]}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__web_search",
        },
        config_path=config,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_pre_tool_use_block_message_mentions_configured_model_patterns(tmp_path):
    state = tmp_path / "state.json"
    config = tmp_path / "config.json"
    state.write_text(json.dumps({"s1": {"model": "claude-opus-4-6"}}), encoding="utf-8")
    config.write_text(json.dumps({"allowed_model_patterns": ["deepseek", "qwen"]}), encoding="utf-8")

    result = run_guard(
        state,
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "mcp__cc_web__fetch_url",
        },
        config_path=config,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    output = response["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "deepseek, qwen" in output["permissionDecisionReason"]
