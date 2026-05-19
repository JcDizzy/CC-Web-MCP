from __future__ import annotations

import json

from cc_web_mcp.config import default_config_dict, ensure_user_config, resolve_config_path


def test_resolve_config_path_uses_explicit_path(tmp_path):
    config = tmp_path / "explicit.json"

    assert resolve_config_path(config) == config


def test_resolve_config_path_uses_environment(monkeypatch, tmp_path):
    config = tmp_path / "env.json"
    monkeypatch.setenv("CC_WEB_MCP_CONFIG", str(config))

    assert resolve_config_path() == config


def test_ensure_user_config_creates_default_json(tmp_path):
    config = tmp_path / "config.json"

    path, created = ensure_user_config(config)

    assert path == config
    assert created is True
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data == default_config_dict()


def test_ensure_user_config_does_not_overwrite_existing_json(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"search_providers": ["bing_cn"]}', encoding="utf-8")

    path, created = ensure_user_config(config)

    assert path == config
    assert created is False
    assert json.loads(config.read_text(encoding="utf-8")) == {"search_providers": ["bing_cn"]}
