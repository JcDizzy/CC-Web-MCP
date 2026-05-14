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
    assert pre_tool["matcher"] == r"^(mcp__cc[-_]web__.*|WebFetch)$"
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
    assert r"^(mcp__cc[-_]web__.*|WebFetch)$" in matchers


def test_install_hook_preserves_unrelated_guard_with_same_matcher(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": r"^(mcp__cc[-_]web__.*|WebFetch)$",
                            "hooks": [{"type": "command", "command": "py -3.11 D:/other_project/hooks/guard.py"}],
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
    commands = [
        hook["command"]
        for entry in data["hooks"]["PreToolUse"]
        for hook in entry.get("hooks", [])
    ]
    assert "py -3.11 D:/other_project/hooks/guard.py" in commands
    assert any("cc_web_mcp/hooks/guard.py" in command.replace("\\", "/") for command in commands)


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
    assert data["hooks"]["PreToolUse"][0]["matcher"] == r"^(mcp__cc[-_]web__.*|WebFetch)$"
    command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command.startswith("E:/anaconda/python.exe ")
    assert "\\" not in command


def test_install_hook_quotes_paths_for_bash_compatible_execution(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    guard = tmp_path / "Project Dir" / "hooks" / "guard.py"

    result = run_install(
        settings,
        [
            "--python-command",
            r"E:\Program Files\Python311\python.exe",
            "--guard",
            str(guard),
        ],
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(settings.read_text(encoding="utf-8"))
    command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command.startswith("'E:/Program Files/Python311/python.exe' ")
    assert sh_single_quote(guard.resolve().as_posix()) in command
    assert "\\" not in command


def sh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
