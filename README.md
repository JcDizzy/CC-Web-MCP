# CC Web MCP

CC Web MCP 是一个面向 Claude Code 第三方模型接入场景的轻量网页搜索和抓取 MCP。

它的主要用途是：当 Claude Code 接入 DeepSeek、Qwen、Kimi 等没有官方 `WebSearch` / `WebFetch` 能力的模型时，补上可访问国内外公开网页的只读工具链。官方 Claude 模型仍建议使用 Claude Code 原生搜索能力。

## 功能概览

- `web_search`：按配置的搜索后端顺序搜索公开网页，默认 `duckduckgo -> bing_cn`。
- `fetch_url`：抓取 `http/https` 页面并转为 Markdown，支持 `start_index` 分页读取。
- `research_brief`：先搜索，再抓取少量来源的短内容，减少上下文占用。
- `health_check`：检查依赖、配置和网络连通性。
- 模型路由：通过 `allowed_model_patterns`、启动指令和 hook 守卫，让 DeepSeek、Qwen、Kimi 等第三方模型优先走 cc-web，官方 Claude 默认继续走原生 `WebSearch/WebFetch`。
- 安全边界：默认禁止抓取本机、内网、链路本地地址和云 metadata 地址，并检查 DNS 解析和重定向后的最终 URL。

## 快速开始

普通用户推荐直接用 `uvx` 从 PyPI 运行，不需要克隆仓库，也不需要提前创建虚拟环境：

```powershell
uvx cc-web-mcp init --runner uvx
uvx cc-web-mcp doctor
```

`--runner uvx` 是推荐写法：它会让 Claude Code 的 MCP server 配置长期指向稳定的 `uvx cc-web-mcp@<当前版本>`，而不是某个临时缓存目录或本地开发环境里的 Python。hook 守卫会单独使用 exec form 的 `uvx --from cc-web-mcp@<当前版本> cc-web-mcp hook-guard`，便于可靠传递 `--state` / `--config` 等参数。

如果之前已经用普通 `pip`、editable install 或旧的 uv 缓存路径初始化过，切换到 `uvx` 后请重新运行：

```powershell
uvx cc-web-mcp init --runner uvx --force
```

首次初始化入口是 `init` 子命令。普通用户建议始终通过 `uvx cc-web-mcp init --runner uvx` 调用；只有 `pipx`、普通 `pip` 或 editable install 且命令已在 `PATH` 中时，才直接运行 `cc-web-mcp init`。初始化会：

- 创建用户配置文件。
- 注册 Claude Code 用户级 stdio MCP。普通 Python 安装会注册为当前 Python 的 `-m cc_web_mcp`；`--runner uvx` 会注册为 `uvx cc-web-mcp@<当前版本>`。
- 向用户级 `~\.claude\CLAUDE.md` 写入第三方模型路由提示。
- 向用户级 `~\.claude\settings.json` 合并 hook 守卫，并在写入前备份。

开发者需要改源码时，再使用 editable install：

```powershell
git clone https://github.com/JcDizzy/CC-Web-MCP.git <安装目录>
cd <安装目录>
py -3.11 -m pip install -e .
py -3.11 -m cc_web_mcp init
py -3.11 -m cc_web_mcp doctor
```

`pipx` 或普通 `pip` 也可以用，但不作为首选路径；如果 `pip install` 提示 `cc-web-mcp.exe` 所在目录不在 `PATH`，可以继续使用 `py -3.11 -m cc_web_mcp ...` 形式运行。

如果需要让 Claude Code 中长期注册的 uvx 命令支持 PDF 提取，初始化时加 `--with-pdf`：

```powershell
uvx cc-web-mcp init --runner uvx --with-pdf --force
```

先看计划、不写文件：

```powershell
uvx cc-web-mcp init --runner uvx --dry-run
```

非 `uvx` 安装且 `cc-web-mcp` 已在 `PATH` 中时，也可以用本地命令预览：

```powershell
cc-web-mcp init --dry-run
```

如果只想初始化配置文件，普通用户继续使用 `uvx`：

```powershell
uvx cc-web-mcp config init
uvx cc-web-mcp config path
```

非 `uvx` 安装且 `cc-web-mcp` 已在 `PATH` 中时，也可以写成：

```powershell
cc-web-mcp config init
cc-web-mcp config path
```

## 基础配置

默认配置路径：

- Windows：`%APPDATA%\cc-web-mcp\config.json`
- macOS/Linux：`~/.config/cc-web-mcp/config.json`

常用调整：

- 同时适配更多第三方模型：`"allowed_model_patterns": ["deepseek", "qwen", "kimi"]`
- DuckDuckGo 不稳定时只使用 Bing 中文入口：`"search_providers": ["bing_cn"]`
- 某个第三方 API 的原生 Web 工具已经可用时：`"block_native_web_for_allowed_models": false`
- 明确允许官方 Claude 调用 `cc-web fetch_url`：`"allow_fetch_url_for_claude": true`

完整配置说明见 [docs/configuration.md](docs/configuration.md)。

## 第一次验证建议

安装完成后，建议先用第三方模型在 Claude Code 里做一次小范围联网任务：

```text
使用 cc-web 查询 “Claude Code MCP PreToolUse hook permissionDecision”，先用 research_brief 获取资料概览，再总结当前推荐写法。
```

如果模型仍尝试调用原生 `WebSearch`，先检查 `~\.claude\CLAUDE.md`。如果模型尝试调用原生 `WebFetch` 并被拦截，说明 hook 已生效；模型应根据提示改用 `cc-web fetch_url`。

## 开发与测试

```powershell
py -3.11 -m pip install -e .
py -3.11 -m pytest .\tests -q
```

构建发布包：

```powershell
py -3.11 -m build
```

## 文档

- [安装与验证](docs/installation.md)
- [配置说明](docs/configuration.md)
- [Claude Code 路由、Hook 与自动授权](docs/routing-and-permissions.md)
- [工具能力与使用细节](docs/capabilities.md)
- [安全说明](docs/security.md)
- [Roadmap](docs/roadmap.md)

## 重要边界

- `bing_cn` 是实用降级，不是全球搜索的等价替代。
- `WebSearch` 在部分第三方 Anthropic-compatible API 中会在服务端直接报错，Claude Code 本地 hook 拦截不到；需要依赖 `CLAUDE.md` 启动指令提前绕开。
- 当前不包含 Playwright 或浏览器自动化，不处理重 JavaScript、登录墙、验证码页面。
- 启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。
