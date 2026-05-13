from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_STATE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ClaudeCode" / "cc_web_model_state.json"
MODEL_ENV_NAMES = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "ANTHROPIC_BASE_URL",
)
CC_WEB_TOOL_PREFIXES = ("mcp__cc-web__", "mcp__cc_web__")


def load_allowed_patterns(path: Path) -> list[str]:
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            patterns = raw.get("allowed_model_patterns", ["deepseek"])
            if isinstance(patterns, list):
                cleaned = [str(item).strip().lower() for item in patterns if str(item).strip()]
                return cleaned or ["deepseek"]
    except Exception:
        pass
    return ["deepseek"]


def model_matches_patterns(model: str | None, patterns: list[str]) -> bool:
    normalized = (model or "").lower()
    return any(pattern in normalized for pattern in patterns)


def is_allowed_environment(patterns: list[str]) -> bool:
    return any(model_matches_patterns(os.environ.get(name), patterns) for name in MODEL_ENV_NAMES)


def load_state(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def record_session_start(payload: dict[str, Any], state_path: Path) -> None:
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return
    state = load_state(state_path)
    state[session_id] = {
        "model": str(payload.get("model") or ""),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cwd": str(payload.get("cwd") or ""),
    }
    save_state(state_path, state)


def guard_pre_tool_use(payload: dict[str, Any], state_path: Path, config_path: Path) -> int:
    tool_name = str(payload.get("tool_name") or "")
    if not tool_name.startswith(CC_WEB_TOOL_PREFIXES):
        return 0

    patterns = load_allowed_patterns(config_path)
    session_id = str(payload.get("session_id") or "")
    state = load_state(state_path)
    model = str(state.get(session_id, {}).get("model") or "")
    if model_matches_patterns(model, patterns) or is_allowed_environment(patterns):
        return 0

    reason = (
            "cc-web MCP 仅允许配置中匹配的模型使用。"
            f"当前允许模型关键词: {', '.join(patterns)}。"
            "默认场景是给 DeepSeek 等缺少官方搜索能力的模型补全网页访问。"
            "官方 Claude 请优先使用原生 WebSearch/WebFetch。"
    )
    response = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }
    print(json.dumps(response, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    state_path = Path(args.state)
    config_path = Path(args.config)

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return 0

    event_name = payload.get("hook_event_name")
    if event_name == "SessionStart":
        record_session_start(payload, state_path)
    elif event_name == "PreToolUse":
        return guard_pre_tool_use(payload, state_path, config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
