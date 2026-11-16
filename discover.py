"""Discover product URLs from a category page (crawl step). Discovery only; nothing is downloaded.

Two methods, tried in this order:
  api     POST to the listing filter API, paging by offset. Used only for categories
          listed in crawl.category_ids (IDs verified against the site).
  jsonld  CollectionPage ItemList in the category page's initial HTML. Used for every
          category not in the map, and as the fallback when the API fails.

Criteria keys read:
  politeness.user_agent, politeness.connect_timeout_s, politeness.read_timeout_s
  crawl.max_urls_per_category, crawl.same_host_only, crawl.log_path, crawl.delay_seconds
  crawl.api.url, crawl.api.page_size, crawl.api.max_products_per_category
  crawl.category_ids
"""

from __future__ import annotations

import json
import re
import sys
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

import pipeline
from criteria import Criteria

PRODUCT_PATH = "/en/product/"
_JSON_LD = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_MAX_ITEM_DEPTH = 4


class _ApiError(RuntimeError):
    pass


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


def category_name(category_url: str) -> str | None:
    """?category=driver -> 'driver'."""
    values = parse_qs(urlsplit(category_url).query).get("category")
    return values[0].strip().lower() if values and values[0].strip() else None


def discover_product_urls(category_url: str, criteria: Criteria) -> list[str]:
    """Product URLs for a category. Logs one line per call to crawl.log_path."""
    method = "jsonld"
    pages = 0
    errors: list[str] = []
    try:
        category = category_name(category_url)
        category_id = criteria.crawl.category_ids.get(category) if category else None
        urls: list[str] = []
        if category_id is not None:
            try:
                urls, pages = _api_urls(category_url, category_id, criteria)
                method = "api"
            except _ApiError as exc:
                errors.append(str(exc))
        if method == "jsonld":
            urls = _jsonld_urls(category_url, criteria)
        urls = _finalize(urls, category_url, criteria)
    except RuntimeError as exc:
        _log(criteria, category_url, method, 0, pages, "; ".join(errors + [str(exc)]))
        raise
    _log(criteria, category_url, method, len(urls), pages, "; ".join(errors) or "-")
    return urls


def _api_urls(category_url: str, category_id: int, criteria: Criteria) -> tuple[list[str], int]:
    """Page through the filter API by offset. Returns (product URLs, pages fetched)."""
    api = criteria.crawl.api
    parts = urlsplit(category_url)
    base = f"{parts.scheme}://{parts.netloc}"
    headers = {"Content-Type": "application/json", "User-Agent": criteria.politeness.user_agent}
    timeout = (criteria.politeness.connect_timeout_s, criteria.politeness.read_timeout_s)
    cap = api.max_products_per_category

    urls: list[str] = []
    pages = 0
    offset = 0
    while offset < cap:
        if pages > 0:
            time.sleep(criteria.crawl.delay_seconds)
        body = {"offset": offset, "limit": api.page_size, "categoryIds": [category_id]}
        try:
            response = requests.post(api.url, headers=headers, data=json.dumps(body), timeout=timeout)
        except requests.RequestException as exc:
            raise _ApiError(f"api request failed at offset {offset}: {type(exc).__name__}") from exc
        pages += 1
        if response.status_code != 200:
            raise _ApiError(f"api HTTP {response.status_code} at offset {offset}")
        try:
            data = response.json().get("data", [])
        except ValueError as exc:
            raise _ApiError(f"api returned non-JSON at offset {offset}") from exc
        if not data:
            break
        for item in data:
            item_id = item.get("id") if isinstance(item, dict) else None
            if item_id:
                urls.append(f"{base}/en/product/{item_id}")
        offset += api.page_size
    return urls[:cap], pages


def _jsonld_urls(category_url: str, criteria: Criteria) -> list[str]:
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
    return extract_collection_urls(response.text)


def _finalize(urls: list[str], category_url: str, criteria: Criteria) -> list[str]:
    """Product-path filter, same-host filter, dedupe (order kept), then the cap."""
    candidates = [url for url in urls if PRODUCT_PATH in url]
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


def _log(
    criteria: Criteria,
    category_url: str,
    method: str,
    count: int,
    pages: int,
    errors: str,
) -> None:
    line = (
        f"{pipeline.utc_now_iso()} | {category_url} | method={method} | "
        f"{count} | {pages} | {errors or '-'}"
    )
    pipeline.append_log(criteria.crawl.log_path, line)
