# Roadmap

## 已完成

- Hook 守卫：`cc-web-mcp hook-guard` 已输出 Claude Code `PreToolUse` 的 `hookSpecificOutput.permissionDecision = deny` 结构，降低后续 Claude Code 版本更新导致 hook 行为变化的风险。
- 标准包入口：已提供 `pyproject.toml`、`src/cc_web_mcp` 包结构和 `cc-web-mcp` console script。
- 首次初始化：`cc-web-mcp init` 已统一创建配置、注册 Claude Code MCP、写入路由提示和合并 hook；PyPI/uvx 场景可用 `uvx cc-web-mcp init --runner uvx` 注册带当前版本 pin 的持久 uvx MCP server 命令，并为 hook 守卫写入 `uvx --from ... cc-web-mcp hook-guard` 的 exec form。
- Claude 误选防护：默认阻止官方 Claude 使用 cc-web，避免它在已有原生 `WebSearch/WebFetch` 时误选本 MCP；可通过 `allow_fetch_url_for_claude` 单独放开 `fetch_url`。
- 第三方模型误选防护：通过 `CLAUDE.md` 指令预防 DeepSeek、Qwen、Kimi 等匹配模型误走原生 `WebSearch`；通过 `block_native_web_for_allowed_models` 和 hook 兜底拦截本地可达的 `WebFetch`。
- 内容类型分流：HTML、纯文本、Markdown、JSON 已分流处理；PDF 和未知二进制类型默认拒绝。
- 相对链接转绝对链接：Markdown 转换前会把 `<a href>` 解析成绝对链接。
- 搜索后端可插拔：已支持 `duckduckgo`、`bing_cn` 和 `searxng`，默认按 `duckduckgo -> bing_cn` 降级。
- `research_brief` 提效：支持同域名去重、并发抓取、失败来源保留错误信息。
- `research_brief` URL 过滤：搜索结果进入抓取前会过滤非法 URL，并透传搜索后端的 `backend` 字段。
- 反爬诊断：`fetch_url` 会对 `403/429`、验证页、登录页、JS 依赖页和已知强反爬域名超时返回结构化 `fetch_diagnostics`，`research_brief` 会透传失败来源的诊断信息。
- 模型友好的失败提示：失败返回包含 `retryable`、`do_not_retry_reason` 和 `recommended_next_action`，减少重复调用和无效重试。
- 截断续读提示：`fetch_url` 截断时返回 `truncation.next_call`，方便模型按下一段继续读取。
- 状态显示：MCP 工具执行中会发送 progress/log 状态，返回 JSON 也会包含 `status_summary` 和 `steps`。
- 本地诊断：普通用户可通过 `uvx cc-web-mcp doctor` 检查配置文件、Claude Code 指令、hook 守卫、hook 实际可执行性和搜索后端连通性是否就位；非 uvx 安装也可使用本地 `cc-web-mcp doctor`。
- 技术资料源轻量加权：默认小幅优先 GitHub、官方文档、包管理站点、Read the Docs、Stack Overflow 等技术来源，但不完全覆盖搜索后端原始排序。
- 缓存和重复抓取控制：默认开启公开 URL 抓取缓存，TTL 由 `cache_ttl_seconds` 控制，缓存 key 包含 schema version。
- PDF 可选提取：uvx 场景可通过 `uvx cc-web-mcp init --runner uvx --with-pdf --force` 注册 `cc-web-mcp[pdf]@<当前版本>`，开启 `enable_pdf_extract` 后可用 `pypdf` 提取公开 PDF 文本。

## 后续计划

- 当前已支持 DuckDuckGo HTML、Bing 中文入口和 SearXNG。后续可以继续接入 Tavily、Brave Search、Exa、Serper 等可选搜索后端。
- 搜索后端配置可以继续扩展为：

```json
{
  "search_providers": ["duckduckgo", "bing_cn"],
  "searxng_base_url": "",
  "tavily_api_key_env": "TAVILY_API_KEY",
  "brave_api_key_env": "BRAVE_API_KEY"
}
```

- 对开发场景来说，GitHub 网页直接转 Markdown 的效果不一定稳定。后续可以增加专用工具：
  - `github_issue(owner, repo, number)`
  - `github_pr(owner, repo, number)`
  - `github_release(owner, repo)`
  - `github_file(owner, repo, path, ref)`
- 如果用户已经配置 GitHub MCP，也可以不重复实现，只在文档中建议搭配 GitHub MCP 使用。
