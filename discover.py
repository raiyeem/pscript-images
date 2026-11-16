"""Discover product URLs from a category page (crawl step). Discovery only; nothing is downloaded.

Source of truth: the CollectionPage JSON-LD in the category page's initial HTML.
ItemList entries are read from mainEntity.itemListElement.

Criteria keys read:
  politeness.user_agent, crawl.max_urls_per_category, crawl.same_host_only,
  crawl.log_path
Not used here yet: crawl.delay_seconds (one request per call, so nothing to wait between).
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any
from urllib.parse import urlsplit

import requests

import pipeline
from criteria import Criteria

PRODUCT_PATH = "/en/product/"
_JSON_LD = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_MAX_ITEM_DEPTH = 4


def _find_collection_pages(node: Any) -> list[dict[str, Any]]:
    """Every dict with @type CollectionPage, at any depth."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("@type") == "CollectionPage":
            found.append(node)
        for value in node.values():
            found.extend(_find_collection_pages(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_find_collection_pages(value))
    return found


def _url_from_entry(entry: Any, depth: int = 0) -> str | None:
    """Accepts a bare URL string, {url: ...}, or {item: {...}} nested up to a few levels."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and depth <= _MAX_ITEM_DEPTH:
        if isinstance(entry.get("url"), str):
            return entry["url"]
        if "item" in entry:
            return _url_from_entry(entry["item"], depth + 1)
    return None


def _item_list_urls(page: dict[str, Any]) -> list[str]:
    main = page.get("mainEntity")
    if not isinstance(main, dict) or main.get("@type") != "ItemList":
        return []
    entries = main.get("itemListElement") or []
    urls = [_url_from_entry(entry) for entry in entries]
    return [url for url in urls if url]


def extract_collection_urls(html: str) -> list[str]:
    """All ItemList URLs from CollectionPage JSON-LD blocks, in document order. Malformed blocks are skipped."""
    urls: list[str] = []
    for raw in _JSON_LD.findall(html):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for page in _find_collection_pages(data):
            urls.extend(_item_list_urls(page))
    return urls


def discover_product_urls(category_url: str, criteria: Criteria) -> list[str]:
    """Product URLs listed on a category page. Logs one line per call to crawl.log_path."""
    try:
        urls = _discover(category_url, criteria)
    except RuntimeError as exc:
        _log(criteria, category_url, 0, str(exc))
        raise
    _log(criteria, category_url, len(urls), "")
    return urls


def _discover(category_url: str, criteria: Criteria) -> list[str]:
    try:
        response = requests.get(
            category_url,
            headers={"User-Agent": criteria.politeness.user_agent},
            timeout=(criteria.politeness.connect_timeout_s, criteria.politeness.read_timeout_s),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"request failed for {category_url}: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} fetching {category_url}")

    candidates = extract_collection_urls(response.text)
    candidates = [url for url in candidates if PRODUCT_PATH in url]
    if criteria.crawl.same_host_only:
        host = urlsplit(category_url).netloc.lower()
        candidates = [url for url in candidates if urlsplit(url).netloc.lower() == host]

    unique = list(dict.fromkeys(candidates))
    cap = criteria.crawl.max_urls_per_category
    if len(unique) > cap:
        print(
            f"warning: {len(unique)} product URLs found, capped at {cap} (max_urls_per_category)",
            file=sys.stderr,
        )
        unique = unique[:cap]
    return unique


def _log(criteria: Criteria, category_url: str, count: int, error: str) -> None:
    line = f"{pipeline.utc_now_iso()} | {category_url} | {count} | {error or '-'}"
    pipeline.append_log(criteria.crawl.log_path, line)
