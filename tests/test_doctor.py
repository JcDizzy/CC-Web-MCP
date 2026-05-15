import json
import subprocess
import sys
from pathlib import Path

def load_doctor_module():
    import cc_web_mcp.doctor as module

    return module


def run_doctor(config_path: Path, claude_path: Path, settings_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "cc_web_mcp.doctor",
            "--config",
            str(config_path),
            "--claude-memory",
            str(claude_path),
            "--settings",
            str(settings_path),
            "--json",
            "--skip-network",
            "--skip-mcp-registration",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def run_doctor_text(config_path: Path, claude_path: Path, settings_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "cc_web_mcp.doctor",
            "--config",
            str(config_path),
            "--claude-memory",
            str(claude_path),
            "--settings",
            str(settings_path),
            "--skip-network",
            "--skip-mcp-registration",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_doctor_reports_missing_claude_instructions_and_hook(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["checks"]["config"]["ok"] is True
    assert report["checks"]["claude_instructions"]["ok"] is False
    assert report["checks"]["hook_guard"]["ok"] is False
    assert any("cc-web-mcp init" in item for item in report["recommendations"])


def test_doctor_text_output_keeps_english_prompts(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    result = run_doctor_text(config, claude_memory, settings)

    assert result.returncode == 1, result.stderr
    assert "cc-web-mcp doctor: Needs attention" in result.stdout
    assert "Recommendations:" in result.stdout
    assert "Run `cc-web-mcp init`" in result.stdout


def test_doctor_passes_when_local_files_are_configured(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 -m cc_web_mcp.hooks.guard"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": hook_command,
                                }
                            ],
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": hook_command,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["checks"]["claude_instructions"]["ok"] is True
    assert report["checks"]["hook_guard"]["ok"] is True


def test_build_report_checks_claude_mcp_registration(tmp_path, monkeypatch):
    doctor = load_doctor_module()
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 -m cc_web_mcp.hooks.guard"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": hook_command}]}],
                    "PreToolUse": [
                        {
                            "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        doctor,
        "_check_mcp_registration",
        lambda: ({"ok": False, "error": "No MCP server found with name: cc-web"}, ["Run `cc-web-mcp init` to register the cc-web MCP server."]),
    )

    report = doctor.build_report(config, claude_memory, settings, skip_network=True)

    assert report["ok"] is False
    assert report["checks"]["mcp_registration"]["ok"] is False
    assert any("register the cc-web MCP server" in item for item in report["recommendations"])


def test_mcp_registration_requires_connected_status(monkeypatch):
    doctor = load_doctor_module()

    class Result:
        returncode = 0
        stdout = """cc-web:
  Scope: User config (available in all your projects)
  Status: Failed to connect
  Type: stdio
  Command: C:\\Python311\\python.exe
  Args: -m cc_web_mcp
"""
        stderr = ""

    monkeypatch.setattr(doctor, "resolve_claude_command", lambda: "claude.cmd")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: Result())

    check, recommendations = doctor._check_mcp_registration()

    assert check["ok"] is False
    assert check["status"] == "Failed to connect"
    assert any("not connected" in item for item in recommendations)


def test_mcp_registration_accepts_connected_status(monkeypatch):
    doctor = load_doctor_module()

    class Result:
        returncode = 0
        stdout = """cc-web:
  Scope: User config (available in all your projects)
  Status: ✓ Connected
  Type: stdio
  Command: C:\\Python311\\python.exe
  Args: -m cc_web_mcp
"""
        stderr = ""

    monkeypatch.setattr(doctor, "resolve_claude_command", lambda: "claude.cmd")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: Result())

    check, recommendations = doctor._check_mcp_registration()

    assert check["ok"] is True
    assert check["status"] == "✓ Connected"
    assert recommendations == []


def test_doctor_json_output_is_ascii_safe_for_windows_console(tmp_path, monkeypatch, capsys):
    doctor = load_doctor_module()
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 -m cc_web_mcp.hooks.guard"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": hook_command}]}],
                    "PreToolUse": [
                        {
                            "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        doctor,
        "_check_mcp_registration",
        lambda: ({"ok": True, "stdout": "Status: ✓ Connected"}, []),
    )

    exit_code = doctor.main(
        [
            "--config",
            str(config),
            "--claude-memory",
            str(claude_memory),
            "--settings",
            str(settings),
            "--json",
            "--skip-network",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    output.encode("ascii")
    assert "\\u2713" in output


def test_doctor_fails_when_guard_is_only_registered_for_session_start(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "py -3.11 -m cc_web_mcp.hooks.guard",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["checks"]["hook_guard"]["ok"] is False
    assert report["checks"]["hook_guard"]["session_start"] is True
    assert report["checks"]["hook_guard"]["pre_tool_use"] is False


def test_doctor_accepts_console_script_hook_guard(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "C:/Users/xhh/AppData/Local/Microsoft/WinGet/Links/uvx.exe cc-web-mcp==0.1.2 hook-guard"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"matcher": "", "hooks": [{"type": "command", "command": hook_command}]}
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["checks"]["hook_guard"]["ok"] is True


def test_doctor_fails_when_pre_tool_matcher_does_not_cover_webfetch(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 -m cc_web_mcp.hooks.guard"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "^mcp__cc[-_]web__.*$",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_doctor(config, claude_memory, settings)

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["checks"]["hook_guard"]["ok"] is False
    assert report["checks"]["hook_guard"]["session_start"] is True
    assert report["checks"]["hook_guard"]["pre_tool_use"] is False
    assert "WebFetch" in report["checks"]["hook_guard"]["pre_tool_use_reason"]


def test_build_report_runs_network_check_when_not_skipped(tmp_path, monkeypatch):
    doctor = load_doctor_module()
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["duckduckgo", "bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 -m cc_web_mcp.hooks.guard"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"matcher": "", "hooks": [{"type": "command", "command": hook_command}]}
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_network_check(config_path=None):
        calls.append(config_path)
        return {
            "ok": True,
            "first_available_search_backend": "bing_cn",
            "search_backend_status": {"bing_cn": {"ok": True}},
        }, []

    def fail_if_mcp_registration_is_checked():
        raise AssertionError("test must not depend on local Claude MCP registration")

    monkeypatch.setattr(doctor, "_check_network", fake_network_check, raising=False)
    monkeypatch.setattr(doctor, "_check_mcp_registration", fail_if_mcp_registration_is_checked)

    report = doctor.build_report(config, claude_memory, settings, skip_network=False, skip_mcp_registration=True)

    assert calls == [config]
    assert report["ok"] is True
    assert report["checks"]["network"]["first_available_search_backend"] == "bing_cn"


def test_build_report_passes_explicit_config_to_network_check(tmp_path, monkeypatch):
    doctor = load_doctor_module()
    config = tmp_path / "custom-config.json"
    config.write_text('{"search_providers": ["bing_cn"]}', encoding="utf-8")
    claude_memory = tmp_path / "CLAUDE.md"
    claude_memory.write_text("Use cc-web MCP. Do not call WebSearch.", encoding="utf-8")
    settings = tmp_path / "settings.json"
    hook_command = "py -3.11 -m cc_web_mcp.hooks.guard"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": hook_command}]}],
                    "PreToolUse": [
                        {
                            "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [{"type": "command", "command": hook_command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_network_check(config_path):
        calls.append(config_path)
        return {"ok": True, "first_available_search_backend": "bing_cn"}, []

    monkeypatch.setattr(doctor, "_check_network", fake_network_check, raising=False)
    monkeypatch.setattr(doctor, "_check_mcp_registration", lambda: ({"ok": True}, []))

    report = doctor.build_report(config, claude_memory, settings, skip_network=False)

    assert calls == [config]
    assert report["ok"] is True
