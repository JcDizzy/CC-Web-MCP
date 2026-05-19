import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest

from cc_web_mcp import web
from cc_web_mcp.web import FetchSafetyError, extract_markdown, normalize_search_results, validate_fetch_url


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])


@pytest.fixture(autouse=True)
def clear_search_backend_cooldowns():
    web._SEARCH_BACKEND_COOLDOWNS.clear()
    yield
    web._SEARCH_BACKEND_COOLDOWNS.clear()


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


def test_filter_search_results_by_domains_keeps_matching_hosts():
    results = [
        {"title": "Docs", "url": "https://docs.example.com/guide", "snippet": "docs"},
        {"title": "Blog", "url": "https://blog.example.net/post", "snippet": "blog"},
        {"title": "API", "url": "https://api.example.com/v1", "snippet": "api"},
        {"title": "Invalid", "url": "not-a-url", "snippet": "bad"},
    ]

    filtered, removed = web.filter_search_results_by_domains(results, ("example.com",))

    assert removed == 2
    assert [item["url"] for item in filtered] == [
        "https://docs.example.com/guide",
        "https://api.example.com/v1",
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


def test_normalize_searxng_html_results():
    html = """
    <html><body>
      <div class="result">
        <a href="https://example.com/preferences">Preferences</a>
      </div>
      <article class="result">
        <h3><a href="https://example.com/doc">Example Doc</a></h3>
        <p class="content">Readable snippet.</p>
      </article>
    </body></html>
    """

    results = web.normalize_searxng_html_results(html, max_results=5)

    assert results == [
        {"title": "Example Doc", "url": "https://example.com/doc", "snippet": "Readable snippet."}
    ]


def test_default_headers_do_not_expose_tool_specific_user_agent():
    ua = web._headers()["User-Agent"]

    assert "GlobalWebMCP" not in ua
    assert "cc-web" not in ua.lower()
    assert "Mozilla/5.0" in ua


def test_normalize_mojeek_results():
    html = """
    <html><body>
      <nav><a href="https://www.mojeek.com/about">About Mojeek</a></nav>
      <a class="title" href="https://example.com/mojeek">Mojeek Result</a>
      <p class="s">Mojeek snippet.</p>
    </body></html>
    """

    results = web.normalize_mojeek_results(html, max_results=5)

    assert results == [
        {"title": "Mojeek Result", "url": "https://example.com/mojeek", "snippet": "Mojeek snippet."}
    ]


def test_normalize_bing_cn_results():
    html = """
    <html><body>
      <ol id="b_results">
        <li class="b_algo">
          <h2><a href="https://learn.microsoft.com/en-us/azure/">Microsoft Learn</a></h2>
          <div class="b_caption"><p>Official Azure documentation.</p></div>
        </li>
        <li class="b_algo">
          <h2><a href="https://github.com/example/repo">GitHub Repo</a></h2>
          <p>Repository snippet.</p>
        </li>
      </ol>
    </body></html>
    """

    results = web.normalize_bing_cn_results(html, max_results=2)

    assert results == [
        {
            "title": "Microsoft Learn",
            "url": "https://learn.microsoft.com/en-us/azure/",
            "snippet": "Official Azure documentation.",
        },
        {
            "title": "GitHub Repo",
            "url": "https://github.com/example/repo",
            "snippet": "Repository snippet.",
        },
    ]


def test_normalize_bing_cn_results_unwraps_bing_redirect_url():
    html = """
    <html><body>
      <ol id="b_results">
        <li class="b_algo">
          <h2>
            <a href="https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly9kb2NzLnB5dGhvbi5vcmcvMy8&ntb=1">
              Python Docs
            </a>
          </h2>
          <p>Official Python documentation.</p>
        </li>
      </ol>
    </body></html>
    """

    results = web.normalize_bing_cn_results(html, max_results=1)

    assert results == [
        {
            "title": "Python Docs",
            "url": "https://docs.python.org/3/",
            "snippet": "Official Python documentation.",
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


def test_search_web_uses_mojeek_provider(monkeypatch):
    class Config:
        search_provider = "mojeek"
        search_providers = ("mojeek",)
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            assert url == "https://www.mojeek.com/search"
            assert params["q"] == "mcp docs"
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a class="title" href="https://example.com/mojeek">Mojeek Result</a>
                  <p class="s">Mojeek snippet.</p>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=2, config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "mojeek"
    assert result["results"][0]["url"] == "https://example.com/mojeek"


def test_search_web_filters_results_by_domains_and_adds_ref_ids(monkeypatch):
    class Config:
        search_provider = "mojeek"
        search_providers = ("mojeek",)
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0

    seen_queries = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            seen_queries.append(params["q"])
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a class="title" href="https://docs.example.com/guide">Docs Result</a>
                  <p class="s">docs snippet</p>
                  <a class="title" href="https://other.example.net/post">Other Result</a>
                  <p class="s">other snippet</p>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web, "_BROWSE_SESSION", web.BrowseSession())
    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=5, domains=["example.com"], config=Config()))

    assert "site:example.com" in seen_queries[0]
    assert result["ok"] is True
    assert result["domain_filter"] == {"domains": ["example.com"], "removed_results": 1}
    assert [item["url"] for item in result["results"]] == ["https://docs.example.com/guide"]
    assert result["results"][0]["ref_id"].startswith("ccweb-search-")


def test_search_web_falls_back_to_searxng_html_when_json_fails(monkeypatch):
    class Config:
        search_provider = "searxng"
        search_providers = ("searxng",)
        searxng_base_url = "https://search.example"
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0

    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            calls.append(params["format"])
            if params["format"] == "json":
                return httpx.Response(429, text="limited", request=httpx.Request("GET", url))
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <article class="result">
                    <h3><a href="https://example.com/html">HTML Result</a></h3>
                    <p>HTML snippet.</p>
                  </article>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=2, config=Config()))

    assert calls == ["json", "html"]
    assert result["ok"] is True
    assert result["backend"] == "searxng_html"
    assert result["results"][0]["url"] == "https://example.com/html"


def test_search_web_falls_back_to_bing_cn_when_duckduckgo_fails(monkeypatch):
    class Config:
        search_provider = "duckduckgo"
        search_providers = ("duckduckgo", "bing_cn")
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            if "duckduckgo.com" in url:
                raise httpx.ConnectError("blocked", request=httpx.Request("GET", url))
            assert url == "https://cn.bing.com/search"
            assert params["q"] == "mcp docs"
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <li class="b_algo">
                    <h2><a href="https://github.com/modelcontextprotocol/servers">MCP Servers</a></h2>
                    <div class="b_caption"><p>Model Context Protocol servers.</p></div>
                  </li>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=2, config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "bing_cn"
    assert result["search_scope_note"] == "bing_cn may be region-biased and is used as fallback; it is not equivalent to full global search."
    assert "duckduckgo_html" in result["fallback_reason"]
    assert result["attempted_backends"][0]["backend"] == "duckduckgo_html"
    assert result["attempted_backends"][0]["ok"] is False
    assert result["attempted_backends"][1] == {"backend": "bing_cn", "ok": True}
    assert result["results"][0]["url"] == "https://github.com/modelcontextprotocol/servers"


def test_search_web_uses_international_bing_provider(monkeypatch):
    class Config:
        search_provider = "bing"
        search_providers = ("bing",)
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            assert url == "https://www.bing.com/search"
            assert params["q"] == "mcp docs"
            assert params["mkt"] == "zh-CN"
            assert params["setlang"] == "zh-cn"
            assert "cc" not in params
            assert "ensearch" not in params
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <li class="b_algo">
                    <h2><a href="https://example.com/international">International Bing</a></h2>
                    <div class="b_caption"><p>International result.</p></div>
                  </li>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=2, config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "bing"
    assert "search_scope_note" not in result
    assert result["attempted_backends"] == [{"backend": "bing", "ok": True}]
    assert result["results"][0]["url"] == "https://example.com/international"


def test_search_web_default_chain_prefers_international_bing_before_bing_cn(monkeypatch):
    class Config:
        search_provider = "duckduckgo"
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0
        search_backend_cooldown_seconds = 0

    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            calls.append(url)
            if "duckduckgo.com" in url:
                raise httpx.ConnectError("blocked", request=httpx.Request("GET", url))
            if "www.bing.com" in url:
                return httpx.Response(
                    200,
                    text="""
                    <html><body>
                      <li class="b_algo">
                        <h2><a href="https://example.com/bing">Bing</a></h2>
                        <p>better fallback</p>
                      </li>
                    </body></html>
                    """,
                    request=httpx.Request("GET", url),
                )
            raise AssertionError("bing_cn should not be reached when international bing succeeds")

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=2, config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "bing"
    assert calls == ["https://html.duckduckgo.com/html/", "https://www.bing.com/search"]


def test_search_web_falls_back_when_provider_returns_empty_results(monkeypatch):
    class Config:
        search_provider = "duckduckgo"
        search_providers = ("duckduckgo", "bing_cn")
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            if "duckduckgo.com" in url:
                return httpx.Response(
                    200,
                    text="<html><body><p>No parsed results</p></body></html>",
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <ol id="b_results">
                    <li class="b_algo">
                      <h2><a href="https://docs.python.org/3/">Python Docs</a></h2>
                      <p>Official docs.</p>
                    </li>
                  </ol>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("python docs", max_results=3, config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "bing_cn"
    assert result["attempted_backends"][0]["backend"] == "duckduckgo_html"
    assert result["attempted_backends"][0]["ok"] is False
    assert "empty_results" in result["attempted_backends"][0]["error"]
    assert result["results"][0]["url"] == "https://docs.python.org/3/"


def test_search_web_falls_back_when_duckduckgo_returns_js_challenge(monkeypatch):
    class Config:
        search_provider = "duckduckgo"
        search_providers = ("duckduckgo", "bing_cn")
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            if "duckduckgo.com" in url:
                return httpx.Response(
                    202,
                    text="""
                    <html><body>
                      <div class="anomaly-modal">Unfortunately, bots use DuckDuckGo too.</div>
                      <form id="challenge-form" action="/anomaly.js"></form>
                    </body></html>
                    """,
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <li class="b_algo">
                    <h2><a href="https://docs.python.org/3/">Python Docs</a></h2>
                    <p>Official docs.</p>
                  </li>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("python docs", max_results=3, config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "bing_cn"
    assert result["attempted_backends"][0]["backend"] == "duckduckgo_html"
    assert result["attempted_backends"][0]["ok"] is False
    assert "duckduckgo_challenge" in result["attempted_backends"][0]["error"]
    assert result["results"][0]["url"] == "https://docs.python.org/3/"


def test_search_web_domain_filter_uses_unwrapped_bing_urls(monkeypatch):
    class Config:
        search_provider = "bing_cn"
        search_providers = ("bing_cn",)
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <li class="b_algo">
                    <h2>
                      <a href="https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly9kb2NzLnB5dGhvbi5vcmcvMy8&ntb=1">
                        Python Docs
                      </a>
                    </h2>
                    <p>Official docs.</p>
                  </li>
                  <li class="b_algo">
                    <h2><a href="https://example.net/other">Other</a></h2>
                    <p>Other result.</p>
                  </li>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web, "_BROWSE_SESSION", web.BrowseSession())
    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("python docs", max_results=3, domains=["python.org"], config=Config()))

    assert result["ok"] is True
    assert result["backend"] == "bing_cn"
    assert result["domain_filter"] == {"domains": ["python.org"], "removed_results": 1}
    assert result["results"][0]["url"] == "https://docs.python.org/3/"
    assert result["results"][0]["ref_id"].startswith("ccweb-search-")


def test_search_web_uses_short_ttl_success_cache(monkeypatch, tmp_path):
    class Config:
        search_provider = "mojeek"
        search_providers = ("mojeek",)
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 600
        cache_dir = str(tmp_path)

    calls = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                text=f"""
                <html><body>
                  <a class="title" href="https://example.com/{calls}">Result {calls}</a>
                  <p class="s">snippet</p>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    first = asyncio.run(web.search_web("cache me", max_results=2, config=Config()))
    second = asyncio.run(web.search_web("cache me", max_results=2, config=Config()))

    assert calls == 1
    assert first["cache"] == "miss"
    assert second["cache"] == "hit"
    assert second["results"][0]["url"] == "https://example.com/1"


def test_search_web_cache_is_independent_from_private_network_fetch_setting(monkeypatch, tmp_path):
    class Config:
        search_provider = "mojeek"
        search_providers = ("mojeek",)
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 600
        allow_private_networks = True
        cache_dir = str(tmp_path)

    calls = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                text=f"""
                <html><body>
                  <a class="title" href="https://example.com/{calls}">Result {calls}</a>
                  <p class="s">snippet</p>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    first = asyncio.run(web.search_web("cache me", max_results=2, config=Config()))
    second = asyncio.run(web.search_web("cache me", max_results=2, config=Config()))

    assert calls == 1
    assert first["cache"] == "miss"
    assert second["cache"] == "hit"
    assert second["results"][0]["url"] == "https://example.com/1"


def test_search_web_skips_backend_during_cooldown(monkeypatch):
    class Config:
        search_provider = "duckduckgo"
        search_providers = ("duckduckgo", "bing")
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False
        search_cache_ttl_seconds = 0
        search_backend_cooldown_seconds = 120

    web._SEARCH_BACKEND_COOLDOWNS.clear()
    calls = []
    now = time.time()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            calls.append(url)
            if "duckduckgo.com" in url:
                return httpx.Response(
                    202,
                    text="<form id='challenge-form' action='/anomaly.js'></form>",
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <li class="b_algo">
                    <h2><a href="https://example.com/bing">Bing</a></h2>
                    <p>fallback result</p>
                  </li>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(web.time, "time", lambda: now)

    first = asyncio.run(web.search_web("cooldown", max_results=2, config=Config()))
    second = asyncio.run(web.search_web("cooldown again", max_results=2, config=Config()))

    assert first["backend"] == "bing"
    assert second["backend"] == "bing"
    assert calls == [
        "https://html.duckduckgo.com/html/",
        "https://www.bing.com/search",
        "https://www.bing.com/search",
    ]
    assert second["attempted_backends"][0]["backend"] == "duckduckgo_html"
    assert second["attempted_backends"][0]["skipped"] is True
    assert second["attempted_backends"][0]["retry_after_seconds"] == 120

    web._SEARCH_BACKEND_COOLDOWNS.clear()


def test_search_web_records_status_steps_and_callback(monkeypatch):
    class Config:
        search_provider = "duckduckgo"
        search_providers = ("duckduckgo", "bing_cn")
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            if "duckduckgo.com" in url:
                raise httpx.ConnectError("blocked", request=httpx.Request("GET", url))
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <li class="b_algo">
                    <h2><a href="https://example.com/doc">Example Doc</a></h2>
                    <div class="b_caption"><p>Example snippet.</p></div>
                  </li>
                </body></html>
                """,
                request=httpx.Request("GET", url),
            )

    messages = []

    async def status_callback(message):
        messages.append(message)

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=2, config=Config(), status_callback=status_callback))

    assert result["ok"] is True
    assert result["backend"] == "bing_cn"
    assert "bing_cn" in result["status_summary"]
    assert [step["message"] for step in result["steps"]] == messages
    assert any("duckduckgo_html" in message for message in messages)
    assert any("bing_cn" in message for message in messages)


def test_search_web_all_provider_failure_guides_model_away_from_immediate_retry(monkeypatch):
    class Config:
        search_provider = "duckduckgo"
        search_providers = ("duckduckgo", "bing_cn")
        searxng_base_url = ""
        max_search_results = 10
        prefer_technical_sources = False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            raise httpx.ConnectError("blocked", request=httpx.Request("GET", url))

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web.search_web("mcp docs", max_results=2, config=Config()))

    assert result["ok"] is False
    assert result["retryable"] is True
    assert "same search" in result["do_not_retry_reason"]
    assert "health_check" in result["recommended_next_action"]
    assert result["attempted_backends"][0]["backend"] == "duckduckgo_html"
    assert result["attempted_backends"][1]["backend"] == "bing_cn"


def test_load_config_keeps_ordered_search_providers(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "search_provider": "duckduckgo",
          "search_providers": ["duckduckgo", "bing_cn", "duckduckgo", ""]
        }
        """,
        encoding="utf-8",
    )

    config = web.load_config(config_path)

    assert config.search_provider == "duckduckgo"
    assert config.search_providers == ("duckduckgo", "bing_cn")


def test_load_config_defaults_to_international_bing_before_bing_cn(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        web,
        "default_config_dict",
        lambda: {
            "search_providers": ["duckduckgo", "bing", "bing_cn"],
            "search_cache_ttl_seconds": 300,
        },
    )

    config = web.load_config(config_path)

    assert config.search_providers == ("duckduckgo", "bing", "bing_cn")
    assert config.search_cache_ttl_seconds == 300


def test_load_config_uses_packaged_defaults_when_user_config_is_missing(monkeypatch, tmp_path):
    missing_config = tmp_path / "missing.json"

    monkeypatch.setattr(
        web,
        "default_config_dict",
        lambda: {
            "allowed_model_patterns": ["deepseek"],
            "search_providers": ["SearXNG", "duckduckgo", "bing"],
            "searxng_base_url": "http://127.0.0.1:8888",
            "search_cache_ttl_seconds": 123,
        },
    )

    config = web.load_config(missing_config)

    assert config.search_provider == "searxng"
    assert config.search_providers == ("searxng", "duckduckgo", "bing")
    assert config.searxng_base_url == "http://127.0.0.1:8888"
    assert config.search_cache_ttl_seconds == 123


def test_search_providers_prefer_explicit_chain_over_legacy_provider(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "search_provider": "searxng",
          "search_providers": ["duckduckgo", "bing_cn"]
        }
        """,
        encoding="utf-8",
    )

    config = web.load_config(config_path)

    assert config.search_provider == "searxng"
    assert config.search_providers == ("duckduckgo", "bing_cn")


def test_check_health_reports_configured_search_provider_chain(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "search_providers": ["duckduckgo", "bing_cn"],
          "block_native_web_for_allowed_models": false
        }
        """,
        encoding="utf-8",
    )

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            if "duckduckgo.com" in url:
                raise httpx.ConnectError("blocked", request=httpx.Request("GET", url))
            assert params["q"] == "cc-web health"
            return FakeResponse(200)

    monkeypatch.setattr(web, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    health = asyncio.run(web.check_health())

    assert health["search_providers"] == ["duckduckgo", "bing_cn"]
    assert health["config"]["block_native_web_for_allowed_models"] is False
    assert health["search_backend_status"]["duckduckgo"]["ok"] is False
    assert health["search_backend_status"]["bing_cn"] == {"ok": True, "status": 200}
    assert health["first_available_search_backend"] == "bing_cn"


def test_check_health_reports_international_bing_provider(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "search_providers": ["bing"]
        }
        """,
        encoding="utf-8",
    )

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            assert url == "https://www.bing.com/search"
            assert params == {"q": "cc-web health", "mkt": "zh-CN", "setlang": "zh-cn"}
            return FakeResponse(200)

    monkeypatch.setattr(web, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    health = asyncio.run(web.check_health())

    assert health["search_providers"] == ["bing"]
    assert health["search_backend_status"]["bing"] == {"ok": True, "status": 200}
    assert health["first_available_search_backend"] == "bing"


def test_check_health_marks_rate_limited_search_backend_unavailable(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "search_providers": ["mojeek", "bing_cn"],
            }
        ),
        encoding="utf-8",
    )

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, follow_redirects=True):
            if "mojeek.com" in url:
                return FakeResponse(429)
            return FakeResponse(200)

    monkeypatch.setattr(web, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(web.httpx, "AsyncClient", FakeClient)

    health = asyncio.run(web.check_health())

    assert health["search_backend_status"]["mojeek"] == {"ok": False, "status": 429}
    assert health["first_available_search_backend"] == "bing_cn"
    assert "198.18.0.0/15" in health["network_policy"]["blocked_networks"]


def test_validate_fetch_url_only_allows_http_and_https(public_dns):
    assert validate_fetch_url("https://example.com/path") == "https://example.com/path"

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("file:///C:/Windows/win.ini")

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("ftp://example.com/file")


def test_validate_fetch_url_blocks_private_networks_by_default():
    blocked = [
        "http://localhost/admin",
        "http://0.0.0.0/admin",
        "http://127.0.0.1/admin",
        "http://10.0.0.1/admin",
        "http://172.16.0.1/admin",
        "http://192.168.1.1/admin",
        "http://100.64.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://224.0.0.1/admin",
        "http://240.0.0.1/admin",
        "http://255.255.255.255/admin",
        "http://[::]/admin",
        "http://[::1]/admin",
        "http://[::ffff:127.0.0.1]/admin",
        "http://[::ffff:10.0.0.1]/admin",
        "http://[::ffff:169.254.169.254]/latest/meta-data",
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


def test_validate_fetch_url_blocks_hostname_resolving_to_reserved_ip(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("100.64.0.10", 443))])

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("https://public-name.example/admin")


def test_async_validate_fetch_url_resolves_dns_in_thread(monkeypatch):
    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return ["127.0.0.1"]

    monkeypatch.setattr(web.asyncio, "to_thread", fake_to_thread)

    with pytest.raises(FetchSafetyError):
        asyncio.run(web.validate_fetch_url_async("https://public-name.example/admin"))

    assert calls
    assert calls[0][0] is web._resolved_private_hosts


def test_validate_fetch_url_allows_public_dns_resolution(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    assert validate_fetch_url("https://example.com/path") == "https://example.com/path"


def test_validate_fetch_url_blocks_proxy_benchmark_address_resolution_by_default(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("198.18.0.176", 443))])

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("https://github.com/repo")


def test_validate_fetch_url_allows_trusted_proxy_benchmark_address_resolution(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("198.18.0.176", 443))])

    assert validate_fetch_url("https://github.com/repo", trusted_proxy_domains=("github.com",)) == "https://github.com/repo"


def test_validate_fetch_url_allows_tun_fake_ip_dns_when_enabled(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("198.18.0.176", 443))])

    assert validate_fetch_url("https://docs.python.org/3/", trust_tun_fake_ip_dns=True) == "https://docs.python.org/3/"


def test_validate_fetch_url_still_blocks_direct_tun_fake_ip_literal_when_enabled(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("198.18.0.176", 443))])

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("https://198.18.0.176/admin", trust_tun_fake_ip_dns=True)


def test_validate_fetch_url_still_blocks_private_dns_when_tun_fake_ip_enabled(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])

    with pytest.raises(FetchSafetyError):
        validate_fetch_url("https://example.com/admin", trust_tun_fake_ip_dns=True)


def test_evaluate_network_policy_records_blocked_dns_resolution(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])

    decision = web.evaluate_network_policy("https://example.com/private")

    assert decision["allowed"] is False
    assert decision["reason"] == "restricted_dns"
    assert decision["resolved_ips"] == ["127.0.0.1"]
    assert decision["blocked_ips"] == ["127.0.0.1"]


def test_evaluate_network_policy_records_tun_fake_ip_trust(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("198.18.1.27", 443))])

    decision = web.evaluate_network_policy("https://docs.python.org/3/", trust_tun_fake_ip_dns=True)

    assert decision["allowed"] is True
    assert decision["reason"] == "trusted_tun_fake_ip_dns"
    assert decision["trusted_proxy"] is True
    assert decision["resolved_ips"] == ["198.18.1.27"]
    assert decision["blocked_ips"] == ["198.18.1.27"]


def test_build_fetch_target_pins_validated_ip_and_keeps_tls_hostname(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    target = web.build_fetch_target("https://example.com/docs?q=1")

    assert target.connect_host == "93.184.216.34"
    assert target.hostname == "example.com"
    assert target.host_header == "example.com"
    assert target.request_target == "/docs?q=1"


def test_build_fetch_target_allows_tun_fake_ip_dns_when_enabled(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("198.18.1.27", 443))])

    target = web.build_fetch_target("https://docs.python.org/3/", trust_tun_fake_ip_dns=True)

    assert target.connect_host == "198.18.1.27"
    assert target.hostname == "docs.python.org"
    assert target.host_header == "docs.python.org"
    assert target.request_target == "/3/"


def test_limited_get_uses_fetch_target_and_preserves_original_url(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])

    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            content=b"ok",
            headers={"content-type": "text/plain"},
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await web._limited_get(client, "http://example.com/docs?q=1", allow_private_networks=False)

    response = asyncio.run(run())

    assert seen_requests[0].url == "http://93.184.216.34/docs?q=1"
    assert seen_requests[0].headers["host"] == "example.com"
    assert response.url == "http://example.com/docs?q=1"


def test_fetch_page_resolves_search_ref_id_and_returns_network_policy(monkeypatch, public_dns):
    monkeypatch.setattr(web, "_BROWSE_SESSION", web.BrowseSession())
    ref_id = web._BROWSE_SESSION.add("search", "https://example.com/docs", title="Docs")

    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 2000
        allow_private_networks = False
        cache_ttl_seconds = 0
        enable_jina_fallback = False

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        return httpx.Response(
            200,
            content=b"<html><body><main><p>Hello ref</p></main></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page(ref_id=ref_id, config=Config()))

    assert result["ok"] is True
    assert result["url"] == "https://example.com/docs"
    assert result["resolved_from_ref_id"] == ref_id
    assert result["network_policy"]["allowed"] is True
    assert result["network_policy"]["resolved_ips"] == ["93.184.216.34"]
    assert result["redirect_count"] == 0


def test_fetch_page_accepts_ref_id_in_url_parameter(monkeypatch, public_dns):
    monkeypatch.setattr(web, "_BROWSE_SESSION", web.BrowseSession())
    ref_id = web._BROWSE_SESSION.add("search", "https://example.com/docs", title="Docs")

    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 2000
        allow_private_networks = False
        cache_ttl_seconds = 0
        enable_jina_fallback = False

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        return httpx.Response(
            200,
            content=b"<html><body><main><p>Hello ref</p></main></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page(url=ref_id, config=Config()))

    assert result["ok"] is True
    assert result["resolved_from_ref_id"] == ref_id


def test_fetch_page_returns_ref_not_found_for_unknown_ref_id():
    result = asyncio.run(web.fetch_page(ref_id="ccweb-search-missing"))

    assert result["ok"] is False
    assert result["error_type"] == "ref_not_found"
    assert result["retryable"] is False


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


def test_fetch_page_returns_paginated_window_metadata(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
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


def test_fetch_page_returns_continuation_guidance_for_truncated_content(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        return httpx.Response(
            200,
            content=b"<html><body><main><p>abcdefghij</p></main></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page("https://example.com/doc", max_chars=4, start_index=0, config=Config()))

    assert result["ok"] is True
    assert result["markdown"] == "abcd"
    assert result["truncation"]["remaining_chars"] == 6
    assert result["truncation"]["next_call"]["tool"] == "fetch_url"
    assert result["truncation"]["next_call"]["start_index"] == 4
    assert "Do not repeat" in result["truncation"]["do_not_retry_reason"]


def test_fetch_page_records_status_steps_and_callback(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        return httpx.Response(
            200,
            content=b"<html><body><main><p>Hello status</p></main></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    messages = []

    async def status_callback(message):
        messages.append(message)

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page("https://example.com/doc", max_chars=50, config=Config(), status_callback=status_callback))

    assert result["ok"] is True
    assert result["backend"] == "direct"
    assert "direct" in result["status_summary"]
    assert [step["message"] for step in result["steps"]] == messages
    assert any("fetching" in message for message in messages)
    assert any("extracting" in message for message in messages)


def test_fetch_page_formats_json_content(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
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

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
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


def test_fetch_page_safety_error_guides_model_to_fix_url():
    result = asyncio.run(web.fetch_page("mailto:reader@example.com"))

    assert result["ok"] is False
    assert result["error_type"] == "fetch_safety"
    assert result["retryable"] is False
    assert "safety policy" in result["do_not_retry_reason"]
    assert "http/https" in result["recommended_next_action"]


def test_fetch_page_extracts_pdf_when_enabled(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0
        enable_pdf_extract = True

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
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

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
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


def test_fetch_page_does_not_cache_jina_fallback_under_direct_url(monkeypatch, tmp_path, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = True
        jina_min_chars = 200
        cache_ttl_seconds = 3600
        allow_private_networks = False
        cache_dir = str(tmp_path / "cache")

    direct_calls = 0
    jina_calls = 0

    async def short_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        nonlocal direct_calls
        direct_calls += 1
        return httpx.Response(
            200,
            content=b"<html><body><main><p>short</p></main></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    async def fake_jina_reader(client, url):
        nonlocal jina_calls
        jina_calls += 1
        return {
            "markdown": "Jina fallback markdown",
            "reader_url": "https://r.jina.ai/https://example.com/short",
        }

    monkeypatch.setattr(web, "_limited_get", short_limited_get)
    monkeypatch.setattr(web, "_fetch_jina_reader_markdown", fake_jina_reader, raising=False)

    first = asyncio.run(web.fetch_page("https://example.com/short", max_chars=1000, config=Config()))
    second = asyncio.run(web.fetch_page("https://example.com/short", max_chars=1000, config=Config()))

    assert first["ok"] is True
    assert second["ok"] is True
    assert direct_calls == 2
    assert jina_calls == 2
    assert second["cache"] == "miss"


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

    async def failing_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        request = httpx.Request("GET", url)
        response = httpx.Response(403, request=request)
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    async def fake_jina_reader(client, url):
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
            await web._fetch_jina_reader_markdown(client, "https://private.example/doc")

    with pytest.raises(FetchSafetyError):
        asyncio.run(run())


def test_jina_reader_still_blocks_private_networks_when_config_allows_them(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])

    async def run():
        async with httpx.AsyncClient() as client:
            await web._fetch_jina_reader_markdown(client, "https://private.example/doc")

    with pytest.raises(FetchSafetyError):
        asyncio.run(run())


def test_diagnose_fetch_response_detects_zhihu_challenge_page():
    request = httpx.Request("GET", "https://www.zhihu.com/question/19550256")
    response = httpx.Response(
        403,
        content="<html><head><title>安全验证 - 知乎</title></head><body>请完成验证 account/unhuman</body></html>".encode("utf-8"),
        headers={"content-type": "text/html"},
        request=request,
    )

    diagnostics = web._diagnose_fetch_response("https://www.zhihu.com/question/19550256", response)

    assert diagnostics["type"] == "captcha_or_challenge"
    assert diagnostics["confidence"] == "high"
    assert "status_code=403" in diagnostics["signals"]
    assert any("安全验证" in signal for signal in diagnostics["signals"])


def test_diagnose_fetch_response_handles_unread_streaming_error_response():
    request = httpx.Request("GET", "https://www.zhihu.com/question/19550256")
    response = httpx.Response(
        403,
        stream=httpx.ByteStream("<html><title>安全验证 - 知乎</title></html>".encode("utf-8")),
        request=request,
    )

    diagnostics = web._diagnose_fetch_response("https://www.zhihu.com/question/19550256", response)

    assert diagnostics["type"] == "blocked_or_waf"
    assert diagnostics["confidence"] == "high"
    assert "status_code=403" in diagnostics["signals"]


def test_limited_get_preserves_error_body_for_diagnostics(public_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            content="<html><head><title>安全验证 - 知乎</title></head><body>请完成验证</body></html>".encode("utf-8"),
            headers={"content-type": "text/html"},
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            try:
                await web._limited_get(client, "https://www.zhihu.com/question/19550256", allow_private_networks=False)
            except httpx.HTTPStatusError as exc:
                return web._diagnose_fetch_exception("https://www.zhihu.com/question/19550256", exc)
        raise AssertionError("expected HTTPStatusError")

    diagnostics = asyncio.run(run())

    assert diagnostics["type"] == "captcha_or_challenge"
    assert any("安全验证" in signal for signal in diagnostics["signals"])


def test_fetch_page_returns_anti_bot_diagnostics_when_direct_fetch_is_blocked(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        request = httpx.Request("GET", url)
        response = httpx.Response(
            403,
            content="<html><head><title>安全验证 - 知乎</title></head><body>请完成验证</body></html>".encode("utf-8"),
            headers={"content-type": "text/html"},
            request=request,
        )
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page("https://www.zhihu.com/question/19550256", config=Config()))

    assert result["ok"] is False
    assert result["error_type"] == "captcha_or_challenge"
    assert result["fetch_diagnostics"]["confidence"] == "high"
    assert result["retryable"] is False
    assert "captcha_or_challenge" in result["do_not_retry_reason"]
    assert result["recommended_next_action"] == result["fetch_diagnostics"]["recommendation"]
    assert "建议改用搜索摘要" in result["fetch_diagnostics"]["recommendation"]


def test_fetch_page_marks_known_site_read_timeout_as_suspected_antibot(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        request = httpx.Request("GET", url)
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page("https://www.zhihu.com/question/19550256", config=Config()))

    assert result["ok"] is False
    assert result["error_type"] == "timeout_suspected_antibot"
    assert result["fetch_diagnostics"]["confidence"] == "medium"
    assert any("known anti-bot domain" in signal for signal in result["fetch_diagnostics"]["signals"])
    assert result["retryable"] is False


def test_fetch_page_marks_plain_network_timeout_retryable(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = False
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        request = httpx.Request("GET", url)
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)

    result = asyncio.run(web.fetch_page("https://example.com/slow", config=Config()))

    assert result["ok"] is False
    assert result["error_type"] == "network_timeout"
    assert result["retryable"] is True
    assert result["retry_after_seconds"] == 30
    assert result["recommended_next_action"]


def test_fetch_page_keeps_direct_anti_bot_diagnostics_when_jina_fallback_fails(monkeypatch, public_dns):
    class Config:
        default_fetch_chars = 1000
        max_fetch_chars = 60000
        enable_jina_fallback = True
        jina_min_chars = 300
        allow_private_networks = False
        cache_ttl_seconds = 0

    async def fake_limited_get(client, url, allow_private_networks=False, trusted_proxy_domains=None):
        request = httpx.Request("GET", url)
        response = httpx.Response(
            403,
            content="<html><head><title>安全验证 - 知乎</title></head><body>请完成验证</body></html>".encode("utf-8"),
            headers={"content-type": "text/html"},
            request=request,
        )
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    async def failing_jina_reader(client, url):
        request = httpx.Request("GET", "https://r.jina.ai/https://www.zhihu.com/question/19550256")
        raise httpx.ReadTimeout("jina timed out", request=request)

    monkeypatch.setattr(web, "_limited_get", fake_limited_get)
    monkeypatch.setattr(web, "_fetch_jina_reader_markdown", failing_jina_reader, raising=False)

    result = asyncio.run(web.fetch_page("https://www.zhihu.com/question/19550256", config=Config()))

    assert result["ok"] is False
    assert result["error_type"] == "captcha_or_challenge"
    assert result["fetch_diagnostics"]["confidence"] == "high"


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
            "truncation": {
                "remaining_chars": 30,
                "next_call": {
                    "url": url,
                    "max_chars": 20,
                    "start_index": 20,
                    "extract_mode": "auto",
                },
            },
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
    assert result["sources"][0]["truncation"]["next_call"]["start_index"] == 20


def test_research_brief_records_status_steps_and_callback(monkeypatch, public_dns):
    class Config:
        max_brief_sources = 2
        brief_chars_per_source = 20
        max_fetch_chars = 60000
        brief_concurrency = 1
        dedupe_domains = False
        allow_private_networks = False
        max_search_results = 10

    async def fake_search_web(query, max_results=5, region="wt-wt", language="zh-cn", config=None, status_callback=None):
        if status_callback:
            await status_callback("cc-web: searching via fake")
        return {
            "ok": True,
            "query": query,
            "backend": "fake",
            "results": [
                {"title": "Doc A", "url": "https://example.com/a", "snippet": "A snippet"},
                {"title": "Doc B", "url": "https://example.org/b", "snippet": "B snippet"},
            ],
        }

    async def fake_fetch_page(url, max_chars=None, start_index=0, extract_mode="auto", config=None, status_callback=None):
        if status_callback:
            await status_callback(f"cc-web: fetching {url}")
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

    messages = []

    async def status_callback(message):
        messages.append(message)

    monkeypatch.setattr(web, "search_web", fake_search_web)
    monkeypatch.setattr(web, "fetch_page", fake_fetch_page)

    result = asyncio.run(
        web.research_brief("docs", max_sources=2, max_chars_per_source=20, config=Config(), status_callback=status_callback)
    )

    assert result["ok"] is True
    assert result["status_summary"] == "research brief complete: 2 sources from fake"
    assert [step["message"] for step in result["steps"]] == messages
    assert messages[0] == "cc-web: searching via fake"
    assert any("fetching 1/2" in message for message in messages)
    assert any("fetching https://example.com/a" in message for message in messages)


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


def test_research_brief_propagates_fetch_diagnostics_for_failed_source(monkeypatch, public_dns):
    class Config:
        max_brief_sources = 1
        brief_chars_per_source = 20
        max_fetch_chars = 60000
        brief_concurrency = 1
        dedupe_domains = False
        allow_private_networks = False

    async def fake_search_web(query, max_results=5, region="wt-wt", language="zh-cn", config=None):
        return {
            "ok": True,
            "query": query,
            "backend": "duckduckgo_html",
            "results": [
                {"title": "Zhihu", "url": "https://www.zhihu.com/question/19550256", "snippet": "snippet"},
            ],
        }

    async def fake_fetch_page(url, max_chars=None, start_index=0, extract_mode="auto", config=None):
        return {
            "ok": False,
            "url": url,
            "error": "HTTPStatusError: forbidden",
            "error_type": "captcha_or_challenge",
            "fetch_diagnostics": {
                "type": "captcha_or_challenge",
                "confidence": "high",
                "signals": ["status_code=403"],
                "recommendation": "目标站点疑似启用了反爬、人机验证或登录墙；建议改用搜索摘要、官方来源或其他可访问来源。",
            },
        }

    monkeypatch.setattr(web, "search_web", fake_search_web)
    monkeypatch.setattr(web, "fetch_page", fake_fetch_page)

    result = asyncio.run(web.research_brief("知乎 test", max_sources=1, max_chars_per_source=20, config=Config()))

    assert result["sources"][0]["ok"] is False
    assert result["sources"][0]["error_type"] == "captcha_or_challenge"
    assert result["sources"][0]["fetch_diagnostics"]["confidence"] == "high"


def test_research_brief_propagates_retry_guidance_for_failed_source(monkeypatch, public_dns):
    class Config:
        max_brief_sources = 1
        brief_chars_per_source = 20
        max_fetch_chars = 60000
        brief_concurrency = 1
        dedupe_domains = False
        allow_private_networks = False

    async def fake_search_web(query, max_results=5, region="wt-wt", language="zh-cn", config=None):
        return {
            "ok": True,
            "query": query,
            "backend": "duckduckgo_html",
            "results": [
                {"title": "Blocked", "url": "https://blocked.example/doc", "snippet": "snippet"},
            ],
        }

    async def fake_fetch_page(url, max_chars=None, start_index=0, extract_mode="auto", config=None):
        return {
            "ok": False,
            "url": url,
            "error": "HTTPStatusError: forbidden",
            "error_type": "blocked_or_waf",
            "retryable": False,
            "do_not_retry_reason": "Target returned blocked_or_waf; repeating fetch_url with the same URL is unlikely to help.",
            "recommended_next_action": "Use search summaries or another accessible source.",
        }

    monkeypatch.setattr(web, "search_web", fake_search_web)
    monkeypatch.setattr(web, "fetch_page", fake_fetch_page)

    result = asyncio.run(web.research_brief("blocked doc", max_sources=1, max_chars_per_source=20, config=Config()))

    assert result["sources"][0]["ok"] is False
    assert result["sources"][0]["retryable"] is False
    assert "same URL" in result["sources"][0]["do_not_retry_reason"]
    assert result["sources"][0]["recommended_next_action"] == "Use search summaries or another accessible source."


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
