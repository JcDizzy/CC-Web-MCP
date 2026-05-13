import asyncio
from pathlib import Path

import httpx
import pytest

import web
from web import FetchSafetyError, extract_markdown, is_deepseek_model, normalize_search_results, validate_fetch_url


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])


def test_normalize_search_results_from_duckduckgo_html():
    html = """
    <html><body>
      <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdoc">Example Doc</a>
      <a class="result__snippet">A useful summary</a>
      <a class="result__a" href="https://example.org/other">Other Result</a>
    </body></html>
    """

    results = normalize_search_results(html, max_results=2)

    assert results == [
        {
            "title": "Example Doc",
            "url": "https://example.com/doc",
            "snippet": "A useful summary",
        },
        {
            "title": "Other Result",
            "url": "https://example.org/other",
            "snippet": "",
        },
    ]


def test_rank_search_results_prioritizes_authoritative_technical_sources():
    results = [
        {"title": "SEO 1", "url": "https://seo1.example/post", "snippet": "mirror"},
        {"title": "SEO 2", "url": "https://seo2.example/post", "snippet": "mirror"},
        {"title": "SEO 3", "url": "https://seo3.example/post", "snippet": "mirror"},
        {"title": "GitHub repo", "url": "https://github.com/modelcontextprotocol/servers", "snippet": "source"},
        {"title": "Docs", "url": "https://docs.example.org/install", "snippet": "official"},
    ]

    ranked = web.rank_search_results(results)

    assert [item["url"] for item in ranked] == [
        "https://seo1.example/post",
        "https://github.com/modelcontextprotocol/servers",
        "https://seo2.example/post",
        "https://docs.example.org/install",
        "https://seo3.example/post",
    ]


def test_normalize_searxng_results():
    payload = {
        "results": [
            {
                "title": "Official Docs",
                "url": "https://docs.example.com",
                "content": "Documentation snippet",
            },
            {
                "title": "",
                "url": "https://invalid.example",
                "content": "missing title",
            },
        ]
    }

    results = web.normalize_searxng_results(payload, max_results=5)

    assert results == [
        {
            "title": "Official Docs",
            "url": "https://docs.example.com",
            "snippet": "Documentation snippet",
        }
    ]


def test_search_web_uses_searxng_provider(monkeypatch):
    class Config:
        search_provider = "searxng"
        searxng_base_url = "https://search.example"
        max_search_results = 10
        prefer_technical_sources = True

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            assert url == "https://search.example/search"
            assert params["format"] == "json"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"title": "SEO", "url": "https://random.example/post", "content": "copy"},
                        {"title": "GitHub", "url": "https://github.com/example/repo", "content": "repo"},
                    ]
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=2, config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "searxng"
    assert result["results"][0]["url"] == "https://github.com/example/repo"


def test_validate_fetch_url_only_allows_http_and_https(public_dns):
    assert validate_fetch_url("https://example.com/path") == "https://example.com/path"

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("file:///C:/Windows/win.ini")

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("ftp://example.com/file")


def test_validate_fetch_url_blocks_private_networks_by_default():
    blocked = [
        "http://localhost/admin",
        "http://127.0.0.1/admin",
        "http://10.0.0.1/admin",
        "http://172.16.0.1/admin",
        "http://192.168.1.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/admin",
        "http://[fc00::1]/admin",
        "http://[fe80::1]/admin",
    ]

    for url in blocked:
        with pytest.raises(FetchSafetyError):
            validate_fetch_url(url)

    assert validate_fetch_url("http://127.0.0.1/admin", allow_private_networks=True) == "http://127.0.0.1/admin"


def test_validate_fetch_url_blocks_hostname_resolving_to_private_ip(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 80))])

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("https://public-name.example/admin")


def test_validate_fetch_url_allows_public_dns_resolution(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    assert validate_fetch_url("https://example.com/path") == "https://example.com/path"


def test_validate_fetch_url_allows_proxy_benchmark_address_resolution(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("198.18.0.176", 443))])

    assert validate_fetch_url("https://github.com/repo") == "https://github.com/repo"


def test_extract_markdown_converts_relative_links_to_absolute():
    html = '<html><body><main><a href="/docs/start">Start</a><a href="../api">API</a></main></body></html>'

    markdown = extract_markdown(html, "https://example.com/guide/install")

    assert "(https://example.com/docs/start)" in markdown
    assert "(https://example.com/api)" in markdown


def test_extract_markdown_removes_scripts_and_keeps_content():
    html = """
    <html>
      <head><script>alert(1)</script><style>body{}</style></head>
      <body><main><h1>Hello</h1><p>Useful text</p></main></body>
    </html>
    """

    markdown = extract_markdown(html, "https://example.com")

    assert "Hello" in markdown
    assert "Useful text" in markdown
    assert "alert" not in markdown
    assert "body{}" not in markdown


def test_limited_get_blocks_redirect_to_private_network():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"}, request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await web._limited_get(client, "https://example.com/start", allow_private_networks=False)

    with pytest.raises(FetchSafetyError):
        asyncio.run(run())


def test_is_deepseek_model_matches_known_names():
    assert is_deepseek_model("deepseek-v4-flash")
    assert is_deepseek_model("DeepSeek-V4-Pro[1m]")
    assert not is_deepseek_model("claude-opus-4-6")
    assert not is_deepseek_model("")


def test_fetch_page_returns_paginated_window_metadata(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300

    async def fake_limited_get(client, url):
        return httpx.Response(
            200,
            content=b"<html><body><main><p>abcdefghij</p></main></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page("https://example.com/doc", max_chars=4, start_index=2, config=Config()))

    assert result["ok"] is True
    assert result["markdown"] == "cdef"
    assert result["content_length"] == 10
    assert result["returned_range"] == {"start": 2, "end": 6}
    assert result["truncated"] is True
    assert result["next_start_index"] == 6


def test_fetch_page_formats_json_content(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False):
        return httpx.Response(
            200,
            content=b'{"name":"cc-web","items":[1,2]}',
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page("https://example.com/data.json", max_chars=2000, config=Config()))

    assert result["ok"] is True
    assert result["markdown"].startswith("{\n")
    assert '"name": "cc-web"' in result["markdown"]


def test_fetch_page_rejects_pdf_content(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False):
        return httpx.Response(
            200,
            content=b"%PDF-1.7",
            headers={"content-type": "application/pdf"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page("https://example.com/file.pdf", config=Config()))

    assert result["ok"] is False
    assert "PDF" in result["error"]


def test_fetch_page_extracts_pdf_when_enabled(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0
        enable_pdf_extract = True

    async def fake_limited_get(client, url, allow_private_networks=False):
        return httpx.Response(
            200,
            content=b"%PDF-1.7 fake",
            headers={"content-type": "application/pdf"},
            request=httpx.Request("GET", url),
        )

    def fake_extract_pdf(content):
        return "PDF extracted text"

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)
    monkeypatch.setattr(web, "_extract_pdf_text", fake_extract_pdf)

    result = asyncio.run(web.fetch_page("https://example.com/file.pdf", config=Config()))

    assert result["ok"] is True
    assert result["markdown"] == "PDF extracted text"


def test_fetch_page_uses_public_url_cache(monkeypatch, tmp_path, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 3600
        cache_dir = str(tmp_path / "cache")

    calls = 0

    async def fake_limited_get(client, url, allow_private_networks=False):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=b"<html><body><main><p>Cached public content that is long enough.</p></main></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    first = asyncio.run(web.fetch_page("https://example.com/cache", max_chars=1000, config=Config()))
    second = asyncio.run(web.fetch_page("https://example.com/cache", max_chars=1000, config=Config()))

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["cache"] == "hit"
    assert calls == 1


def test_cache_key_includes_schema_version():
    key_v1 = web._cache_key("https://example.com", "auto", schema_version=1)
    key_v2 = web._cache_key("https://example.com", "auto", schema_version=2)

    assert key_v1 != key_v2


def test_fetch_page_uses_jina_fallback_when_primary_fetch_fails(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = True
        jina_min_chars = 200
        cache_ttl_seconds = 0
        allow_private_networks = False

    async def failing_limited_get(client, url, allow_private_networks=False):
        request = httpx.Request("GET", url)
        response = httpx.Response(403, request=request)
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    async def fake_jina_reader(client, url, allow_private_networks=False):
        return {
            "markdown": "Jina fallback markdown",
            "reader_url": "https://r.jina.ai/https://blocked.example/doc",
        }

    monkeypatch.setattr(web, "_limited_get", failing_limited_get)
    monkeypatch.setattr(web, "_fetch_jina_reader_markdown", fake_jina_reader, raising=False)

    result = asyncio.run(web.fetch_page("https://blocked.example/doc", max_chars=1000, config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "jina_reader"
    assert result["markdown"] == "Jina fallback markdown"
    assert result["fallback_reason"].startswith("HTTPStatusError")


def test_jina_reader_revalidates_url_and_blocks_private_networks(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])

    async def run():
        async with httpx.AsyncClient() as client:
            await web._fetch_jina_reader_markdown(client, "https://private.example/doc", allow_private_networks=False)

    with pytest.raises(FetchSafetyError):
        asyncio.run(run())


def test_research_brief_returns_compact_sources(monkeypatch, public_dns):
    async def fake_search_web(query, max_results=5, region="wt-wt", language="zh-cn", config=None):
        return {
            "ok": True,
            "query": query,
            "backend": "searxng",
            "results": [
                {"title": "Doc A", "url": "https://example.com/a", "snippet": "A snippet"},
                {"title": "Doc B", "url": "https://example.com/b", "snippet": "B snippet"},
            ],
        }

    async def fake_fetch_page(url, max_chars=None, start_index=0, extract_mode="auto", config=None):
        return {
            "ok": True,
            "url": url,
            "final_url": url,
            "backend": "direct",
            "markdown": "x" * int(max_chars),
            "content_length": 50,
            "truncated": True,
            "next_start_index": 20,
        }

    monkeypatch.setattr(web, "search_web", fake_search_web)
    monkeypatch.setattr(web, "fetch_page", fake_fetch_page)

    research_brief = getattr(web, "research_brief")
    result = asyncio.run(research_brief("latest docs", max_sources=1, max_chars_per_source=20))

    assert result["ok"] is True
    assert result["backend"] == "searxng"
    assert len(result["sources"]) == 1
    assert result["sources"][0]["title"] == "Doc A"
    assert result["sources"][0]["markdown"] == "x" * 20
    assert result["sources"][0]["truncated"] is True


def test_research_brief_filters_invalid_urls_before_fetch(monkeypatch, public_dns):
    class Config:
        max_brief_sources = 3
        brief_chars_per_source = 20
        max_fetch_chars = 60000
        brief_concurrency = 2
        dedupe_domains = False
        allow_private_networks = False

    fetched_urls = []

    async def fake_search_web(query, max_results=5, region="wt-wt", language="zh-cn", config=None):
        return {
            "ok": True,
            "query": query,
            "backend": "duckduckgo_html",
            "results": [
                {"title": "Local", "url": "http://127.0.0.1/admin", "snippet": "bad"},
                {"title": "File", "url": "file:///C:/Windows/win.ini", "snippet": "bad"},
                {"title": "Public", "url": "https://example.com/public", "snippet": "ok"},
            ],
        }

    async def fake_fetch_page(url, max_chars=None, start_index=0, extract_mode="auto", config=None):
        fetched_urls.append(url)
        return {
            "ok": True,
            "url": url,
            "final_url": url,
            "backend": "direct",
            "markdown": "ok",
            "content_length": 2,
            "truncated": False,
            "next_start_index": None,
        }

    monkeypatch.setattr(web, "search_web", fake_search_web)
    monkeypatch.setattr(web, "fetch_page", fake_fetch_page)

    result = asyncio.run(web.research_brief("docs", max_sources=3, max_chars_per_source=20, config=Config()))

    assert fetched_urls == ["https://example.com/public"]
    assert [source["url"] for source in result["sources"]] == ["https://example.com/public"]
    assert [skipped["url"] for skipped in result["skipped_results"]] == [
        "http://127.0.0.1/admin",
        "file:///C:/Windows/win.ini",
    ]


def test_research_brief_dedupes_same_domain_results(monkeypatch, public_dns):
    class Config:
        max_brief_sources = 3
        brief_chars_per_source = 20
        max_fetch_chars = 60000
        brief_concurrency = 2
        dedupe_domains = True

    fetched_urls = []

    async def fake_search_web(query, max_results=5, region="wt-wt", language="zh-cn", config=None):
        return {
            "ok": True,
            "query": query,
            "results": [
                {"title": "Doc A", "url": "https://example.com/a", "snippet": "A snippet"},
                {"title": "Doc B", "url": "https://example.com/b", "snippet": "B snippet"},
                {"title": "Doc C", "url": "https://docs.example.org/c", "snippet": "C snippet"},
            ],
        }

    async def fake_fetch_page(url, max_chars=None, start_index=0, extract_mode="auto", config=None):
        fetched_urls.append(url)
        return {
            "ok": True,
            "url": url,
            "final_url": url,
            "backend": "direct",
            "markdown": url,
            "content_length": len(url),
            "truncated": False,
            "next_start_index": None,
        }

    monkeypatch.setattr(web, "search_web", fake_search_web)
    monkeypatch.setattr(web, "fetch_page", fake_fetch_page)

    result = asyncio.run(web.research_brief("docs", max_sources=3, max_chars_per_source=20, config=Config()))

    assert result["ok"] is True
    assert fetched_urls == ["https://example.com/a", "https://docs.example.org/c"]
    assert [source["url"] for source in result["sources"]] == fetched_urls
