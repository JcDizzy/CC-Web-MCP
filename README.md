# CC Web MCP

CC Web MCP 是一个面向 Claude Code 第三方模型接入场景的轻量网页搜索和抓取 MCP。

它的主要用途是：当 Claude Code 接入 DeepSeek、Qwen、Kimi 等没有官方 `WebSearch` / `WebFetch` 能力的模型时，补上可访问国内外公开网页的只读工具链。官方 Claude 模型仍建议使用 Claude Code 原生搜索能力。

## 功能

- `web_search`：按配置的搜索后端顺序搜索公开网页，默认 `duckduckgo -> bing_cn`。
- `fetch_url`：抓取 `http/https` 页面并转为 Markdown，支持 `start_index` 分页读取。
- `research_brief`：先搜索，再抓取少量来源的短内容，减少上下文占用。
- `health_check`：检查依赖、配置和网络连通性。
- 可配置允许模型：通过 `config.json` 的 `allowed_model_patterns` 控制哪些模型能使用。
- 可选 Jina Reader fallback：普通抓取失败、403 或正文太短时，用 Jina Reader 作为备用读取通道。
- SSRF 安全边界：默认禁止抓取本机、内网、链路本地地址和云 metadata 地址，并检查重定向后的最终 URL。
- 内容类型分流：HTML 转 Markdown，文本/Markdown 直接清洗，JSON 格式化，PDF 默认拒绝，也可安装可选依赖后开启提取。
- 相对链接转绝对链接：页面内 `/docs/xxx`、`../guide` 会按页面 URL 转成完整链接。
- 轻量缓存：默认按公开 URL 和提取模式缓存抓取结果，减少重复请求。
- 技术资料源加权：默认优先排序 GitHub、官方文档、包管理站点、Read the Docs、Stack Overflow 等来源。
- 可插拔搜索后端：默认 DuckDuckGo HTML，失败后降级到 Bing 中文入口，也可配置 SearXNG 作为自建/公共搜索入口。

## 安装说明

以下命令以 Windows PowerShell 和 `py -3.11` 为例。`<安装目录>` 请替换为你自己的项目路径。

1. 克隆仓库：

```powershell
git clone https://github.com/JcDizzy/CC-Web-MCP.git <安装目录>
cd <安装目录>
```

2. 安装依赖：

```powershell
py -3.11 -m pip install -r requirements.txt
```

3. 注册到 Claude Code：

```powershell
claude mcp add --scope user --transport stdio cc-web -- py -3.11 .\server.py
```

如果要使用指定 Python，请把路径替换为你自己的解释器位置：

```powershell
claude mcp add --scope user --transport stdio cc-web -- <Python解释器路径> .\server.py
```

4. 确认 MCP 已注册：

```powershell
claude mcp get cc-web
```

5. 在 Claude Code 中调用 `health_check`，确认依赖和网络连通性。

如需限制只有 DeepSeek 等第三方模型能调用本 MCP，请把 `hooks\guard.py` 配置为 Claude Code 的 `PreToolUse` hook，并在 `config.json` 的 `allowed_model_patterns` 中维护允许模型。

## 配置

编辑 `config.json`：

```json
{
  "allowed_model_patterns": ["deepseek"],
  "search_provider": "duckduckgo",
  "search_providers": ["duckduckgo", "bing_cn"],
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
  "enable_pdf_extract": false
}
```

如果要同时适用于更多模型：

```json
"allowed_model_patterns": ["deepseek", "qwen", "kimi"]
```

如果当前网络无法访问 DuckDuckGo，可以保留默认降级链路：

```json
"search_providers": ["duckduckgo", "bing_cn"]
```

也可以直接只使用 Bing 中文入口：

```json
"search_providers": ["bing_cn"]
```

## Hook 守卫

`hooks\guard.py` 可作为 Claude Code `PreToolUse` hook 使用。它会读取 `config.json`，只允许匹配 `allowed_model_patterns` 的模型调用 `mcp__cc-web__*` / `mcp__cc_web__*` 工具。

## 自动授权

如果不想每次调用 cc-web MCP 都手动确认，可以在 Claude Code 的 `settings.json` 中加入只读 MCP 工具 allow 规则。推荐先使用细粒度写法：

```json
{
  "permissions": {
    "allow": [
      "mcp__cc-web__health_check",
      "mcp__cc-web__web_search",
      "mcp__cc-web__research_brief",
      "mcp__cc-web__fetch_url"
    ]
  }
}
```

如果你的 Claude Code 版本把连字符服务名规范化成下划线，也可以使用：

```json
{
  "permissions": {
    "allow": [
      "mcp__cc_web__health_check",
      "mcp__cc_web__web_search",
      "mcp__cc_web__research_brief",
      "mcp__cc_web__fetch_url"
    ]
  }
}
```

确认本机显示的实际工具名后，也可以用通配形式：

```json
{
  "permissions": {
    "allow": ["mcp__cc-web__*"]
  }
}
```

不建议为了这个 MCP 长期开启 `--dangerously-skip-permissions`。更稳妥的方式是只 allow `cc-web` 的只读工具，同时保留 `hooks\guard.py` 对非目标模型的拦截。

## 测试

```powershell
py -3.11 -m pytest .\tests -q
```

## 可选能力

### SearXNG 搜索后端

默认搜索链路是 `duckduckgo -> bing_cn`。如果你有 SearXNG 实例，可以改为：

```json
{
  "search_provider": "searxng",
  "search_providers": ["searxng", "duckduckgo", "bing_cn"],
  "searxng_base_url": "https://your-searxng.example"
}
```

### 中国网络环境

如果本机网络访问 DuckDuckGo 不稳定，CC Web MCP 会按 `search_providers` 顺序继续尝试后续后端。默认配置会降级到 `bing_cn`，返回结果里会包含：

- `backend`：本次实际使用的搜索后端，例如 `bing_cn`。
- `fallback_reason`：触发降级的原因，例如 `duckduckgo_html failed: ...`。
- `attempted_backends`：每个搜索后端的尝试结果。

这样模型可以继续拿到可用资料，同时知道当前不是完整的 DuckDuckGo/全球搜索结果。

### PDF 提取

默认 PDF 会明确拒绝，避免误读二进制内容。若需要读取公开 PDF，可安装可选依赖并开启：

```powershell
py -3.11 -m pip install -r requirements-optional.txt
```

```json
"enable_pdf_extract": true
```

## 已完成

- Hook 守卫：`hooks/guard.py` 已输出 Claude Code `PreToolUse` 的 `hookSpecificOutput.permissionDecision = deny` 结构，降低后续 Claude Code 版本更新导致 hook 行为变化的风险。
- 内容类型分流：HTML、纯文本、Markdown、JSON 已分流处理；PDF 和未知二进制类型默认拒绝。
- 相对链接转绝对链接：Markdown 转换前会把 `<a href>` 解析成绝对链接。
- 搜索后端可插拔：已支持 `duckduckgo`、`bing_cn` 和 `searxng`，默认按 `duckduckgo -> bing_cn` 降级。
- `research_brief` 提效：支持同域名去重、并发抓取、失败来源保留错误信息。
- `research_brief` URL 过滤：搜索结果进入抓取前会过滤非法 URL，并透传搜索后端的 `backend` 字段。
- 技术资料源轻量加权：默认小幅优先 GitHub、官方文档、包管理站点、Read the Docs、Stack Overflow 等技术来源，但不完全覆盖搜索后端原始排序。
- 缓存和重复抓取控制：默认开启公开 URL 抓取缓存，TTL 由 `cache_ttl_seconds` 控制，缓存 key 包含 schema version。
- PDF 可选提取：安装 `requirements-optional.txt` 并开启 `enable_pdf_extract` 后，可用 `pypdf` 提取公开 PDF 文本。

## 后续计划

- 当前已支持 DuckDuckGo HTML、Bing 中文入口和 SearXNG。后续可以继续接入：
  - Tavily
  - Brave Search
  - Exa
  - Serper
- 配置可以类似：

```json
{
  "search_provider": "duckduckgo",
  "searxng_base_url": "",
  "tavily_api_key_env": "TAVILY_API_KEY",
  "brave_api_key_env": "BRAVE_API_KEY"
}
```

- 对开发场景来说，GitHub 网页直接转 Markdown 的效果不一定稳定。
- 后续可以增加专用工具：
  - `github_issue(owner, repo, number)`
  - `github_pr(owner, repo, number)`
  - `github_release(owner, repo)`
  - `github_file(owner, repo, path, ref)`
- 如果用户已经配置 GitHub MCP，也可以不重复实现，只在 README 中建议搭配 GitHub MCP 使用。

## 安全说明

- 这是只读工具链，不执行网页写入操作。
- `fetch_url` 默认只允许 `http/https`，并禁止本机、内网、链路本地地址和云 metadata 地址。
- URL 安全校验会同时检查原始主机名和 DNS 解析后的 IP，避免公开域名解析到私网或本机地址。
- 30x 重定向后的目标 URL 会再次校验，避免公网 URL 跳转到内网地址。
- `research_brief` 在抓取搜索结果前会过滤非法 URL，并在返回里记录 `skipped_results`。
- Jina Reader fallback 也会重复执行 URL 安全校验；默认禁止内网 URL 走 Jina。
- 缓存只在 `allow_private_networks: false` 时启用，并且缓存 key 包含 schema version，避免旧格式缓存污染新逻辑。
- `allow_private_networks: true` 只建议在可信内网文档场景临时开启。
- 当前不包含 Playwright 或浏览器自动化，不处理重 JavaScript、登录墙、验证码页面。
- 启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。
