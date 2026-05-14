import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL_HOOK = ROOT / "scripts" / "install_hook.py"


def run_install(settings_path: Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    args = [
        sys.executable,
        str(INSTALL_HOOK),
        "--settings",
        str(settings_path),
        "--python-command",
        "py -3.11",
    ]
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(args, text=True, capture_output=True, check=False)


def test_install_hook_creates_hooks_and_preserves_existing_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "env": {"ANTHROPIC_BASE_URL": "https://example.test"},
                "model": "opus",
                "enabledPlugins": {"superpowers@claude-plugins-official": True},
            }
        ),
        encoding="utf-8",
    )

    result = run_install(settings)

    assert result.returncode == 0, result.stderr
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://example.test"
    assert data["model"] == "opus"
    assert data["enabledPlugins"]["superpowers@claude-plugins-official"] is True
    assert data["hooks"]["SessionStart"][0]["matcher"] == ""
    pre_tool = data["hooks"]["PreToolUse"][0]
    assert pre_tool["matcher"] == r"^(mcp__cc[-_]web__.*|WebSearch|WebFetch)$"
    assert pre_tool["hooks"][0]["type"] == "command"
    assert "hooks/guard.py" in pre_tool["hooks"][0]["command"].replace("\\", "/")


def test_install_hook_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    first = run_install(settings)
    second = run_install(settings)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert len(data["hooks"]["SessionStart"]) == 1
    assert len(data["hooks"]["PreToolUse"]) == 1


def test_install_hook_preserves_unrelated_hooks(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "echo bash"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_install(settings)

    assert result.returncode == 0, result.stderr
    data = json.loads(settings.read_text(encoding="utf-8"))
    matchers = [item["matcher"] for item in data["hooks"]["PreToolUse"]]
    assert "Bash" in matchers
    assert r"^(mcp__cc[-_]web__.*|WebSearch|WebFetch)$" in matchers


def test_install_hook_replaces_existing_cc_web_hook_when_command_changes(tmp_path):
    settings = tmp_path / "settings.json"
    matcher = r"^(mcp__cc[-_]web__.*|WebSearch|WebFetch)$"
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
                                    "command": "py -3.11 E:/jc/cc_web_mcp/hooks/guard.py",
                                    "timeout": 5,
                                }
                            ],
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": matcher,
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "py -3.11 E:/jc/cc_web_mcp/hooks/guard.py",
                                    "timeout": 5,
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_install(settings, ["--python-command", "E:\\anaconda\\python.exe"])

    assert result.returncode == 0, result.stderr
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert len(data["hooks"]["SessionStart"]) == 1
    assert len(data["hooks"]["PreToolUse"]) == 1
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"].startswith("E:\\anaconda\\python.exe ")
