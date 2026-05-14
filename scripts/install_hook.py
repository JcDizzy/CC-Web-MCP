from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATCHER = r"^(mcp__cc[-_]web__.*|WebSearch|WebFetch)$"


def default_settings_path() -> Path:
    home = Path.home()
    return home / ".claude" / "settings.json"


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def save_settings(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def backup_settings(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.cc-web-backup.{timestamp}")
    backup_path.write_bytes(path.read_bytes())
    return backup_path


def build_hook_command(python_command: str, guard_path: Path) -> str:
    guard = guard_path.resolve().as_posix()
    return f"{python_command} {guard}"


def make_command_hook(command: str) -> dict[str, Any]:
    return {
        "type": "command",
        "command": command,
        "timeout": 5,
    }


def make_matcher(matcher: str, command: str) -> dict[str, Any]:
    return {
        "matcher": matcher,
        "hooks": [make_command_hook(command)],
    }


def hook_matches(entry: Any, matcher: str, command: str) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("matcher", "") != matcher:
        return False
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    return any(isinstance(hook, dict) and hook.get("command") == command for hook in hooks)


def is_cc_web_guard_command(command: Any) -> bool:
    if not isinstance(command, str):
        return False
    normalized = command.replace("\\", "/").lower()
    return "cc_web_mcp/hooks/guard.py" in normalized or "/hooks/guard.py" in normalized


def is_cc_web_guard_entry(entry: Any, matcher: str) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("matcher", "") != matcher:
        return False
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    return any(isinstance(hook, dict) and is_cc_web_guard_command(hook.get("command")) for hook in hooks)


def merge_hook(data: dict[str, Any], event_name: str, matcher: str, command: str) -> bool:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings.json field 'hooks' must be an object")

    entries = hooks.setdefault(event_name, [])
    if not isinstance(entries, list):
        raise ValueError(f"settings.json hooks.{event_name} must be an array")

    old_len = len(entries)
    entries[:] = [entry for entry in entries if not is_cc_web_guard_entry(entry, matcher)]
    removed_existing = len(entries) != old_len

    if not removed_existing and any(hook_matches(entry, matcher, command) for entry in entries):
        return False

    entries.append(make_matcher(matcher, command))
    return True


def install_hooks(settings_path: Path, python_command: str, guard_path: Path) -> tuple[bool, Path | None]:
    data = load_settings(settings_path)
    command = build_hook_command(python_command, guard_path)
    changed = False
    changed |= merge_hook(data, "SessionStart", "", command)
    changed |= merge_hook(data, "PreToolUse", DEFAULT_MATCHER, command)

    backup_path = None
    if changed:
        backup_path = backup_settings(settings_path)
        save_settings(settings_path, data)
    return changed, backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Install cc-web Claude Code hooks.")
    parser.add_argument("--settings", default=str(default_settings_path()))
    parser.add_argument("--python-command", default="py -3.11")
    parser.add_argument("--guard", default=str(ROOT / "hooks" / "guard.py"))
    args = parser.parse_args()

    settings_path = Path(os.path.expanduser(args.settings))
    guard_path = Path(os.path.expanduser(args.guard))
    changed, backup_path = install_hooks(settings_path, args.python_command, guard_path)

    if changed:
        print(f"已更新: {settings_path}")
        if backup_path is not None:
            print(f"备份: {backup_path}")
    else:
        print(f"无需更新: {settings_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
