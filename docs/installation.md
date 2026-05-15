# 安装与验证

普通用户建议优先使用 `uvx`。以下命令以 Windows PowerShell 为例。

## 安装

### 推荐：uvx

项目发布在 PyPI 上，推荐用 `uvx` 直接运行，不需要克隆仓库，也不需要提前创建虚拟环境：

```powershell
uvx cc-web-mcp init --runner uvx
uvx cc-web-mcp doctor
```

`--runner uvx` 很重要：它会把 Claude Code MCP 注册成 `uvx cc-web-mcp`，避免把 uvx 临时缓存目录里的 `python.exe` 写进长期配置。
如果之前已经用普通 `pip`、editable install 或旧的 uv 缓存路径初始化过，切换到 `uvx` 后请重新运行 `uvx cc-web-mcp init --runner uvx --force`，刷新 Claude Code 里保存的 MCP 命令路径。

如果需要 PDF 提取能力，初始化时加 `--with-pdf`，Claude Code 保存的命令会使用 `cc-web-mcp[pdf]`：

```powershell
uvx cc-web-mcp init --runner uvx --with-pdf --force
```

### 备选：pipx 或 pip

如果所在环境不能使用 `uvx`，也可以使用 `pipx`：

```powershell
pipx install cc-web-mcp
cc-web-mcp init
cc-web-mcp doctor
```

也可以安装到当前 Python 环境：

```powershell
py -3.11 -m pip install cc-web-mcp
py -3.11 -m cc_web_mcp init
py -3.11 -m cc_web_mcp doctor
```

如果 Windows 提示 `cc-web-mcp.exe` 安装到了不在 `PATH` 中的目录，例如 `E:\anaconda\Scripts`，安装本身仍然成功。后续命令可以直接使用 `py -3.11 -m cc_web_mcp ...` 模块形式。

### 开发目录安装

只有在需要修改源码或运行本地测试时，才建议使用 editable install：

```powershell
git clone https://github.com/JcDizzy/CC-Web-MCP.git <安装目录>
cd <安装目录>
py -3.11 -m pip install -e .
py -3.11 -m cc_web_mcp init
py -3.11 -m cc_web_mcp doctor
```

## 首次初始化

如果按推荐的 `uvx` 路径使用，首次初始化只需要运行一次：

```powershell
uvx cc-web-mcp init --runner uvx
```

非 `uvx` 安装，并且 `cc-web-mcp` 已经在 `PATH` 中时，才使用本地命令：

```powershell
cc-web-mcp init
```

这个命令会完成四件事：

- 创建用户配置文件。
- 注册 Claude Code 用户级 stdio MCP。普通 Python 安装会注册为当前 Python 的 `-m cc_web_mcp`；`--runner uvx` 会注册为 `uvx cc-web-mcp`。
- 写入用户级 `~\.claude\CLAUDE.md` 路由提示。
- 合并更新用户级 `~\.claude\settings.json` hook 守卫，并在写入前备份。

先预览、不改文件：

```powershell
uvx cc-web-mcp init --runner uvx --dry-run
```

非 `uvx` 安装且 `cc-web-mcp` 已在 `PATH` 中时，也可以用本地命令预览：

```powershell
cc-web-mcp init --dry-run
```

不注册 MCP，只写配置和 hook。普通用户继续使用 `uvx`：

```powershell
uvx cc-web-mcp init --runner uvx --skip-mcp
```

非 `uvx` 安装且 `cc-web-mcp` 已在 `PATH` 中时，也可以写成：

```powershell
cc-web-mcp init --skip-mcp
```

刷新已存在的 cc-web hook：

```powershell
uvx cc-web-mcp init --runner uvx --force
```

刷新为带 PDF 可选依赖的 uvx 注册：

```powershell
uvx cc-web-mcp init --runner uvx --with-pdf --force
```

## 本地诊断

推荐的 `uvx` 安装方式不会把 `cc-web-mcp.exe` 放进你的 `PATH`，所以普通用户请这样诊断：

```powershell
uvx cc-web-mcp doctor
```

只看 JSON，且跳过真实网络访问：

```powershell
uvx cc-web-mcp doctor --json --skip-network
```

如果你使用的是 `pipx`，或者 `cc-web-mcp` 已经在 `PATH` 中，可以使用本地命令：

```powershell
cc-web-mcp doctor
```

如果是普通 `pip` / editable install，且 `cc-web-mcp` 命令不在 `PATH` 中，使用模块形式：

```powershell
py -3.11 -m cc_web_mcp doctor
```

本地命令也支持 JSON 和跳过网络：

```powershell
cc-web-mcp doctor --json --skip-network
```

如果本地命令不在 `PATH` 中，对应的模块形式是：

```powershell
py -3.11 -m cc_web_mcp doctor --json --skip-network
```

确认 Claude Code MCP 注册：

```powershell
claude mcp get cc-web
```

## 配置文件

查看当前配置路径。普通用户优先使用 `uvx`：

```powershell
uvx cc-web-mcp config path
```

非 `uvx` 安装且 `cc-web-mcp` 已在 `PATH` 中时，也可以写成：

```powershell
cc-web-mcp config path
```

只初始化配置文件，不写 Claude Code。普通用户优先使用 `uvx`：

```powershell
uvx cc-web-mcp config init
```

非 `uvx` 安装且 `cc-web-mcp` 已在 `PATH` 中时，也可以写成：

```powershell
cc-web-mcp config init
```

显示当前配置内容。普通用户优先使用 `uvx`：

```powershell
uvx cc-web-mcp config show
```

非 `uvx` 安装且 `cc-web-mcp` 已在 `PATH` 中时，也可以写成：

```powershell
cc-web-mcp config show
```

默认配置路径：

- Windows：`%APPDATA%\cc-web-mcp\config.json`
- macOS/Linux：`~/.config/cc-web-mcp/config.json`

也可以通过环境变量覆盖：

```powershell
$env:CC_WEB_MCP_CONFIG="D:\path\to\config.json"
uvx cc-web-mcp doctor
```

如果是普通 `pip` / editable install 且本地命令不在 `PATH` 中，环境变量同样适用于模块形式：

```powershell
$env:CC_WEB_MCP_CONFIG="D:\path\to\config.json"
py -3.11 -m cc_web_mcp doctor
```

## 旧脚本兼容

`scripts/install_instructions.py`、`scripts/install_hook.py` 和 `scripts/doctor.py` 现在只是兼容包装。新安装和日常维护请使用：

```powershell
uvx cc-web-mcp init --runner uvx
uvx cc-web-mcp doctor
```

## 开发测试

```powershell
py -3.11 -m pip install -e .
py -3.11 -m pytest .\tests -q
```
