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

如果要运行测试，再安装开发依赖：

```powershell
py -3.11 -m pip install -r requirements-dev.txt
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

5. 安装 Claude Code 启动指令：

```powershell
py -3.11 .\scripts\install_instructions.py
```

这个脚本会把 cc-web 路由说明写入用户级 `~\.claude\CLAUDE.md`。它的作用是让 DeepSeek、Qwen、Kimi 等第三方模型在第一次思考时就避开原生 `WebSearch`，直接使用 cc-web。

6. 安装 Claude Code hook 守卫：

```powershell
py -3.11 .\scripts\install_hook.py
```

这个脚本会合并更新用户级 `~\.claude\settings.json`，并在写入前创建 `settings.json.cc-web-backup.<时间戳>` 备份。它可以重复运行，不会重复添加同一条 hook。

Claude Code 可能用 bash 执行 hook，即使你平时在 Windows PowerShell 里使用 Claude Code。安装脚本会把 hook command 里的 Windows 路径自动归一化为 bash 友好的正斜杠形式，并给含空格的路径加 shell 引号，避免出现 `E:anacondapython.exe: command not found` 这类错误。

7. 在 Claude Code 中调用 `health_check`，确认依赖和网络连通性。

也可以在命令行先做一次本地诊断：

```powershell
py -3.11 .\scripts\doctor.py
```

默认诊断会检查本地配置、Claude Code 指令、hook 守卫和网络连通性。如果只想看 JSON 结果，便于贴给模型分析，并且暂时跳过真实网络访问：

```powershell
py -3.11 .\scripts\doctor.py --json --skip-network
```

如需限制只有 DeepSeek 等第三方模型能调用本 MCP，请保留启动指令和 hook 守卫，并在 `config.json` 的 `allowed_model_patterns` 中维护允许模型。

## 配置

编辑 `config.json`：

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
  "enable_pdf_extract": false
}
```

`search_providers` 是推荐配置，表示按顺序尝试多个搜索后端。旧版 `search_provider` 仍兼容，但不建议新配置继续使用单后端字段。

`allow_fetch_url_for_claude` 默认是 `false`。这会让官方 Claude 继续优先使用 Claude Code 内置 `WebSearch/WebFetch`，避免自动误选 cc-web。只有你明确希望官方 Claude 也可以调用 `cc-web fetch_url` 时，才改成：

```json
"allow_fetch_url_for_claude": true
```

即使打开这个开关，`web_search` 和 `research_brief` 仍建议只给 `allowed_model_patterns` 中匹配的第三方模型使用。

`block_native_web_for_allowed_models` 默认是 `true`。当当前模型匹配 `allowed_model_patterns` 时，守卫会阻止它调用 Claude Code 原生 `WebFetch`，并提示改用 `cc-web`。注意：部分第三方 Anthropic-compatible API 会在服务端直接拒绝 `WebSearch`，请求到不了 Claude Code 本地工具执行层，因此 `WebSearch` 必须靠 `CLAUDE.md` 启动指令提前绕开。如果某个第三方 API 的原生 Web 工具已经可用，可以改成：

```json
"block_native_web_for_allowed_models": false
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

`hooks\guard.py` 可作为 Claude Code `PreToolUse` hook 使用。它会读取 `config.json`，默认只允许匹配 `allowed_model_patterns` 的模型调用 `mcp__cc-web__*` / `mcp__cc_web__*` 工具，并拦截第三方模型误用本地可达的原生 `WebFetch`。

例外：当 `allow_fetch_url_for_claude` 为 `true` 时，官方 Claude 可以调用 `fetch_url`；`web_search` 和 `research_brief` 仍会被守卫拦截。

`WebSearch` 的边界要特别注意：在 DeepSeek 等第三方 API 中，`WebSearch` 可能在 API 请求阶段直接返回 400，`PreToolUse` hook 不会触发。所以 `WebSearch` 预防依赖 `scripts\install_instructions.py` 写入的 `CLAUDE.md` 指令；hook 只负责 `WebFetch` 和 cc-web 工具的本地兜底。

`PreToolUse` 的 matcher 推荐包含 cc-web MCP 工具和 `WebFetch`，例如：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "py -3.11 ./hooks/guard.py",
            "timeout": 5
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "^(mcp__cc[-_]web__.*|WebFetch)$",
        "hooks": [
          {
            "type": "command",
            "command": "py -3.11 ./hooks/guard.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

推荐直接运行 `py -3.11 .\scripts\install_hook.py` 自动写入。上面的 JSON 主要用于手动检查或迁移到项目级 settings。手动配置时请使用正斜杠路径；不要把 `E:\anaconda\python.exe` 这类反斜杠 Windows 路径直接写进 hook command。

这样会形成双层路由：`CLAUDE.md` 负责在模型发起请求前预防 `WebSearch`；hook 负责在本地执行层拦截 `WebFetch` 和 cc-web 误用。官方 Claude 默认走原生 `WebSearch/WebFetch`；DeepSeek、Qwen、Kimi 等匹配模型默认走 `cc-web`。

守卫输出会同时包含：

- `permissionDecisionReason`：用于权限结果和界面提示。
- `additionalContext`：注入到模型上下文，明确提示“不要重试 WebFetch，改用 cc-web MCP”。

`scripts\install_instructions.py` 默认写入用户级 `~\.claude\CLAUDE.md`。如果希望只在某个项目中启用，也可以在项目的 `CLAUDE.md` 或 `AGENTS.md` 中加入类似说明：

```markdown
当当前模型是 DeepSeek、Qwen、Kimi 等第三方模型时，外网搜索和网页抓取优先使用 cc-web MCP：
- 不要调用 WebSearch；部分第三方 API 会在 Claude Code hook 触发前直接拒绝 WebSearch。
- 搜索/概览：mcp__cc-web__research_brief
- 原始搜索：mcp__cc-web__web_search
- 读取 URL：mcp__cc-web__fetch_url
官方 Claude 模型仍优先使用原生 WebSearch/WebFetch。
```

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
    "allow": ["mcp__cc-web__*", "mcp__cc_web__*"]
  }
}
```

注意：这里是权限规则里的通配写法；上面的 hook `matcher` 使用 Claude Code hook matcher 规则，推荐保留正则 `^(mcp__cc[-_]web__.*|WebFetch)$`。

不建议为了这个 MCP 长期开启 `--dangerously-skip-permissions`。更稳妥的方式是只 allow `cc-web` 的只读工具，同时保留 `hooks\guard.py` 对非目标模型的拦截。

## 测试

```powershell
py -3.11 -m pip install -r requirements-dev.txt
py -3.11 -m pytest .\tests -q
```

## 可选能力

### SearXNG 搜索后端

默认搜索链路是 `duckduckgo -> bing_cn`。如果你有 SearXNG 实例，可以改为：

```json
{
  "search_providers": ["searxng", "duckduckgo", "bing_cn"],
  "searxng_base_url": "https://your-searxng.example"
}
```

### 中国网络环境

如果本机网络访问 DuckDuckGo 不稳定，CC Web MCP 会按 `search_providers` 顺序继续尝试后续后端。默认配置会降级到 `bing_cn`，返回结果里会包含：

- `backend`：本次实际使用的搜索后端，例如 `bing_cn`。
- `search_scope_note`：当使用 `bing_cn` 时提醒模型这是区域偏置的 fallback，不等价于完整全球搜索。
- `fallback_reason`：触发降级的原因，例如 `duckduckgo_html failed: ...`。
- `attempted_backends`：每个搜索后端的尝试结果。

`health_check` 也会返回 `search_providers`、`search_backend_status` 和 `first_available_search_backend`，方便你一眼判断当前环境到底能用哪个搜索后端。

这样模型可以继续拿到可用资料，同时知道当前不是完整的 DuckDuckGo/全球搜索结果。

### 上下文友好的失败提示和分页

`fetch_url` 和 `web_search` 失败时会尽量返回给模型可直接使用的处理字段：

- `retryable`：是否值得稍后重试。
- `retry_after_seconds`：建议等待时间，仅在可能是临时网络问题时出现。
- `do_not_retry_reason`：告诉模型不要用同样参数立刻重复调用的原因。
- `recommended_next_action`：建议下一步，例如换来源、用 `research_brief`，或先跑 `health_check`。

`fetch_url` 返回内容被截断时，除了 `next_start_index`，还会返回 `truncation.next_call`。模型可以用里面的 `url`、`max_chars`、`start_index` 和 `extract_mode` 继续读取下一段，而不是重复读取同一段。

### 状态显示

`web_search`、`fetch_url` 和 `research_brief` 会在执行时向 Claude Code 发送 MCP progress/log 状态，例如正在搜索哪个后端、正在抓取哪个 URL、是否进入 Jina Reader fallback。Claude Code 是否把这些状态显示在 `Called cc-web ...` 折叠行附近，取决于当前 Claude Code 版本的 MCP 进度渲染；不改 Claude Code 源码时，cc-web 不能强制改写那一行 UI。

为了保证状态始终可见，工具返回 JSON 里也会包含：

- `status_summary`：一句话概括本次调用做了什么。
- `steps`：简短步骤列表，只记录搜索后端、抓取来源、fallback 等状态，不记录正文内容。

### 反爬、登录墙和超时

`fetch_url` 不会尝试绕过验证码、登录墙或 WAF。遇到知乎、微信公众号、X、Reddit 等强反爬或强登录站点时，轻量 HTTP 抓取可能返回 `403`、安全验证页、空正文或 `ReadTimeout`。

这类失败会尽量返回结构化诊断：

- `error_type`：例如 `captcha_or_challenge`、`login_required`、`blocked_or_waf`、`js_required`、`timeout_suspected_antibot`、`network_timeout`。
- `fetch_diagnostics.confidence`：`high` / `medium` / `low`，表示诊断置信度。
- `fetch_diagnostics.signals`：触发判断的证据，例如 `status_code=403`、`challenge keyword: 安全验证`、`known anti-bot domain: www.zhihu.com`。
- `fetch_diagnostics.recommendation`：给模型的处理建议，通常是改用搜索摘要、官方来源或其他可访问来源。

`ReadTimeout` 本身不能证明反爬；只有命中已知强反爬域名或其他页面特征时，才会标成 `timeout_suspected_antibot`。如果 Jina Reader fallback 也失败，cc-web 会优先保留原始目标站点的反爬诊断，避免被二次 fallback 的超时错误覆盖。

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
- 本地诊断脚本：`scripts/doctor.py` 可检查配置文件、Claude Code 指令、hook 守卫和搜索后端连通性是否就位。
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
  "search_providers": ["duckduckgo", "bing_cn"],
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
- 缓存只在 `allow_private_networks: false` 时启用，并且缓存 key 包含 schema version，避免旧格式缓存污染新逻辑。Jina Reader fallback 结果不会写入原 URL 的直接抓取缓存，避免临时 fallback 掩盖后续恢复的原站点内容。
- `allow_private_networks: true` 只建议在可信内网文档场景临时开启。
- 当前不包含 Playwright 或浏览器自动化，不处理重 JavaScript、登录墙、验证码页面。
- 对疑似反爬页面，cc-web 只做诊断和降级提示，不尝试绕过网站访问控制。
- 启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。
