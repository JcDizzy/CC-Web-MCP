# Claude Code 路由、Hook 与自动授权

## 路由策略

cc-web 的默认策略是：

- DeepSeek、Qwen、Kimi 等匹配 `allowed_model_patterns` 的第三方模型优先使用 cc-web。
- 官方 Claude 模型优先使用 Claude Code 原生 `WebSearch/WebFetch`。
- 如需让官方 Claude 也能调用 `cc-web fetch_url`，可设置 `allow_fetch_url_for_claude: true`。

`cc-web-mcp init` 默认写入用户级 `~\.claude\CLAUDE.md`。它负责在模型发起请求前预防第三方模型误用 `WebSearch`。

## Hook 守卫

`cc-web-mcp hook-guard` 可作为 Claude Code `PreToolUse` hook 使用。它会读取用户配置文件，并拦截第三方模型误用本地可达的原生 `WebFetch`。cc-web MCP 工具本身不再默认经过 hook，避免工具调用成功时仍出现额外的非阻塞 hook 噪音。

例外：当 `allow_fetch_url_for_claude` 为 `true` 时，官方 Claude 可以调用 `fetch_url`；`web_search` 和 `research_brief` 仍会被守卫拦截。

`WebSearch` 的边界要特别注意：在 DeepSeek 等第三方 API 中，`WebSearch` 可能在 API 请求阶段直接返回 400，`PreToolUse` hook 不会触发。所以 `WebSearch` 预防依赖 `cc-web-mcp init` 写入的 `CLAUDE.md` 指令；hook 只负责 `WebFetch` 和 cc-web 工具的本地兜底。

`PreToolUse` 的 matcher 推荐只匹配 `WebFetch`，例如：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "cc-web-mcp hook-guard",
            "timeout": 5
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "^WebFetch$",
        "hooks": [
          {
            "type": "command",
            "command": "cc-web-mcp hook-guard",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

普通用户推荐直接通过 `uvx` 初始化：

```powershell
uvx cc-web-mcp init --runner uvx
```

如果手动配置 hook，推荐参考初始化命令自动写入的 exec form：`command` 为 `uvx`，`args` 为 `["--from", "cc-web-mcp@<当前版本>", "cc-web-mcp", "hook-guard"]`。只有在 `cc-web-mcp` 已经通过 `pipx` 或 PATH 可见的本地安装方式可直接运行时，才使用示例里的 `cc-web-mcp hook-guard` console script；这样可以避免把具体仓库路径或 Python 解释器路径写死在 `settings.json` 里。

这样会形成双层路由：`CLAUDE.md` 负责在模型发起请求前预防 `WebSearch`；hook 负责在本地执行层拦截 `WebFetch`。官方 Claude 默认走原生 `WebSearch/WebFetch`；DeepSeek、Qwen、Kimi 等匹配模型默认走 `cc-web`。

守卫输出会同时包含：

- `permissionDecisionReason`：用于权限结果和界面提示。
- `additionalContext`：注入到模型上下文，明确提示“不要重试 WebFetch，改用 cc-web MCP”。

## 项目级提示

如果希望只在某个项目中启用，也可以在项目的 `CLAUDE.md` 或 `AGENTS.md` 中加入类似说明：

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

注意：这里是权限规则里的通配写法；hook `matcher` 使用 Claude Code hook matcher 规则，推荐保留正则 `^WebFetch$`。

不建议为了这个 MCP 长期开启 `--dangerously-skip-permissions`。更稳妥的方式是只 allow `cc-web` 的只读工具，同时保留 hook 守卫对非目标模型的拦截。
