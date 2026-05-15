from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from cc_web_mcp.config import resolve_config_path
from cc_web_mcp.install import is_cc_web_guard_command, resolve_claude_command
from cc_web_mcp.web import check_health


def default_config_path() -> Path:
    return resolve_config_path()


def default_claude_memory_path() -> Path:
    return Path.home() / ".claude" / "CLAUDE.md"


def default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "file missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, "JSON root is not an object"
    return data, ""


def _check_config(path: Path) -> tuple[dict[str, Any], list[str]]:
    recommendations: list[str] = []
    data, error = _read_json(path)
    if data is None:
        recommendations.append("Run `cc-web-mcp init` to create the cc-web configuration file.")
        return {"ok": False, "path": str(path), "error": error}, recommendations

    providers = data.get("search_providers") or [data.get("search_provider") or "duckduckgo"]
    if not isinstance(providers, list):
        providers = [str(providers)]
    if not providers:
        recommendations.append("Set search_providers, for example ['duckduckgo', 'bing_cn'].")
    return {
        "ok": True,
        "path": str(path),
        "search_providers": providers,
        "allowed_model_patterns": data.get("allowed_model_patterns", ["deepseek"]),
    }, recommendations


def _check_claude_instructions(path: Path) -> tuple[dict[str, Any], list[str]]:
    recommendations: list[str] = []
    if not path.exists():
        recommendations.append("Run `cc-web-mcp init` to add cc-web routing hints to CLAUDE.md.")
        return {"ok": False, "path": str(path), "error": "file missing"}, recommendations

    text = path.read_text(encoding="utf-8-sig", errors="replace")
    ok = "cc-web" in text.lower() and "WebSearch" in text
    if not ok:
        recommendations.append("Run `cc-web-mcp init --force` to refresh cc-web routing hints.")
    return {"ok": ok, "path": str(path)}, recommendations


def _hook_command_mentions_guard(command: Any) -> bool:
    return is_cc_web_guard_command(command)


def _iter_hook_entries(settings: dict[str, Any], event_name: str) -> list[dict[str, Any]]:
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return []
    entries = hooks.get(event_name, [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _entry_has_guard_command(entry: dict[str, Any]) -> bool:
    if _hook_command_mentions_guard(entry.get("command")):
        return True
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    return any(isinstance(hook, dict) and _hook_command_mentions_guard(hook.get("command")) for hook in hooks)


def _matcher_covers_samples(matcher: str | None, samples: tuple[str, ...]) -> tuple[bool, str]:
    if matcher in (None, ""):
        return True, ""
    try:
        pattern = re.compile(str(matcher))
    except re.error as exc:
        return False, f"PreToolUse matcher is not a valid regular expression: {exc}"
    missing = [sample for sample in samples if not pattern.search(sample)]
    if missing:
        return False, "PreToolUse matcher does not cover: " + ", ".join(missing)
    return True, ""


def _check_hook_event(settings: dict[str, Any], event_name: str, required_samples: tuple[str, ...] = ()) -> tuple[bool, str]:
    entries = _iter_hook_entries(settings, event_name)
    if not entries:
        return False, f"{event_name} hook is missing"
    guard_entries = [entry for entry in entries if _entry_has_guard_command(entry)]
    if not guard_entries:
        return False, f"{event_name} hook does not run cc_web_mcp.hooks.guard"
    if not required_samples:
        return True, ""
    reasons: list[str] = []
    for entry in guard_entries:
        ok, reason = _matcher_covers_samples(entry.get("matcher"), required_samples)
        if ok:
            return True, ""
        reasons.append(reason)
    return False, reasons[0] if reasons else f"{event_name} matcher is incomplete"


def _check_hook_guard(path: Path) -> tuple[dict[str, Any], list[str]]:
    recommendations: list[str] = []
    data, error = _read_json(path)
    if data is None:
        recommendations.append("Run `cc-web-mcp init` to add the cc-web hook guard.")
        return {"ok": False, "path": str(path), "error": error}, recommendations

    session_ok, session_reason = _check_hook_event(data, "SessionStart")
    pre_tool_ok, pre_tool_reason = _check_hook_event(
        data,
        "PreToolUse",
        (
            "mcp__cc-web__fetch_url",
            "mcp__cc_web__fetch_url",
            "WebFetch",
        ),
    )
    ok = session_ok and pre_tool_ok
    if not ok:
        recommendations.append("Run `cc-web-mcp init --force` to refresh the cc-web hook guard.")
    return {
        "ok": ok,
        "path": str(path),
        "session_start": session_ok,
        "pre_tool_use": pre_tool_ok,
        "session_start_reason": session_reason,
        "pre_tool_use_reason": pre_tool_reason,
    }, recommendations


def _check_network(config_path: Path | None = None) -> tuple[dict[str, Any], list[str]]:
    recommendations: list[str] = []
    try:
        health = asyncio.run(check_health(config_path))
    except Exception as exc:
        recommendations.append("Run `cc-web-mcp doctor --skip-network` if live network access is unavailable.")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, recommendations

    first_backend = health.get("first_available_search_backend")
    ok = bool(first_backend)
    if not ok:
        recommendations.append("No search backend is reachable. Check network access or configure search_providers.")
    return {
        "ok": ok,
        "first_available_search_backend": first_backend,
        "search_backend_status": health.get("search_backend_status", {}),
        "network": health.get("network", {}),
        "health_ok": health.get("ok"),
    }, recommendations


def _check_mcp_registration() -> tuple[dict[str, Any], list[str]]:
    recommendations: list[str] = []
    command = [resolve_claude_command(), "mcp", "get", "cc-web"]
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        recommendations.append("Install Claude Code CLI or ensure `claude` is available, then run `cc-web-mcp init`.")
        return {
            "ok": False,
            "command": " ".join(command),
            "error": f"{type(exc).__name__}: {exc}",
        }, recommendations

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    status_match = re.search(r"(?im)^\s*Status:\s*(.+?)\s*$", stdout)
    status = status_match.group(1).strip() if status_match else ""
    ok = result.returncode == 0 and "cc-web" in stdout.lower() and "connected" in status.lower()
    if not ok:
        if result.returncode == 0 and "cc-web" in stdout.lower():
            recommendations.append("The cc-web MCP server is registered but not connected. Run `cc-web-mcp init --force` and check `claude mcp get cc-web`.")
        else:
            recommendations.append("Run `cc-web-mcp init` to register the cc-web MCP server.")
    return {
        "ok": ok,
        "command": " ".join(command),
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
    }, recommendations


def build_report(
    config_path: Path,
    claude_memory_path: Path,
    settings_path: Path,
    skip_network: bool,
    skip_mcp_registration: bool = False,
) -> dict[str, Any]:
    recommendations: list[str] = []
    config_check, config_recs = _check_config(config_path)
    instructions_check, instructions_recs = _check_claude_instructions(claude_memory_path)
    hook_check, hook_recs = _check_hook_guard(settings_path)
    if skip_mcp_registration:
        mcp_check, mcp_recs = {"ok": None, "skipped": True}, []
    else:
        mcp_check, mcp_recs = _check_mcp_registration()
    network_check: dict[str, Any]
    network_recs: list[str]
    if skip_network:
        network_check, network_recs = {"ok": None, "skipped": True}, []
    else:
        network_check, network_recs = _check_network(config_path)
    recommendations.extend(config_recs)
    recommendations.extend(instructions_recs)
    recommendations.extend(hook_recs)
    recommendations.extend(mcp_recs)
    recommendations.extend(network_recs)

    package_root = Path(__file__).resolve().parent
    checks: dict[str, Any] = {
        "python": {"ok": True, "executable": sys.executable, "version": sys.version.split()[0]},
        "project": {"ok": (package_root / "server.py").exists() or (package_root / "web.py").exists(), "path": str(package_root)},
        "config": config_check,
        "mcp_registration": mcp_check,
        "claude_instructions": instructions_check,
        "hook_guard": hook_check,
        "network": network_check,
    }

    ok = all(check.get("ok") is not False for check in checks.values())
    return {"ok": ok, "checks": checks, "recommendations": recommendations}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose local cc-web MCP setup.")
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--claude-memory", default=str(default_claude_memory_path()))
    parser.add_argument("--settings", default=str(default_settings_path()))
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--skip-network", action="store_true", help="Skip live network checks.")
    parser.add_argument("--skip-mcp-registration", action="store_true", help="Skip Claude Code MCP registration checks.")
    args = parser.parse_args(argv)

    report = build_report(
        Path(os.path.expanduser(args.config)),
        Path(os.path.expanduser(args.claude_memory)),
        Path(os.path.expanduser(args.settings)),
        skip_network=args.skip_network,
        skip_mcp_registration=args.skip_mcp_registration,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        status = "OK" if report["ok"] else "Needs attention"
        print(f"cc-web-mcp doctor: {status}")
        for name, check in report["checks"].items():
            print(f"- {name}: {check.get('ok')}")
        if report["recommendations"]:
            print("Recommendations:")
            for item in report["recommendations"]:
                print(f"- {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
