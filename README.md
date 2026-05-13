# CC Web MCP

CC Web MCP 是一个面向 Claude Code 第三方模型接入场景的轻量网页搜索和抓取 MCP。

它的主要用途是：当 Claude Code 接入 DeepSeek、Qwen、Kimi 等没有官方 `WebSearch` / `WebFetch` 能力的模型时，补上可访问国内外公开网页的只读工具链。官方 Claude 模型仍建议使用 Claude Code 原生搜索能力。

## 功能

- `web_search`：使用 DuckDuckGo HTML 搜索公开网页。
- `fetch_url`：抓取 `http/https` 页面并转为 Markdown，支持 `start_index` 分页读取。
- `research_brief`：先搜索，再抓取少量来源的短内容，减少上下文占用。
- `health_check`：检查依赖、配置和网络连通性。
- 可配置允许模型：通过 `config.json` 的 `allowed_model_patterns` 控制哪些模型能使用。
- 可选 Jina Reader fallback：普通抓取失败、403 或正文太短时，用 Jina Reader 作为备用读取通道。

## 配置

编辑 `config.json`：

```json
{
  "allowed_model_patterns": ["deepseek"],
  "default_fetch_chars": 10000,
  "max_fetch_chars": 60000,
  "max_search_results": 10,
  "max_brief_sources": 3,
  "brief_chars_per_source": 2500,
  "enable_jina_fallback": true,
  "jina_min_chars": 300
}
```

如果要同时适用于更多模型：

```json
"allowed_model_patterns": ["deepseek", "qwen", "kimi"]
```

## Claude Code 注册

```powershell
claude mcp add --scope user --transport stdio cc-web -- py -3.11 E:\jc\cc_web_mcp\server.py
```

如果要使用指定 Python，请把路径替换为你自己的解释器位置：

```powershell
claude mcp add --scope user --transport stdio cc-web -- C:\Path\To\python.exe E:\jc\cc_web_mcp\server.py
```

## Hook 守卫

`hooks\guard.py` 可作为 Claude Code `PreToolUse` hook 使用。它会读取 `config.json`，只允许匹配 `allowed_model_patterns` 的模型调用 `mcp__cc_web__*` 工具。

## 测试

```powershell
py -3.11 -m pytest E:\jc\cc_web_mcp\tests -q
```

## 改进建议 / Roadmap

当前版本已经可以作为轻量 MVP 使用，但如果准备长期作为 DeepSeek / Qwen / Kimi 等第三方模型在 Claude Code 里的网页检索工具，建议优先补强以下工程点。

### P0：安全边界

- `fetch_url` 目前只限制 `http/https`，后续应默认禁止抓取本机、内网、链路本地地址和云服务器 metadata 地址，避免 SSRF 风险。
- 建议默认拦截：
  - `localhost`
  - `127.0.0.0/8`
  - `10.0.0.0/8`
  - `172.16.0.0/12`
  - `192.168.0.0/16`
  - `169.254.0.0/16`
  - `::1`
  - `fc00::/7`
  - `fe80::/10`
- 不能只校验原始 URL，也要校验重定向后的 `final_url`，避免公网 URL 通过 30x 跳转到内网地址。
- 如需访问内网文档，建议后续增加显式配置项，例如 `allow_private_networks: false`，默认关闭。

### P0：Hook 阻断格式

- `hooks/guard.py` 当前通过输出 `{"decision":"block"}` 表达阻断意图，建议改为 Claude Code `PreToolUse` hook 的新版结构化输出：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "cc-web MCP 仅允许配置中匹配的模型使用，官方 Claude 请优先使用原生 WebSearch/WebFetch。"
  }
}
```

- 这样可以减少后续 Claude Code 版本更新导致 hook 行为变化的风险。

### P1：搜索后端可插拔

- 当前 `web_search` 使用 DuckDuckGo HTML，优点是无需 API key、实现轻量，但稳定性和搜索质量受 HTML 结构、限流、地区差异影响。
- 建议抽象搜索后端，保留 DuckDuckGo 作为默认免费后端，同时预留：
  - SearXNG
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

### P1：内容类型分流

- 当前 `fetch_url` 主要按 HTML 页面处理，对纯文本、Markdown、JSON、PDF、二进制文件的处理较粗。
- 建议根据 `content-type` 分流：
  - `text/html`：BeautifulSoup + markdownify
  - `text/plain` / `text/markdown`：直接清洗并分页返回
  - `application/json`：格式化、截断并返回
  - `application/pdf`：暂时明确报错，或后续接入 PDF 提取库
  - 其他二进制类型：默认拒绝抓取
- 这样可以避免模型误读乱码内容，也方便后续支持芯片手册、标准文档等 PDF 资料。

### P1：相对链接转绝对链接

- `extract_markdown(html, base_url)` 当前传入了 `base_url`，但还没有把页面里的相对链接转换成绝对链接。
- 建议在 Markdown 转换前，用 `urllib.parse.urljoin(base_url, href)` 处理 `<a href>`。
- 这样模型后续继续抓取官方文档内部链接时，不会拿到 `/docs/xxx`、`../guide/install` 这类不完整 URL。

### P2：`research_brief` 提效和提质

- 当前 `research_brief` 逐个抓取搜索结果，逻辑简单但速度可能受慢页面影响。
- 后续可以加入：
  - `asyncio.gather` 并发抓取
  - 最大并发数限制，例如 2~3
  - 同域名结果去重
  - 抓取失败时继续处理其他来源
  - 每个来源记录失败原因，方便模型判断资料质量

### P2：技术资料源加权

- 面向 coding agent 时，搜索结果最好偏向原始、高质量技术来源。
- 建议优先保留或加权：
  - 官方文档站点
  - GitHub 仓库、Issue、PR、Release
  - Stack Overflow
  - Read the Docs
  - PyPI / npm / crates.io 等包管理站点
  - 芯片厂商官网、SDK 文档、协议标准文档
- 可考虑降低搬运站、采集站、低质量 SEO 站点的优先级。

### P2：缓存和重复抓取控制

- Agent 可能在一次会话里多次抓取同一个 URL。
- 可以增加轻量缓存，例如按 URL + 参数缓存到本地目录，并设置 TTL。
- 缓存内容建议只用于公开网页，不缓存私密 URL 或内网页面。

### P2：GitHub 专用工具

- 对开发场景来说，GitHub 网页直接转 Markdown 的效果不一定稳定。
- 后续可以增加专用工具：
  - `github_issue(owner, repo, number)`
  - `github_pr(owner, repo, number)`
  - `github_release(owner, repo)`
  - `github_file(owner, repo, path, ref)`
- 如果用户已经配置 GitHub MCP，也可以不重复实现，只在 README 中建议搭配 GitHub MCP 使用。

## 说明

- 这是只读工具链，不执行网页写入操作。
- 当前不包含 Playwright 或浏览器自动化，不处理重 JavaScript、登录墙、验证码页面。
- 启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。
