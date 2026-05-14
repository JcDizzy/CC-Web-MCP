import logging

from mcp import types
from mcp.server.fastmcp import Context, FastMCP

from web import check_health, fetch_page, research_brief as build_research_brief, search_web, to_json_text


logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


mcp = FastMCP(
    "cc-web",
    instructions=(
        "cc-web 主要用于 DeepSeek、Qwen、Kimi 等缺少 Claude Code 原生 WebSearch/WebFetch 能力的第三方模型。"
        "官方 Claude 模型应优先使用内置 WebSearch/WebFetch，不要主动使用 cc-web。"
        "只有用户显式要求 cc-web，或配置 allow_fetch_url_for_claude=true 时，官方 Claude 才可使用 fetch_url。"
    ),
)


async def _send_progress(ctx: Context | None, progress: int, total: int, message: str | None = None) -> None:
    if ctx is None:
        return
    sent = False
    try:
        request_context = ctx.request_context
        progress_token = request_context.meta.progressToken if request_context.meta else None
        if progress_token is not None:
            params = types.ProgressNotificationParams(
                progressToken=progress_token,
                progress=progress,
                total=total,
                message=message,
            )
            notification = types.ServerNotification(
                types.ProgressNotification(method="notifications/progress", params=params)
            )
            await request_context.session.send_notification(notification, ctx.request_id)
            sent = True
    except Exception:
        pass
    if not sent:
        try:
            await ctx.report_progress(progress, total)
        except Exception:
            pass


def _progress_callback(ctx: Context | None, total: int = 100):
    step = 0

    async def callback(message: str) -> None:
        nonlocal step
        if ctx is None:
            return
        step = min(total - 1, step + 10)
        try:
            await ctx.info(message)
        except Exception:
            pass
        await _send_progress(ctx, step, total, message)

    return callback


async def _finish_progress(ctx: Context | None) -> None:
    await _send_progress(ctx, 100, 100, "cc-web: done")


@mcp.tool()
async def web_search(query: str, max_results: int = 5, region: str = "wt-wt", language: str = "zh-cn", ctx: Context = None) -> str:
    """仅供缺少原生 WebSearch 的第三方模型搜索公开网页；官方 Claude 应使用内置 WebSearch。"""
    result = await search_web(query, max_results, region, language, status_callback=_progress_callback(ctx))
    await _finish_progress(ctx)
    return to_json_text(result)


@mcp.tool()
async def fetch_url(
    url: str,
    max_chars: int | None = None,
    start_index: int = 0,
    extract_mode: str = "auto",
    ctx: Context = None,
) -> str:
    """抓取 http/https URL 正文并转为 Markdown；官方 Claude 默认应使用内置 WebFetch，除非用户显式要求 cc-web 或配置允许。"""
    result = await fetch_page(url, max_chars, start_index, extract_mode, status_callback=_progress_callback(ctx))
    await _finish_progress(ctx)
    return to_json_text(result)


@mcp.tool()
async def research_brief(
    query: str,
    max_sources: int = 3,
    max_chars_per_source: int | None = None,
    region: str = "wt-wt",
    language: str = "zh-cn",
    ctx: Context = None,
) -> str:
    """仅供缺少原生 WebSearch/WebFetch 的第三方模型做上下文友好的资料概览；官方 Claude 应使用内置工具。"""
    result = await build_research_brief(
        query,
        max_sources,
        max_chars_per_source,
        region,
        language,
        status_callback=_progress_callback(ctx),
    )
    await _finish_progress(ctx)
    return to_json_text(result)


@mcp.tool()
async def health_check() -> str:
    """检查 MCP 依赖、配置和网络连通性。"""
    return to_json_text(await check_health())


if __name__ == "__main__":
    mcp.run("stdio")
