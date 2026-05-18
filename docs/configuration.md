# 配置说明

配置文件默认位于用户配置目录，不再依赖仓库根目录的 `config.json`。

- Windows：`%APPDATA%\cc-web-mcp\config.json`
- macOS/Linux：`~/.config/cc-web-mcp/config.json`

查看当前路径：

```powershell
cc-web-mcp config path
```

首次创建配置：

```powershell
cc-web-mcp config init
```

也可以通过 `CC_WEB_MCP_CONFIG` 指向自定义配置文件。

```json
{
  "allowed_model_patterns": ["deepseek"],
  "search_providers": ["duckduckgo", "bing_cn"],
  "allow_fetch_url_for_claude": false,
  "block_native_web_for_allowed_models": true,
  "searxng_base_url": "",
  "prefer_technical_sources": true,
  "default_fetch_chars": 10000,
  "max_fetch_chars": 60000,
  "max_search_results": 10,
  "max_brief_sources": 3,
  "brief_chars_per_source": 2500,
  "brief_concurrency": 3,
  "dedupe_domains": true,
  "enable_jina_fallback": true,
  "jina_min_chars": 300,
  "allow_private_networks": false,
  "cache_ttl_seconds": 1800,
  "search_cache_ttl_seconds": 60,
  "trusted_proxy_domains": [],
  "enable_pdf_extract": false
}
```

## 模型与路由

`allowed_model_patterns` 控制哪些模型被视为应该使用 cc-web 的第三方模型。匹配方式是大小写不敏感的关键词包含匹配。

```json
"allowed_model_patterns": ["deepseek", "qwen", "kimi"]
```

`allow_fetch_url_for_claude` 默认是 `false`。这会让官方 Claude 继续优先使用 Claude Code 内置 `WebSearch/WebFetch`，避免自动误选 cc-web。只有你明确希望官方 Claude 也可以调用 `cc-web fetch_url` 时，才改成：

```json
"allow_fetch_url_for_claude": true
```

即使打开这个开关，`web_search` 和 `research_brief` 仍建议只给 `allowed_model_patterns` 中匹配的第三方模型使用。

`block_native_web_for_allowed_models` 默认是 `true`。当当前模型匹配 `allowed_model_patterns` 时，守卫会阻止它调用 Claude Code 原生 `WebFetch`，并提示改用 `cc-web`。注意：部分第三方 Anthropic-compatible API 会在服务端直接拒绝 `WebSearch`，请求到不了 Claude Code 本地工具执行层，因此 `WebSearch` 必须靠 `CLAUDE.md` 启动指令提前绕开。

如果某个第三方 API 的原生 Web 工具已经可用，可以改成：

```json
"block_native_web_for_allowed_models": false
```

`health_check` 会在 `config` 字段里返回 `allow_fetch_url_for_claude` 和 `block_native_web_for_allowed_models`，方便排查当前路由策略。

## 搜索后端

`search_providers` 是推荐配置，表示按顺序尝试多个搜索后端。旧版 `search_provider` 仍兼容，但不建议新配置继续使用单后端字段。

默认搜索链路：

```json
"search_providers": ["duckduckgo", "bing_cn"]
```

如果当前网络无法访问 DuckDuckGo，可以保留默认降级链路，也可以直接只使用 Bing 中文入口：

```json
"search_providers": ["bing_cn"]
```

`bing_cn` 是实用 fallback，不是完整 DuckDuckGo/全球搜索结果的等价替代。使用 `bing_cn` 时，工具返回会包含 `search_scope_note` 提醒模型当前结果可能有区域偏置。

如果你希望增加一个不依赖账号的英文公开搜索 fallback，可以把 Mojeek 放到链路后面：

```json
"search_providers": ["duckduckgo", "mojeek", "bing_cn"]
```

`mojeek` 使用公开 HTML 搜索入口，适合作为轻量补充，不等价于付费搜索 API。

如果你有 SearXNG 实例，可以改为：

```json
{
  "search_providers": ["searxng", "duckduckgo", "bing_cn"],
  "searxng_base_url": "https://your-searxng.example"
}
```

`searxng` 会优先尝试 JSON 搜索接口；如果实例禁用了 JSON 输出，会自动降级读取 HTML 结果页。

`health_check` 会返回 `search_providers`、`search_backend_status` 和 `first_available_search_backend`，方便你一眼判断当前环境到底能用哪个搜索后端。`429` 这类限流状态会被视为不可用，避免误把暂时不可搜索的后端排在第一位。

## 抓取与摘要

- `default_fetch_chars`：`fetch_url` 默认返回字符数。
- `max_fetch_chars`：单次抓取允许返回的最大字符数。
- `max_search_results`：搜索工具最多返回的结果数。
- `max_brief_sources`：`research_brief` 最多抓取的来源数。
- `brief_chars_per_source`：`research_brief` 每个来源最多保留的字符数。
- `brief_concurrency`：`research_brief` 并发抓取数量。
- `dedupe_domains`：`research_brief` 是否按域名去重。

## Jina Reader fallback

`enable_jina_fallback` 控制普通抓取失败、403 或正文太短时是否尝试 Jina Reader。

```json
"enable_jina_fallback": true
```

`jina_min_chars` 控制正文过短时触发 fallback 的阈值。Jina fallback 内部会重复做 URL 安全校验，并默认禁止内网 URL 走 Jina。

启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。

## 缓存与安全开关

`cache_ttl_seconds` 控制公开 URL 正文抓取缓存时间。正文抓取缓存只在 `allow_private_networks: false` 时启用，缓存 key 包含 schema version，避免旧格式缓存污染新逻辑。

`search_cache_ttl_seconds` 控制成功搜索结果的短缓存时间，默认 `60` 秒。它只缓存成功结果，不缓存失败或限流响应；它独立于 `allow_private_networks`，因为搜索缓存不抓取用户提供的任意 URL。

`allow_private_networks` 默认是 `false`。只建议在可信内网文档场景临时开启：

```json
"allow_private_networks": true
```

`trusted_proxy_domains` 用于少数本机透明代理 / TUN 环境：某些公开域名可能解析到 `198.18.0.0/15` 代理测试网段。cc-web 默认会阻止这类解析；只有你确认该域名由可信代理接管时，才加入白名单：

```json
"trusted_proxy_domains": ["github.com"]
```

## PDF 提取

默认 PDF 会明确拒绝，避免误读二进制内容。若需要读取公开 PDF，可安装可选依赖并开启：

推荐 uvx 场景直接刷新 Claude Code 注册命令：

```powershell
uvx cc-web-mcp init --runner uvx --with-pdf --force
```

普通 pip 环境可安装 PyPI extra：

```powershell
py -3.11 -m pip install "cc-web-mcp[pdf]"
```

```json
"enable_pdf_extract": true
```
