from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from cc_web_mcp import __version__
from cc_web_mcp.config import ensure_user_config, resolve_config_path


START_MARKER = "<!-- cc-web-mcp:start -->"
END_MARKER = "<!-- cc-web-mcp:end -->"
DEFAULT_MATCHER = r"^WebFetch$"
LEGACY_MATCHERS = (
    r"^(mcp__cc[-_]web__.*|WebFetch)$",
    r"^(mcp__cc[-_]web__.*|WebSearch|WebFetch)$",
)


def default_memory_path() -> Path:
    return Path.home() / ".claude" / "CLAUDE.md"


def default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


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


def _shell_path(value: str | Path) -> str:
    return str(value).replace("\\", "/")


def _quote_shell(value: str) -> str:
    normalized = _shell_path(value).strip()
    if not normalized:
        return '""'
    if os.name == "nt":
        if re.search(r'[\s\[\]()"&|<>^]', normalized):
            return '"' + normalized.replace('"', r'\"') + '"'
        return normalized
    if _is_windows_executable_path(normalized):
        return f'"{normalized}"'
    return shlex.quote(normalized)


def _is_windows_executable_path(command: str) -> bool:
    return bool(command and len(command) >= 3 and command[1] == ":" and command[2] in "\\/")


def _format_python_command(python_command: str) -> str:
    command = (python_command or "").strip() or "py -3.11"
    if _is_windows_executable_path(command):
        return _quote_shell(command)
    return command.replace("\\", "/")


def default_python_command() -> str:
    return sys.executable


def resolve_uvx_command() -> str:
    if os.name == "nt":
        return shutil.which("uvx.exe") or shutil.which("uvx") or "uvx"
    return shutil.which("uvx") or "uvx"


def build_uvx_tool_command(uvx_package: str = "cc-web-mcp") -> list[str]:
    package = (uvx_package or "").strip() or "cc-web-mcp"
    return [resolve_uvx_command(), package]


def build_uvx_command_from_package(uvx_package: str = "cc-web-mcp") -> list[str]:
    package = (uvx_package or "").strip() or "cc-web-mcp"
    return [resolve_uvx_command(), "--from", package, "cc-web-mcp"]


def resolve_uvx_package(uvx_package: str = "cc-web-mcp", with_pdf: bool = False) -> str:
    package = (uvx_package or "").strip() or "cc-web-mcp"
    if with_pdf and package == "cc-web-mcp":
        return f"cc-web-mcp[pdf]@{__version__}"
    if package == "cc-web-mcp":
        return f"cc-web-mcp@{__version__}"
    return package


def build_guard_command(python_command: str | None = None) -> str:
    python_command = python_command or default_python_command()
    return f"{_format_python_command(python_command)} -m cc_web_mcp.hooks.guard"


def build_uvx_guard_command_parts(uvx_package: str = "cc-web-mcp") -> list[str]:
    return [*build_uvx_command_from_package(uvx_package), "hook-guard"]


def build_uvx_guard_command(uvx_package: str = "cc-web-mcp") -> str:
    command = build_uvx_guard_command_parts(uvx_package)
    return " ".join([_format_python_command(command[0]), *(_quote_shell(part) for part in command[1:])])


def build_hook_command(
    runner: str = "python",
    python_command: str | None = None,
    uvx_package: str = "cc-web-mcp",
) -> str | list[str]:
    if runner == "uvx":
        return build_uvx_guard_command_parts(uvx_package)
    if runner != "python":
        raise ValueError("runner must be 'python' or 'uvx'")
    return build_guard_command(python_command)


def make_command_hook(command: str | list[str], runner: str = "python") -> dict[str, Any]:
    hook = {
        "type": "command",
        "timeout": 5,
    }
    if isinstance(command, list):
        if not command:
            raise ValueError("hook command must not be empty")
        hook["command"] = command[0]
        if len(command) > 1:
            hook["args"] = command[1:]
        return hook
    hook["command"] = command
    return hook


def make_matcher(matcher: str, command: str | list[str], runner: str = "python") -> dict[str, Any]:
    return {
        "matcher": matcher,
        "hooks": [make_command_hook(command, runner=runner)],
    }


def _hook_command_matches(hook: dict[str, Any], command: str | list[str]) -> bool:
    if isinstance(command, list):
        if not command:
            return False
        return hook.get("command") == command[0] and list(hook.get("args") or []) == command[1:]
    return hook.get("command") == command and not hook.get("args")


def hook_matches(entry: Any, matcher: str, command: str | list[str]) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("matcher", "") != matcher:
        return False
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    return any(isinstance(hook, dict) and _hook_command_matches(hook, command) for hook in hooks)


def is_cc_web_guard_command(command: Any, args: Any | None = None) -> bool:
    if not isinstance(command, str):
        return False
    normalized_args = [str(arg).replace("\\", "/").lower() for arg in args] if isinstance(args, list) else []
    normalized = " ".join([command.replace("\\", "/").lower(), *normalized_args]).strip()
    if (
        "cc_web_mcp.hooks.guard" in normalized
        or "cc-web-mcp.hooks.guard" in normalized
        or "cc_web_mcp/hooks/guard.py" in normalized
        or "cc-web-mcp/hooks/guard.py" in normalized
    ):
        return True

    if normalized_args:
        tokens = [command.replace("\\", "/").lower(), *normalized_args]
    else:
        try:
            tokens = shlex.split(normalized)
        except ValueError:
            tokens = normalized.split()
    if not tokens or "hook-guard" not in tokens:
        return False

    hook_index = tokens.index("hook-guard")
    if any(_is_cc_web_console_token(token) for token in tokens[:hook_index]):
        return True
    return any(
        token == "-m" and index + 1 < hook_index and tokens[index + 1] in {"cc_web_mcp", "cc-web-mcp"}
        for index, token in enumerate(tokens[:hook_index])
    )


def _is_cc_web_console_token(token: str) -> bool:
    basename = token.strip("\"'").rsplit("/", 1)[-1]
    if basename in {"cc-web-mcp", "cc-web-mcp.exe"}:
        return True
    return (
        basename.startswith("cc-web-mcp[")
        or basename.startswith("cc-web-mcp==")
        or basename.startswith("cc-web-mcp@")
    )


def is_cc_web_guard_entry(entry: Any, matcher: str) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("matcher", "") not in {matcher, *LEGACY_MATCHERS}:
        return False
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(hook, dict) and is_cc_web_guard_command(hook.get("command"), hook.get("args"))
        for hook in hooks
    )


def merge_hook(
    data: dict[str, Any],
    event_name: str,
    matcher: str,
    command: str | list[str],
    force: bool = False,
    runner: str = "python",
) -> bool:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings.json field 'hooks' must be an object")

    entries = hooks.setdefault(event_name, [])
    if not isinstance(entries, list):
        raise ValueError(f"settings.json hooks.{event_name} must be an array")

    if not force and any(hook_matches(entry, matcher, command) for entry in entries):
        return False

    old_len = len(entries)
    entries[:] = [entry for entry in entries if not is_cc_web_guard_entry(entry, matcher)]
    removed_existing = len(entries) != old_len

    if not removed_existing and any(hook_matches(entry, matcher, command) for entry in entries):
        return False

    entries.append(make_matcher(matcher, command, runner=runner))
    return True


def install_hooks(
    settings_path: Path,
    python_command: str | None,
    force: bool = False,
    runner: str = "python",
    uvx_package: str = "cc-web-mcp",
) -> tuple[bool, Path | None]:
    data = load_settings(settings_path)
    command = build_hook_command(runner=runner, python_command=python_command, uvx_package=uvx_package)
    changed = False
    changed |= merge_hook(data, "SessionStart", "", command, force=force, runner=runner)
    changed |= merge_hook(data, "PreToolUse", DEFAULT_MATCHER, command, force=force, runner=runner)

    backup_path = None
    if changed:
        backup_path = backup_settings(settings_path)
        save_settings(settings_path, data)
    return changed, backup_path


def replace_block(text: str) -> tuple[str, bool]:
    instruction_block = f"""{START_MARKER}
## cc-web MCP routing for third-party models

When the current Claude Code model is DeepSeek, Qwen, Kimi, or another third-party model that lacks working native web tools:

- Do not call WebSearch. Some third-party Anthropic-compatible APIs reject WebSearch before Claude Code local hooks can run.
- For web research or current information, call `mcp__cc-web__research_brief` first.
- If raw search results are needed, call `mcp__cc-web__web_search`.
- If a specific URL must be read, call `mcp__cc-web__fetch_url`.
- Official Claude models should continue to prefer native `WebSearch` / `WebFetch`.
{END_MARKER}"""

    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start != -1 and end != -1 and end >= start:
        end += len(END_MARKER)
        new_text = text[:start].rstrip() + "\n\n" + instruction_block + "\n\n" + text[end:].lstrip()
        return new_text.rstrip() + "\n", new_text != text

    if text.strip():
        return text.rstrip() + "\n\n" + instruction_block + "\n", True
    return instruction_block + "\n", True


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.cc-web-backup.{timestamp}")
    backup_path.write_bytes(path.read_bytes())
    return backup_path


def install_instructions(memory_path: Path) -> tuple[bool, Path | None]:
    old_text = memory_path.read_text(encoding="utf-8-sig") if memory_path.exists() else ""
    new_text, changed = replace_block(old_text)
    backup_path = None
    if changed:
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = backup_file(memory_path)
        memory_path.write_text(new_text, encoding="utf-8")
    return changed, backup_path


def build_mcp_server_command() -> list[str]:
    return [sys.executable, "-m", "cc_web_mcp"]


def build_server_command(runner: str = "python", uvx_package: str = "cc-web-mcp") -> list[str]:
    if runner == "uvx":
        return build_uvx_tool_command(uvx_package)
    if runner != "python":
        raise ValueError("runner must be 'python' or 'uvx'")
    return build_mcp_server_command()


def resolve_claude_command() -> str:
    if os.name == "nt":
        return shutil.which("claude.cmd") or shutil.which("claude.exe") or shutil.which("claude") or "claude.cmd"
    return shutil.which("claude") or "claude"


def build_claude_mcp_add_command(
    server_command: list[str] | None = None,
    transport_name: str = "stdio",
    scope: str = "user",
    server_name: str = "cc-web",
    runner: str = "python",
    uvx_package: str = "cc-web-mcp",
) -> list[str]:
    command = list(server_command or build_server_command(runner=runner, uvx_package=uvx_package))
    return [
        resolve_claude_command(),
        "mcp",
        "add",
        "--scope",
        scope,
        "--transport",
        transport_name,
        server_name,
        "--",
        *command,
    ]


def build_claude_mcp_remove_command(scope: str = "user", server_name: str = "cc-web") -> list[str]:
    return [
        resolve_claude_command(),
        "mcp",
        "remove",
        server_name,
        "--scope",
        scope,
    ]


def is_missing_mcp_server_message(output: str) -> bool:
    normalized = (output or "").lower()
    return (
        "not found" in normalized
        or "does not exist" in normalized
        or re.search(r"\bno\b.*\bserver\b.*\bfound\b", normalized, flags=re.DOTALL) is not None
    )


def build_init_summary(
    config_path: Path | None = None,
    memory_path: Path | None = None,
    settings_path: Path | None = None,
    python_command: str | None = None,
    force: bool = False,
    skip_hooks: bool = False,
    skip_instructions: bool = False,
    skip_mcp: bool = False,
    dry_run: bool = False,
    scope: str = "user",
    runner: str = "python",
    uvx_package: str = "cc-web-mcp",
    with_pdf: bool = False,
) -> dict[str, Any]:
    resolved_config = resolve_config_path(config_path)
    config_created = not resolved_config.exists()
    resolved_uvx_package = resolve_uvx_package(uvx_package, with_pdf=with_pdf)

    actions: list[dict[str, Any]] = []
    if not skip_instructions:
        actions.append({"kind": "claude_memory", "path": str(memory_path or default_memory_path())})
    if not skip_hooks:
        actions.append({"kind": "claude_settings", "path": str(settings_path or default_settings_path())})
    if not skip_mcp:
        actions.append(
            {
                "kind": "claude_mcp_add",
                "command": build_claude_mcp_add_command(scope=scope, runner=runner, uvx_package=resolved_uvx_package),
            }
        )

    return {
        "config_path": str(resolved_config),
        "config_created": config_created,
        "actions": actions,
        "dry_run": dry_run,
        "force": force,
        "runner": runner,
        "uvx_package": resolved_uvx_package,
        "with_pdf": with_pdf,
        "mcp_registered": None,
        "mcp_registration_command": " ".join(build_claude_mcp_add_command(scope=scope, runner=runner, uvx_package=resolved_uvx_package)),
    }


def register_claude_mcp(
    scope: str = "user",
    runner: str = "python",
    uvx_package: str = "cc-web-mcp",
    force: bool = False,
) -> tuple[bool, list[str], str, str]:
    command = build_claude_mcp_add_command(scope=scope, runner=runner, uvx_package=uvx_package)
    try:
        if force:
            remove_command = build_claude_mcp_remove_command(scope=scope)
            remove_result = subprocess.run(remove_command, text=True, capture_output=True, check=False)
            remove_output = f"{remove_result.stdout}\n{remove_result.stderr}".lower()
            if remove_result.returncode != 0 and not is_missing_mcp_server_message(remove_output):
                return False, remove_command, remove_result.stdout, remove_result.stderr
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as exc:
        return False, command, "", f"{type(exc).__name__}: {exc}"
    return result.returncode == 0, command, result.stdout, result.stderr


def run_init(
    config_path: Path | None = None,
    memory_path: Path | None = None,
    settings_path: Path | None = None,
    python_command: str | None = None,
    force: bool = False,
    skip_hooks: bool = False,
    skip_instructions: bool = False,
    skip_mcp: bool = False,
    dry_run: bool = False,
    scope: str = "user",
    runner: str = "python",
    uvx_package: str = "cc-web-mcp",
    with_pdf: bool = False,
) -> dict[str, Any]:
    summary = build_init_summary(
        config_path=config_path,
        memory_path=memory_path,
        settings_path=settings_path,
        python_command=python_command,
        force=force,
        skip_hooks=skip_hooks,
        skip_instructions=skip_instructions,
        skip_mcp=skip_mcp,
        dry_run=dry_run,
        scope=scope,
        runner=runner,
        uvx_package=uvx_package,
        with_pdf=with_pdf,
    )
    resolved_uvx_package = summary["uvx_package"]

    memory_target = memory_path or default_memory_path()
    settings_target = settings_path or default_settings_path()

    if dry_run:
        return summary

    _, config_created = ensure_user_config(config_path)
    summary["config_path"] = str(resolve_config_path(config_path))
    summary["config_created"] = config_created

    if not skip_instructions:
        changed, backup_path = install_instructions(memory_target)
        summary["memory_changed"] = changed
        summary["memory_backup"] = str(backup_path) if backup_path else None

    if not skip_hooks:
        changed, backup_path = install_hooks(
            settings_target,
            python_command,
            force=force,
            runner=runner,
            uvx_package=resolved_uvx_package,
        )
        summary["hooks_changed"] = changed
        summary["hooks_backup"] = str(backup_path) if backup_path else None

    if not skip_mcp:
        registered, command, stdout, stderr = register_claude_mcp(
            scope=scope,
            runner=runner,
            uvx_package=resolved_uvx_package,
            force=force,
        )
        summary["mcp_registered"] = registered
        summary["mcp_registration_command"] = " ".join(command)
        summary["mcp_stdout"] = stdout
        summary["mcp_stderr"] = stderr
        if not registered:
            raise RuntimeError(
                "claude mcp add failed. "
                f"Command: {' '.join(command)}\n"
                f"stdout: {stdout}\n"
                f"stderr: {stderr}"
            )
    return summary


def default_config_path() -> Path:
    return resolve_config_path()


def _print_summary(summary: dict[str, Any]) -> None:
    dry_run = bool(summary.get("dry_run"))
    if dry_run:
        print("Dry run: no files were changed.")
    print(f"Config: {summary['config_path']}")
    if summary.get("config_created"):
        print("Config would be initialized." if dry_run else "Config initialized.")
    if summary.get("memory_changed"):
        print(f"Updated: {summary.get('memory_backup') or 'CLAUDE.md'}")
    if summary.get("hooks_changed"):
        print(f"Updated: {summary.get('hooks_backup') or 'settings.json'}")
    if dry_run:
        print("MCP registration would run.")
    elif summary.get("mcp_registered") is True:
        print("MCP registered: cc-web")
    elif summary.get("mcp_registered") is None:
        print("MCP registration skipped.")
    for action in summary.get("actions", []):
        if action["kind"] == "claude_mcp_add":
            print("MCP registration command:")
            print(" ".join(action["command"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install cc-web Claude Code integration.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--memory", "--claude-memory", dest="memory", default=str(default_memory_path()))
    parser.add_argument("--settings", default=str(default_settings_path()))
    parser.add_argument(
        "--python-command",
        default=None,
        help="Python command used by the Claude Code hook guard. Defaults to the current interpreter.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-hooks", action="store_true")
    parser.add_argument("--skip-instructions", action="store_true")
    parser.add_argument("--skip-mcp", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scope", default="user")
    parser.add_argument("--runner", choices=("python", "uvx"), default="python")
    parser.add_argument("--uvx-package", default="cc-web-mcp")
    parser.add_argument("--with-pdf", action="store_true", help="When using --runner uvx, register cc-web-mcp with the pdf extra.")
    args = parser.parse_args(argv)

    try:
        summary = run_init(
            config_path=Path(os.path.expanduser(args.config)) if args.config else None,
            memory_path=Path(os.path.expanduser(args.memory)) if args.memory else None,
            settings_path=Path(os.path.expanduser(args.settings)) if args.settings else None,
            python_command=args.python_command,
            force=args.force,
            skip_hooks=args.skip_hooks,
            skip_instructions=args.skip_instructions,
            skip_mcp=args.skip_mcp,
            dry_run=args.dry_run,
            scope=args.scope,
            runner=args.runner,
            uvx_package=args.uvx_package,
            with_pdf=args.with_pdf,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
