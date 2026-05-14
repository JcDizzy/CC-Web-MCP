from __future__ import annotations

import asyncio
import hashlib
import inspect
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 GlobalWebMCP/1.1"
)
MAX_DOWNLOAD_BYTES = 5_000_000
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=8.0, read=15.0)
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "cc-web-mcp"
CACHE_SCHEMA_VERSION = 3
BING_CN_SCOPE_NOTE = "bing_cn may be region-biased and is used as fallback; it is not equivalent to full global search."
ANTI_BOT_DOMAINS = (
    "zhihu.com",
    "weixin.qq.com",
    "x.com",
    "twitter.com",
    "reddit.com",
)
CHALLENGE_PATH_HINTS = (
    "/account/unhuman",
    "/captcha",
    "/challenge",
    "/security",
    "/verify",
)
LOGIN_PATH_HINTS = (
    "/login",
    "/signin",
    "/sign_in",
    "/auth",
)
CHALLENGE_KEYWORDS = (
    "安全验证",
    "访问异常",
    "验证码",
    "请完成验证",
    "人机验证",
    "verify you are human",
    "are you a human",
    "unusual traffic",
    "just a moment",
    "attention required",
    "checking your browser",
)
LOGIN_KEYWORDS = (
    "登录后查看",
    "请登录",
    "login required",
    "sign in to continue",
)
JS_REQUIRED_KEYWORDS = (
    "enable javascript",
    "requires javascript",
    "请启用 javascript",
    "请启用js",
)
BLOCKED_IP_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "127.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


class FetchSafetyError(ValueError):
    pass


class FetchDiagnosticError(FetchSafetyError):
    def __init__(self, message: str, diagnostics: dict[str, Any]):
        super().__init__(message)
        self.diagnostics = diagnostics


StatusCallback = Callable[[str], Awaitable[None] | None]


class StatusRecorder:
    def __init__(self, callback: StatusCallback | None = None):
        self.callback = callback
        self.steps: list[dict[str, str]] = []

    async def add(self, message: str) -> None:
        message = _clean_text(message)
        if not message:
            return
        self.steps.append({"message": message, "at": now_iso()})
        if self.callback:
            maybe_awaitable = self.callback(message)
            if maybe_awaitable:
                await maybe_awaitable

    def summary(self, fallback: str = "") -> str:
        if fallback:
            return fallback
        if self.steps:
            return self.steps[-1]["message"]
        return ""


async def _call_with_optional_status(fn: Callable[..., Any], *args: Any, status_callback: StatusCallback | None = None, **kwargs: Any) -> Any:
    if status_callback is not None:
        try:
            signature = inspect.signature(fn)
            if "status_callback" in signature.parameters:
                kwargs["status_callback"] = status_callback
        except (TypeError, ValueError):
            kwargs["status_callback"] = status_callback
    return await fn(*args, **kwargs)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class GlobalWebConfig:
    allowed_model_patterns: tuple[str, ...] = ("deepseek",)
    search_provider: str = "duckduckgo"
    search_providers: tuple[str, ...] = ("duckduckgo", "bing_cn")
    allow_fetch_url_for_claude: bool = False
    searxng_base_url: str = ""
    prefer_technical_sources: bool = True
    default_fetch_chars: int = 10_000
    max_fetch_chars: int = 60_000
    max_search_results: int = 10
    max_brief_sources: int = 3
    brief_chars_per_source: int = 2_500
    enable_jina_fallback: bool = True
    jina_min_chars: int = 300
    allow_private_networks: bool = False
    cache_ttl_seconds: int = 1_800
    cache_dir: str = str(DEFAULT_CACHE_DIR)
    brief_concurrency: int = 3
    dedupe_domains: bool = True
    enable_pdf_extract: bool = False


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _cfg(config: Any, name: str, default: Any) -> Any:
    return getattr(config, name, default)


def _normalize_search_provider_name(provider: Any) -> str:
    normalized = str(provider or "").strip().lower().replace("-", "_")
    aliases = {
        "ddg": "duckduckgo",
        "duckduckgo_html": "duckduckgo",
        "bing": "bing_cn",
        "bingcn": "bing_cn",
        "bing_china": "bing_cn",
    }
    return aliases.get(normalized, normalized)


def _normalize_search_providers(raw_providers: Any, default_provider: str = "duckduckgo") -> tuple[str, ...]:
    if isinstance(raw_providers, str):
        items = [raw_providers]
    elif isinstance(raw_providers, (list, tuple)):
        items = list(raw_providers)
    else:
        default = _normalize_search_provider_name(default_provider)
        items = ["duckduckgo", "bing_cn"] if default == "duckduckgo" else [default]

    providers: list[str] = []
    for item in items:
        provider = _normalize_search_provider_name(item)
        if provider and provider not in providers:
            providers.append(provider)
    return tuple(providers or ("duckduckgo", "bing_cn"))


def load_config(path: str | Path | None = None) -> GlobalWebConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    try:
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}

    patterns = raw.get("allowed_model_patterns", ["deepseek"])
    if not isinstance(patterns, list):
        patterns = ["deepseek"]
    allowed_model_patterns = tuple(
        str(item).strip().lower() for item in patterns if str(item).strip()
    ) or ("deepseek",)

    return GlobalWebConfig(
        allowed_model_patterns=allowed_model_patterns,
        search_provider=_normalize_search_provider_name(raw.get("search_provider") or "duckduckgo"),
        search_providers=_normalize_search_providers(raw.get("search_providers"), raw.get("search_provider") or "duckduckgo"),
        allow_fetch_url_for_claude=bool(raw.get("allow_fetch_url_for_claude", False)),
        searxng_base_url=str(raw.get("searxng_base_url") or "").strip().rstrip("/"),
        prefer_technical_sources=bool(raw.get("prefer_technical_sources", True)),
        default_fetch_chars=_bounded_int(raw.get("default_fetch_chars"), 10_000, 1_000, 60_000),
        max_fetch_chars=_bounded_int(raw.get("max_fetch_chars"), 60_000, 1_000, 120_000),
        max_search_results=_bounded_int(raw.get("max_search_results"), 10, 1, 20),
        max_brief_sources=_bounded_int(raw.get("max_brief_sources"), 3, 1, 5),
        brief_chars_per_source=_bounded_int(raw.get("brief_chars_per_source"), 2_500, 100, 20_000),
        enable_jina_fallback=bool(raw.get("enable_jina_fallback", True)),
        jina_min_chars=_bounded_int(raw.get("jina_min_chars"), 300, 0, 5_000),
        allow_private_networks=bool(raw.get("allow_private_networks", False)),
        cache_ttl_seconds=_bounded_int(raw.get("cache_ttl_seconds"), 1_800, 0, 86_400),
        cache_dir=str(raw.get("cache_dir") or DEFAULT_CACHE_DIR),
        brief_concurrency=_bounded_int(raw.get("brief_concurrency"), 3, 1, 5),
        dedupe_domains=bool(raw.get("dedupe_domains", True)),
        enable_pdf_extract=bool(raw.get("enable_pdf_extract", False)),
    )


def config_to_dict(config: GlobalWebConfig) -> dict[str, Any]:
    return {
        "allowed_model_patterns": list(config.allowed_model_patterns),
        "search_provider": config.search_provider,
        "search_providers": list(config.search_providers),
        "allow_fetch_url_for_claude": config.allow_fetch_url_for_claude,
        "searxng_base_url": config.searxng_base_url,
        "prefer_technical_sources": config.prefer_technical_sources,
        "default_fetch_chars": config.default_fetch_chars,
        "max_fetch_chars": config.max_fetch_chars,
        "max_search_results": config.max_search_results,
        "max_brief_sources": config.max_brief_sources,
        "brief_chars_per_source": config.brief_chars_per_source,
        "enable_jina_fallback": config.enable_jina_fallback,
        "jina_min_chars": config.jina_min_chars,
        "allow_private_networks": config.allow_private_networks,
        "cache_ttl_seconds": config.cache_ttl_seconds,
        "cache_dir": config.cache_dir,
        "brief_concurrency": config.brief_concurrency,
        "dedupe_domains": config.dedupe_domains,
        "enable_pdf_extract": config.enable_pdf_extract,
    }


def model_matches_patterns(model: str | None, patterns: tuple[str, ...] | list[str] | None) -> bool:
    normalized = (model or "").lower()
    return any(pattern and pattern.lower() in normalized for pattern in (patterns or ()))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_private_host(host: str) -> bool:
    normalized = (host or "").strip().strip("[]").lower().rstrip(".")
    if not normalized:
        return False
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        if getattr(ip, "ipv4_mapped", None) is not None:
            ip = ip.ipv4_mapped
        return any(ip in network for network in BLOCKED_IP_NETWORKS)
    except ValueError:
        return False


def _resolved_private_hosts(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    private_ips: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip = str(sockaddr[0])
        if _is_private_host(ip) and ip not in private_ips:
            private_ips.append(ip)
    return private_ips


def validate_fetch_url(
    url: str,
    allow_private_networks: bool = False,
    resolve_dns: bool = True,
) -> str:
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise FetchSafetyError("仅允许抓取 http/https URL")
    if not parsed.netloc:
        raise FetchSafetyError("URL 缺少主机名")
    hostname = parsed.hostname or ""
    if not allow_private_networks and _is_private_host(hostname):
        raise FetchSafetyError("默认禁止抓取本机、内网、链路本地或云 metadata 地址")
    if not allow_private_networks and resolve_dns:
        private_ips = _resolved_private_hosts(hostname)
        if private_ips:
            raise FetchSafetyError(f"域名解析到受限地址，已阻止抓取: {', '.join(private_ips)}")
    return cleaned


async def validate_fetch_url_async(
    url: str,
    allow_private_networks: bool = False,
    resolve_dns: bool = True,
) -> str:
    cleaned = validate_fetch_url(url, allow_private_networks=allow_private_networks, resolve_dns=False)
    if not allow_private_networks and resolve_dns:
        hostname = urlparse(cleaned).hostname or ""
        private_ips = await asyncio.to_thread(_resolved_private_hosts, hostname)
        if private_ips:
            raise FetchSafetyError(f"域名解析到受限地址，已阻止抓取: {', '.join(private_ips)}")
    return cleaned


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
    }


def _duckduckgo_result_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if "duckduckgo.com" in parsed.netloc.lower() and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        if query.get("uddg"):
            return unquote(query["uddg"][0])
    return raw_url


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_multiline(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    return "\n\n".join(lines)


def normalize_search_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []

    anchors = soup.select("a.result__a")
    for anchor in anchors:
        title = _clean_text(anchor.get_text(" "))
        href = anchor.get("href") or ""
        if not title or not href:
            continue

        snippet = ""
        parent = anchor.find_parent(class_=re.compile(r"result"))
        if parent:
            snippet_node = parent.select_one(".result__snippet")
            if snippet_node:
                snippet = _clean_text(snippet_node.get_text(" "))

        if not snippet:
            next_snippet = anchor.find_next(class_="result__snippet")
            if next_snippet:
                snippet = _clean_text(next_snippet.get_text(" "))

        results.append(SearchResult(title=title, url=_duckduckgo_result_url(href), snippet=snippet))
        if len(results) >= max_results:
            break

    return [result.__dict__ for result in results]


def normalize_searxng_results(payload: dict[str, Any], max_results: int = 5) -> list[dict[str, str]]:
    results: list[SearchResult] = []
    for item in payload.get("results", []):
        title = _clean_text(str(item.get("title") or ""))
        url = str(item.get("url") or "").strip()
        snippet = _clean_text(str(item.get("content") or item.get("snippet") or ""))
        if not title or not url:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return [result.__dict__ for result in results]


def normalize_bing_cn_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []

    for item in soup.select("li.b_algo"):
        anchor = item.select_one("h2 a[href]") or item.select_one("a[href]")
        if not anchor:
            continue
        title = _clean_text(anchor.get_text(" "))
        url = str(anchor.get("href") or "").strip()
        if not title or not url:
            continue

        snippet = ""
        snippet_node = item.select_one(".b_caption p") or item.select_one("p")
        if snippet_node:
            snippet = _clean_text(snippet_node.get_text(" "))

        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break

    return [result.__dict__ for result in results]


def _technical_source_score(url: str) -> int:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower()
    score = 0
    if host == "github.com" or host.endswith(".github.com"):
        score += 65
    if host.startswith("docs.") or ".docs." in host or "readthedocs.io" in host:
        score += 40
    if host in {"pypi.org", "www.npmjs.com", "crates.io", "pkg.go.dev"}:
        score += 35
    if host in {"stackoverflow.com", "developer.mozilla.org"}:
        score += 30
    if any(part in host for part in ("docs", "developer", "dev", "api")):
        score += 15
    if any(part in path for part in ("/docs", "/documentation", "/guide", "/reference", "/api")):
        score += 10
    if any(bad in host for bad in ("blogspot.", "medium.com", "csdn.", "51cto.", "jianshu.")):
        score -= 15
    return score


def rank_search_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    ranked = list(results)
    scores = {id(item): _technical_source_score(item.get("url", "")) for item in ranked}

    for index in range(1, len(ranked)):
        current = ranked[index]
        current_score = scores[id(current)]
        if current_score <= 0:
            continue
        max_shift = 2 if current_score >= 60 else 1
        new_index = index
        while new_index > 0 and index - new_index < max_shift:
            previous = ranked[new_index - 1]
            previous_score = scores[id(previous)]
            if current_score - previous_score < 30:
                break
            new_index -= 1
        if new_index != index:
            ranked.pop(index)
            ranked.insert(new_index, current)

    return ranked


def _provider_backend_name(provider: str) -> str:
    normalized = _normalize_search_provider_name(provider)
    if normalized == "duckduckgo":
        return "duckduckgo_html"
    return normalized


def _search_backend_health_url(provider: str, config: GlobalWebConfig | Any) -> tuple[str, str]:
    """Return the normalized backend name and a lightweight health-check URL."""
    provider = _normalize_search_provider_name(provider)
    if provider == "searxng":
        base_url = _cfg(config, "searxng_base_url", "").rstrip("/")
        if not base_url:
            raise ValueError("searxng_base_url 不能为空")
        return provider, f"{base_url}/search"
    if provider == "bing_cn":
        return provider, "https://cn.bing.com/"
    if provider == "duckduckgo":
        return provider, "https://duckduckgo.com/"
    raise ValueError(f"不支持的搜索后端: {provider}")


async def _search_with_provider(
    provider: str,
    query: str,
    max_results: int,
    region: str,
    language: str,
    config: GlobalWebConfig | Any,
) -> tuple[str, list[dict[str, str]]]:
    provider = _normalize_search_provider_name(provider)

    if provider == "searxng":
        base_url = _cfg(config, "searxng_base_url", "").rstrip("/")
        if not base_url:
            raise ValueError("searxng_base_url 不能为空")
        async with httpx.AsyncClient(headers=_headers(), timeout=REQUEST_TIMEOUT, max_redirects=5) as client:
            response = await client.get(
                f"{base_url}/search",
                params={"q": query, "format": "json", "language": language or "zh-cn"},
                follow_redirects=True,
            )
            response.raise_for_status()
            return "searxng", normalize_searxng_results(response.json(), max_results=max_results)

    if provider == "bing_cn":
        async with httpx.AsyncClient(
            headers={**_headers(), "Accept-Language": language or "zh-cn"},
            timeout=REQUEST_TIMEOUT,
            max_redirects=5,
        ) as client:
            response = await client.get(
                "https://cn.bing.com/search",
                params={"q": query, "ensearch": "1", "cc": "cn", "setlang": language or "zh-cn"},
                follow_redirects=True,
            )
            response.raise_for_status()
            return "bing_cn", normalize_bing_cn_results(response.text, max_results=max_results)

    if provider == "duckduckgo":
        async with httpx.AsyncClient(
            headers={**_headers(), "Accept-Language": language or "zh-cn"},
            timeout=REQUEST_TIMEOUT,
            max_redirects=5,
        ) as client:
            response = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": region or "wt-wt"},
                follow_redirects=True,
            )
            response.raise_for_status()
            return "duckduckgo_html", normalize_search_results(response.text, max_results=max_results)

    raise ValueError(f"不支持的搜索后端: {provider}")


def _best_content_node(soup: BeautifulSoup):
    for selector in ("main", "article", "[role=main]", ".content", "#content"):
        node = soup.select_one(selector)
        if node and _clean_text(node.get_text(" ")):
            return node
    return soup.body or soup


def _absolute_links(soup: BeautifulSoup, base_url: str) -> None:
    if not base_url:
        return
    for node in soup.find_all("a"):
        href = node.get("href")
        if href:
            node["href"] = urljoin(base_url, href)


def _domain_matches(host: str, domains: tuple[str, ...]) -> bool:
    normalized = (host or "").lower().strip(".")
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in domains)


def _add_signal(signals: list[str], signal: str) -> None:
    if signal and signal not in signals:
        signals.append(signal)


def _extract_html_title(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    if soup.title:
        return _clean_text(soup.title.get_text(" "))
    return ""


def _safe_response_text(response: httpx.Response, limit: int = 5000) -> str:
    try:
        if not response.content:
            return ""
        return response.text[:limit]
    except httpx.ResponseNotRead:
        return ""


def _diagnostics_response(
    issue_type: str,
    confidence: str,
    signals: list[str],
) -> dict[str, Any]:
    recommendation = "抓取失败原因不明确；建议稍后重试，或换用搜索结果摘要和其他来源。"
    if issue_type in {"captcha_or_challenge", "blocked_or_waf", "login_required", "timeout_suspected_antibot"}:
        recommendation = "目标站点疑似启用了反爬、人机验证或登录墙；建议改用搜索摘要、官方来源或其他可访问来源。"
    elif issue_type == "js_required":
        recommendation = "目标页面可能需要浏览器渲染；当前轻量 HTTP 抓取不支持重型浏览器模式，建议换用可访问来源。"
    elif issue_type == "network_timeout":
        recommendation = "请求超时；建议稍后重试，或改用搜索摘要和其他来源。"
    return {
        "type": issue_type,
        "confidence": confidence,
        "signals": signals,
        "recommendation": recommendation,
    }


def _fetch_failure_guidance(error_type: str, recommendation: str | None = None) -> dict[str, Any]:
    if error_type == "network_timeout":
        return {
            "retryable": True,
            "retry_after_seconds": 30,
            "do_not_retry_reason": "Transient timeout; do not repeat immediately with the same URL.",
            "recommended_next_action": recommendation
            or "Retry later, run health_check if failures persist, or use research_brief/search results.",
        }

    if error_type == "fetch_safety":
        return {
            "retryable": False,
            "do_not_retry_reason": "Blocked by fetch safety policy; do not retry the same URL.",
            "recommended_next_action": recommendation or "Use an absolute http/https URL from a public source.",
        }

    if error_type in {"captcha_or_challenge", "blocked_or_waf", "login_required", "timeout_suspected_antibot", "js_required"}:
        return {
            "retryable": False,
            "do_not_retry_reason": f"Target returned {error_type}; repeating fetch_url with the same URL is unlikely to help.",
            "recommended_next_action": recommendation or "Use search summaries, official sources, or another accessible source.",
        }

    return {
        "retryable": False,
        "do_not_retry_reason": "Fetch failed; do not repeat the identical call unless the URL or parameters change.",
        "recommended_next_action": recommendation or "Try research_brief, use another source, or narrow the request.",
    }


def _diagnose_fetch_response(requested_url: str, response: httpx.Response, markdown: str = "") -> dict[str, Any] | None:
    final_url = str(response.url or requested_url)
    parsed = urlparse(final_url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    status_code = response.status_code
    text_sample = _safe_response_text(response)
    title = _extract_html_title(text_sample)
    haystack = " ".join([requested_url, final_url, title, text_sample[:3000], markdown[:1000]]).lower()
    signals: list[str] = []

    if status_code in {401, 403, 429, 503}:
        _add_signal(signals, f"status_code={status_code}")
    if status_code == 403:
        _add_signal(signals, "forbidden")
    if status_code == 429:
        _add_signal(signals, "rate_limited")
    if _domain_matches(host, ANTI_BOT_DOMAINS):
        _add_signal(signals, f"known anti-bot domain: {host}")
    for hint in CHALLENGE_PATH_HINTS:
        if hint in path:
            _add_signal(signals, f"challenge path: {hint}")
    for hint in LOGIN_PATH_HINTS:
        if hint in path:
            _add_signal(signals, f"login path: {hint}")
    for keyword in CHALLENGE_KEYWORDS:
        if keyword.lower() in haystack:
            _add_signal(signals, f"challenge keyword: {keyword}")
    for keyword in LOGIN_KEYWORDS:
        if keyword.lower() in haystack:
            _add_signal(signals, f"login keyword: {keyword}")
    for keyword in JS_REQUIRED_KEYWORDS:
        if keyword.lower() in haystack:
            _add_signal(signals, f"js keyword: {keyword}")

    if any(signal.startswith("challenge ") for signal in signals):
        return _diagnostics_response("captcha_or_challenge", "high", signals)
    if any(signal.startswith("login ") for signal in signals):
        return _diagnostics_response("login_required", "high", signals)
    if status_code in {403, 429}:
        confidence = "high" if _domain_matches(host, ANTI_BOT_DOMAINS) else "medium"
        return _diagnostics_response("blocked_or_waf", confidence, signals)
    if status_code in {401}:
        return _diagnostics_response("login_required", "medium", signals)
    if any(signal.startswith("js keyword") for signal in signals):
        return _diagnostics_response("js_required", "medium", signals)
    if markdown != "" and len(_clean_text(markdown)) < 200 and _domain_matches(host, ANTI_BOT_DOMAINS):
        _add_signal(signals, f"short extracted content: {len(_clean_text(markdown))} chars")
        return _diagnostics_response("captcha_or_challenge", "medium", signals)
    return None


def _diagnose_fetch_exception(url: str, exc: Exception) -> dict[str, Any] | None:
    if isinstance(exc, FetchDiagnosticError):
        return exc.diagnostics
    if isinstance(exc, httpx.HTTPStatusError):
        return _diagnose_fetch_response(url, exc.response)
    if isinstance(exc, (httpx.ReadTimeout, httpx.TimeoutException)):
        host = (urlparse(url).hostname or "").lower()
        signals = [f"{type(exc).__name__}: {exc}"]
        if _domain_matches(host, ANTI_BOT_DOMAINS):
            _add_signal(signals, f"known anti-bot domain: {host}")
            return _diagnostics_response("timeout_suspected_antibot", "medium", signals)
        return _diagnostics_response("network_timeout", "low", signals)
    return None


def extract_markdown(html: str, base_url: str = "", extract_mode: str = "auto") -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "template", "svg"]):
        node.decompose()
    _absolute_links(soup, base_url)

    mode = (extract_mode or "auto").lower()
    if mode == "text":
        return _clean_multiline(soup.get_text("\n"))

    content_node = soup.body or soup if mode == "body" else _best_content_node(soup)
    markdown = html_to_markdown(str(content_node), heading_style="ATX", strip=["img"])
    return _clean_multiline(markdown)


def slice_text_window(text: str, max_chars: int, start_index: int = 0) -> dict[str, Any]:
    content_length = len(text)
    start = max(0, min(int(start_index or 0), content_length))
    end = min(start + max(1, int(max_chars or 1)), content_length)
    truncated = end < content_length
    return {
        "text": text[start:end].rstrip(),
        "content_length": content_length,
        "returned_range": {"start": start, "end": end},
        "truncated": truncated,
        "next_start_index": end if truncated else None,
    }


def _truncation_guidance(url: str, max_chars: int, extract_mode: str, window: dict[str, Any]) -> dict[str, Any] | None:
    if not window.get("truncated"):
        return None
    next_start = window.get("next_start_index")
    remaining = max(0, int(window.get("content_length", 0)) - int(next_start or 0))
    return {
        "remaining_chars": remaining,
        "do_not_retry_reason": "Do not repeat fetch_url with the same start_index; continue from next_start_index.",
        "next_call": {
            "tool": "fetch_url",
            "url": url,
            "max_chars": max_chars,
            "start_index": next_start,
            "extract_mode": extract_mode,
        },
    }


async def _limited_get(
    client: httpx.AsyncClient,
    url: str,
    allow_private_networks: bool = False,
) -> httpx.Response:
    current_url = await validate_fetch_url_async(url, allow_private_networks=allow_private_networks)
    for _ in range(6):
        async with client.stream("GET", current_url, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    response.raise_for_status()
                current_url = await validate_fetch_url_async(
                    urljoin(str(response.url), location),
                    allow_private_networks=allow_private_networks,
                )
                continue

            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise FetchSafetyError("页面过大，已停止下载")
                chunks.append(chunk)
            full_response = httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=b"".join(chunks),
                request=response.request,
                extensions=response.extensions,
            )
            full_response.raise_for_status()
            return full_response
    raise FetchSafetyError("重定向次数过多，已停止抓取")


async def _fetch_jina_reader_markdown(
    client: httpx.AsyncClient,
    url: str,
) -> dict[str, str]:
    safe_url = await validate_fetch_url_async(url, allow_private_networks=False)
    # Jina Reader 的公开用法是给原 URL 加前缀：https://r.jina.ai/https://example.com
    reader_url = f"https://r.jina.ai/{safe_url}"
    response = await client.get(reader_url, follow_redirects=True)
    response.raise_for_status()
    return {"markdown": _clean_multiline(response.text), "reader_url": str(response.url)}


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise FetchSafetyError("PDF 提取需要安装可选依赖 pypdf") from exc

    try:
        import io

        reader = PdfReader(io.BytesIO(content))
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = _clean_multiline("\n".join(pages))
    except Exception as exc:
        raise FetchSafetyError(f"PDF 提取失败: {type(exc).__name__}: {exc}") from exc
    if not text:
        raise FetchSafetyError("PDF 未提取到可读文本")
    return text


def _format_response_content(response: httpx.Response, extract_mode: str, config: GlobalWebConfig | Any | None = None) -> str:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type in {"text/html", "application/xhtml+xml"} or not content_type:
        return extract_markdown(response.text, str(response.url), extract_mode=extract_mode)
    if content_type in {"text/plain", "text/markdown", "text/x-markdown"}:
        return _clean_multiline(response.text)
    if content_type in {"application/json", "application/ld+json"} or content_type.endswith("+json"):
        try:
            return json.dumps(response.json(), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return _clean_multiline(response.text)
    if content_type == "application/pdf":
        if _cfg(config, "enable_pdf_extract", False):
            return _extract_pdf_text(response.content)
        raise FetchSafetyError("暂不支持 PDF 正文提取，请后续接入 PDF 提取工具")
    if not content_type.startswith("text/"):
        raise FetchSafetyError(f"拒绝抓取二进制或暂不支持的内容类型: {content_type or 'unknown'}")
    return _clean_multiline(response.text)


def _cache_key(
    url: str,
    extract_mode: str,
    backend_hint: str = "direct",
    schema_version: int = CACHE_SCHEMA_VERSION,
) -> str:
    raw = json.dumps(
        {
            "schema_version": schema_version,
            "url": url,
            "extract_mode": extract_mode,
            "backend": backend_hint,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(config: GlobalWebConfig, key: str) -> Path:
    return Path(config.cache_dir) / f"{key}.json"


def _read_cache(config: GlobalWebConfig, key: str) -> dict[str, Any] | None:
    if _cfg(config, "cache_ttl_seconds", 0) <= 0 or _cfg(config, "allow_private_networks", False):
        return None
    path = _cache_path(config, key)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(data.get("cached_at", 0))
        if datetime.now(timezone.utc).timestamp() - fetched_at > _cfg(config, "cache_ttl_seconds", 0):
            return None
        return data
    except Exception:
        return None


def _write_cache(config: GlobalWebConfig, key: str, data: dict[str, Any]) -> None:
    if _cfg(config, "cache_ttl_seconds", 0) <= 0 or _cfg(config, "allow_private_networks", False):
        return
    try:
        path = _cache_path(config, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {**data, "cached_at": datetime.now(timezone.utc).timestamp()}
        path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


async def search_web(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
    language: str = "zh-cn",
    config: GlobalWebConfig | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    status = StatusRecorder(status_callback)
    query = _clean_text(query)
    if not query:
        await status.add("cc-web: search query is empty")
        return {
            "ok": False,
            "error": "query 不能为空",
            "error_type": "invalid_query",
            "status_summary": "search failed: empty query",
            "steps": status.steps,
            "retryable": False,
            "do_not_retry_reason": "Empty query; do not retry until a non-empty query is provided.",
            "recommended_next_action": "Provide a concise search query.",
            "results": [],
        }

    max_results = max(1, min(int(max_results or 5), config.max_search_results))
    providers = _normalize_search_providers(
        _cfg(config, "search_providers", None),
        _cfg(config, "search_provider", "duckduckgo"),
    )
    attempted_backends: list[dict[str, Any]] = []
    fallback_reason = ""
    last_error = ""

    for provider in providers:
        backend = _provider_backend_name(provider)
        try:
            await status.add(f"cc-web: searching {backend} for {query}")
            backend, results = await _search_with_provider(provider, query, max_results, region, language, config)
            attempted_backends.append({"backend": backend, "ok": True})
            await status.add(f"cc-web: {backend} returned {len(results[:max_results])} results")

            if _cfg(config, "prefer_technical_sources", True):
                results = rank_search_results(results)

            response: dict[str, Any] = {
                "ok": True,
                "query": query,
                "backend": backend,
                "status_summary": f"search complete: {len(results[:max_results])} results from {backend}",
                "steps": status.steps,
                "fetched_at": now_iso(),
                "results": results[:max_results],
                "attempted_backends": attempted_backends,
            }
            if backend == "bing_cn":
                response["search_scope_note"] = BING_CN_SCOPE_NOTE
            if fallback_reason:
                response["fallback_reason"] = fallback_reason
            return response
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            attempted_backends.append({"backend": backend, "ok": False, "error": last_error})
            await status.add(f"cc-web: {backend} failed, trying next backend")
            if not fallback_reason:
                fallback_reason = f"{backend} failed: {last_error}"

    await status.add("cc-web: all search backends failed")
    return {
        "ok": False,
        "query": query,
        "backend": _provider_backend_name(providers[-1]) if providers else "unknown",
        "status_summary": "search failed: all configured backends failed",
        "steps": status.steps,
        "fetched_at": now_iso(),
        "error": last_error or "all search providers failed",
        "fallback_reason": fallback_reason,
        "attempted_backends": attempted_backends,
        "retryable": True,
        "retry_after_seconds": 30,
        "do_not_retry_reason": "All configured search backends failed; do not repeat the same search immediately.",
        "recommended_next_action": "Run health_check to inspect search backends, retry later, or change search_providers.",
        "results": [],
    }


async def fetch_page(
    url: str,
    max_chars: int | None = None,
    start_index: int = 0,
    extract_mode: str = "auto",
    config: GlobalWebConfig | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    status = StatusRecorder(status_callback)
    try:
        safe_url = await validate_fetch_url_async(url, allow_private_networks=_cfg(config, "allow_private_networks", False))
    except FetchSafetyError as exc:
        await status.add("cc-web: fetch blocked by URL safety policy")
        result = {
            "ok": False,
            "url": url,
            "error": str(exc),
            "error_type": "fetch_safety",
            "status_summary": "fetch failed: URL safety policy",
            "steps": status.steps,
        }
        result.update(_fetch_failure_guidance("fetch_safety"))
        return result

    max_chars = max(1, min(int(max_chars or _cfg(config, "default_fetch_chars", 10_000)), _cfg(config, "max_fetch_chars", 60_000)))
    fallback_reason = ""
    reader_url = ""
    cache_key = _cache_key(safe_url, extract_mode)
    cached = _read_cache(config, cache_key)

    try:
        if cached:
            await status.add(f"cc-web: cache hit for {safe_url}")
            markdown_full = str(cached.get("markdown_full", ""))
            backend = str(cached.get("backend", "direct"))
            final_url = str(cached.get("final_url", safe_url))
            status_code = cached.get("status_code")
            content_type = str(cached.get("content_type", ""))
            reader_url = str(cached.get("reader_url", ""))
            fallback_reason = str(cached.get("fallback_reason", ""))
            cache_state = "hit"
        else:
            async with httpx.AsyncClient(headers=_headers(), timeout=REQUEST_TIMEOUT, max_redirects=5) as client:
                try:
                    await status.add(f"cc-web: fetching {safe_url}")
                    response = await _limited_get(
                        client,
                        safe_url,
                        allow_private_networks=_cfg(config, "allow_private_networks", False),
                    )
                    final_url = await validate_fetch_url_async(
                        str(response.url),
                        allow_private_networks=_cfg(config, "allow_private_networks", False),
                    )
                    content_type = response.headers.get("content-type", "")
                    await status.add(f"cc-web: extracting markdown from {safe_url}")
                    markdown_full = _format_response_content(response, extract_mode=extract_mode, config=config)
                    diagnostics = _diagnose_fetch_response(safe_url, response, markdown=markdown_full)
                    if diagnostics:
                        raise FetchDiagnosticError(diagnostics["recommendation"], diagnostics)
                    backend = "direct"
                    status_code: int | None = response.status_code

                    if _cfg(config, "enable_jina_fallback", True) and len(markdown_full) < _cfg(config, "jina_min_chars", 300):
                        fallback_reason = f"direct content too short: {len(markdown_full)} chars"
                        await status.add("cc-web: direct content too short, trying Jina Reader")
                        jina = await _fetch_jina_reader_markdown(
                            client,
                            safe_url,
                        )
                        markdown_full = jina["markdown"]
                        reader_url = jina["reader_url"]
                        backend = "jina_reader"
                        content_type = "text/markdown"
                except Exception as exc:
                    if not _cfg(config, "enable_jina_fallback", True):
                        raise
                    primary_diagnostics = _diagnose_fetch_exception(safe_url, exc)
                    fallback_reason = f"{type(exc).__name__}: {exc}"
                    await status.add("cc-web: direct fetch failed, trying Jina Reader")
                    try:
                        jina = await _fetch_jina_reader_markdown(
                            client,
                            safe_url,
                        )
                    except Exception as fallback_exc:
                        if primary_diagnostics:
                            _add_signal(
                                primary_diagnostics["signals"],
                                f"jina_fallback_failed={type(fallback_exc).__name__}: {fallback_exc}",
                            )
                            raise FetchDiagnosticError(primary_diagnostics["recommendation"], primary_diagnostics) from fallback_exc
                        raise
                    markdown_full = jina["markdown"]
                    reader_url = jina["reader_url"]
                    backend = "jina_reader"
                    final_url = safe_url
                    status_code = None
                    content_type = "text/markdown"
            cache_state = "miss"
            if backend != "jina_reader":
                _write_cache(
                    config,
                    cache_key,
                    {
                        "markdown_full": markdown_full,
                        "backend": backend,
                        "final_url": final_url,
                        "status_code": status_code,
                        "content_type": content_type,
                        "reader_url": reader_url,
                        "fallback_reason": fallback_reason,
                    },
                )

        window = slice_text_window(markdown_full, max_chars=max_chars, start_index=start_index)
        result = {
            "ok": True,
            "url": safe_url,
            "final_url": final_url,
            "backend": backend,
            "status_summary": f"fetch complete: {backend}, {window['content_length']} chars",
            "steps": status.steps,
            "status_code": status_code,
            "content_type": content_type,
            "fetched_at": now_iso(),
            "markdown": window["text"],
            "content_length": window["content_length"],
            "returned_range": window["returned_range"],
            "truncated": window["truncated"],
            "next_start_index": window["next_start_index"],
            "cache": cache_state,
        }
        if reader_url:
            result["reader_url"] = reader_url
        if fallback_reason:
            result["fallback_reason"] = fallback_reason
        truncation = _truncation_guidance(safe_url, max_chars, extract_mode, window)
        if truncation:
            result["truncation"] = truncation
        return result
    except Exception as exc:
        diagnostics = _diagnose_fetch_exception(safe_url, exc)
        error_type = diagnostics["type"] if diagnostics else "fetch_failed"
        result = {
            "ok": False,
            "url": safe_url,
            "fetched_at": now_iso(),
            "error": f"{type(exc).__name__}: {exc}",
            "error_type": error_type,
            "status_summary": f"fetch failed: {error_type}",
            "steps": status.steps,
        }
        if diagnostics:
            result["fetch_diagnostics"] = diagnostics
        result.update(_fetch_failure_guidance(error_type, diagnostics.get("recommendation") if diagnostics else None))
        return result


async def research_brief(
    query: str,
    max_sources: int = 3,
    max_chars_per_source: int | None = None,
    region: str = "wt-wt",
    language: str = "zh-cn",
    config: GlobalWebConfig | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    status = StatusRecorder(status_callback)
    max_sources = max(1, min(int(max_sources or _cfg(config, "max_brief_sources", 3)), _cfg(config, "max_brief_sources", 3)))
    max_chars_per_source = max(
        1,
        min(int(max_chars_per_source or _cfg(config, "brief_chars_per_source", 2_500)), _cfg(config, "max_fetch_chars", 60_000)),
    )

    search = await _call_with_optional_status(
        search_web,
        query,
        max_results=max(_cfg(config, "max_search_results", 10), max_sources),
        region=region,
        language=language,
        config=config,
        status_callback=status.add,
    )
    if not search.get("ok"):
        return {
            "ok": False,
            "query": query,
            "status_summary": "research brief failed: search failed",
            "steps": status.steps,
            "fetched_at": now_iso(),
            "search": search,
            "sources": [],
        }

    selected_results: list[dict[str, str]] = []
    skipped_results: list[dict[str, str]] = []
    seen_domains: set[str] = set()
    for result in search.get("results", []):
        raw_url = result.get("url", "")
        try:
            safe_url = await validate_fetch_url_async(
                raw_url,
                allow_private_networks=_cfg(config, "allow_private_networks", False),
            )
        except FetchSafetyError as exc:
            skipped_results.append(
                {
                    "title": result.get("title", ""),
                    "url": raw_url,
                    "reason": str(exc),
                }
            )
            continue
        result = {**result, "url": safe_url}
        parsed = urlparse(safe_url)
        domain = (parsed.hostname or "").lower()
        if _cfg(config, "dedupe_domains", True) and domain:
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
        selected_results.append(result)
        if len(selected_results) >= max_sources:
            break

    semaphore = asyncio.Semaphore(_cfg(config, "brief_concurrency", 3))

    async def fetch_source(index: int, result: dict[str, str]) -> dict[str, Any]:
        async with semaphore:
            await status.add(f"cc-web: fetching {index}/{len(selected_results)} {result.get('url', '')}")
            fetched = await _call_with_optional_status(
                fetch_page,
                result.get("url", ""),
                max_chars=max_chars_per_source,
                start_index=0,
                extract_mode="auto",
                config=config,
                status_callback=status.add,
            )
            source: dict[str, Any] = {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "snippet": result.get("snippet", ""),
                "ok": bool(fetched.get("ok")),
            }
            if fetched.get("ok"):
                source.update(
                    {
                        "final_url": fetched.get("final_url"),
                        "backend": fetched.get("backend"),
                        "markdown": fetched.get("markdown", ""),
                        "content_length": fetched.get("content_length"),
                        "truncated": fetched.get("truncated"),
                        "next_start_index": fetched.get("next_start_index"),
                    }
                )
                if fetched.get("truncation"):
                    source["truncation"] = fetched["truncation"]
            else:
                source["error"] = fetched.get("error", "fetch failed")
                if fetched.get("error_type"):
                    source["error_type"] = fetched.get("error_type")
                if fetched.get("fetch_diagnostics"):
                    source["fetch_diagnostics"] = fetched.get("fetch_diagnostics")
                for key in ("retryable", "retry_after_seconds", "do_not_retry_reason", "recommended_next_action"):
                    if key in fetched:
                        source[key] = fetched[key]
            return source

    sources = await asyncio.gather(*(fetch_source(index, result) for index, result in enumerate(selected_results, start=1)))

    return {
        "ok": True,
        "query": query,
        "backend": search.get("backend", "unknown"),
        "status_summary": f"research brief complete: {len(sources)} sources from {search.get('backend', 'unknown')}",
        "steps": status.steps,
        "fetched_at": now_iso(),
        "sources": sources,
        "skipped_results": skipped_results,
    }


async def check_health() -> dict[str, Any]:
    config = load_config()
    search_providers = _normalize_search_providers(
        _cfg(config, "search_providers", None),
        _cfg(config, "search_provider", "duckduckgo"),
    )
    checks: dict[str, Any] = {
        "ok": True,
        "fetched_at": now_iso(),
        "config": config_to_dict(config),
        "search_providers": list(search_providers),
        "search_backend_status": {},
        "first_available_search_backend": None,
        "dependencies": {
            "mcp": True,
            "httpx": True,
            "beautifulsoup4": True,
            "markdownify": True,
        },
        "network": {},
    }
    async with httpx.AsyncClient(headers=_headers(), timeout=REQUEST_TIMEOUT) as client:
        for provider in search_providers:
            try:
                backend, url = _search_backend_health_url(provider, config)
                response = await client.get(url, follow_redirects=True)
                status = {"ok": response.status_code < 500, "status": response.status_code}
                checks["search_backend_status"][backend] = status
                if status["ok"] and checks["first_available_search_backend"] is None:
                    checks["first_available_search_backend"] = backend
            except Exception as exc:
                backend = _normalize_search_provider_name(provider)
                checks["search_backend_status"][backend] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        for name, url in {
            "duckduckgo": "https://duckduckgo.com/",
            "bing_cn": "https://cn.bing.com/",
            "github": "https://github.com/",
            "anthropic": "https://www.anthropic.com/",
            "jina_reader": "https://r.jina.ai/https://example.com/",
        }.items():
            try:
                response = await client.get(url, follow_redirects=True)
                checks["network"][name] = {"ok": response.status_code < 500, "status": response.status_code}
            except Exception as exc:
                checks["ok"] = False
                checks["network"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return checks


def to_json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
