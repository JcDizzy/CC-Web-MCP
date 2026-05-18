# 安全说明

- 这是只读工具链，不执行网页写入操作。
- `fetch_url` 默认只允许 `http/https`，并禁止本机、内网、链路本地地址和云 metadata 地址。
- URL 安全校验会同时检查原始主机名和 DNS 解析后的 IP，避免公开域名解析到私网、本机地址或 `198.18.0.0/15` 代理测试网段。
- 如果本机透明代理确实让可信公开域名解析到 `198.18.0.0/15`，可以用 `trusted_proxy_domains` 精确放行这些域名；该例外不会放行本机、内网或云 metadata 地址。
- 30x 重定向后的目标 URL 会再次校验，避免公网 URL 跳转到内网地址。
- `research_brief` 在抓取搜索结果前会过滤非法 URL，并在返回里记录 `skipped_results`。
- Jina Reader fallback 也会重复执行 URL 安全校验；默认禁止内网 URL 走 Jina。
- URL 正文抓取缓存只在 `allow_private_networks: false` 时启用，并且缓存 key 包含 schema version，避免旧格式缓存污染新逻辑。
- 搜索短缓存只保存成功结果，不缓存失败、限流或全部后端不可用的响应；它独立于 `allow_private_networks`，因为搜索缓存不抓取用户提供的任意 URL。
- Jina Reader fallback 结果不会写入原 URL 的直接抓取缓存，避免临时 fallback 掩盖后续恢复的原站点内容。
- `allow_private_networks: true` 只建议在可信内网文档场景临时开启。
- 当前不包含 Playwright 或浏览器自动化，不处理重 JavaScript、登录墙、验证码页面。
- 对疑似反爬页面，cc-web 只做诊断和降级提示，不尝试绕过网站访问控制。
- 启用 Jina Reader fallback 时，目标 URL 会经过第三方服务；不要用于私密链接或内网页面。
