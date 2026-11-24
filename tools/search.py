"""Web search — DuckDuckGo, no API key required.

Uses the `ddgs` package when installed, otherwise scrapes the DuckDuckGo
HTML endpoint with plain regex (no extra dependencies).
"""

from __future__ import annotations

import html as html_lib
import re
import urllib.parse
from typing import Any

import requests

from tools.registry import Tool, ToolRegistry

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/0.1"}


def _ddg_html_search(query: str, count: int, news: bool = False) -> list[dict[str, str]]:
    base = "https://html.duckduckgo.com/html/" if not news else "https://html.duckduckgo.com/html/?ia=news"
    resp = requests.get(
        base, params={"q": query}, headers=HEADERS, timeout=20
    )
    resp.raise_for_status()
    page = resp.text
    results: list[dict[str, str]] = []
    # result__a anchors carry the title + (redirect) href; result__snippet the text.
    anchors = re.findall(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S
    )
    snippets = re.findall(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    for i, (href, title_html) in enumerate(anchors[:count]):
        title = re.sub(r"<[^>]+>", "", html_lib.unescape(title_html)).strip()
        url = html_lib.unescape(href)
        m = re.search(r"uddg=([^&]+)", url)
        if m:
            url = urllib.parse.unquote(m.group(1))
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", html_lib.unescape(snippets[i])).strip()
        if title and url.startswith("http"):
            results.append({"title": title, "url": url, "snippet": snippet})
    return results


def _ddgs_search(query: str, count: int, news: bool = False) -> list[dict[str, str]]:
    from ddgs import DDGS  # type: ignore

    with DDGS() as ddgs:
        if news:
            rows = ddgs.news(query, max_results=count)
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("body", ""),
                }
                for r in rows
            ]
        rows = ddgs.text(query, max_results=count)
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in rows
        ]


def _search(query: str, count: int, news: bool) -> list[dict[str, str]]:
    try:
        return _ddgs_search(query, count, news)
    except Exception:
        return _ddg_html_search(query, count, news)


def _fmt(results: list[dict[str, str]]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
    return "\n".join(lines)


def web_search(query: str, count: int = 5) -> str:
    """Search the web and return titles, URLs and snippets."""
    try:
        return _fmt(_search(query, max(1, min(count, 10)), news=False))
    except Exception as exc:  # noqa: BLE001
        return f"Web search failed: {exc}"


def search_news(query: str = "", count: int = 5) -> str:
    """Search the news (defaults to top headlines)."""
    q = query.strip() or "top news"
    try:
        return _fmt(_search(q, max(1, min(count, 10)), news=True))
    except Exception as exc:  # noqa: BLE001
        return f"News search failed: {exc}"


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="web_search",
            description="Search the web. Returns titles, URLs and snippets.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "search query"},
                    "count": {"type": "integer", "description": "max results (1-10)"},
                },
                "required": ["query"],
            },
            func=web_search,
        )
    )
    registry.register(
        Tool(
            name="search_news",
            description="Search the news. Empty query = top headlines.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "news topic (optional)"},
                    "count": {"type": "integer", "description": "max results (1-10)"},
                },
                "required": [],
            },
            func=search_news,
        )
    )
