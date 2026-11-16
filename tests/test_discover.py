"""Tests for discover.discover_product_urls. requests.get is mocked; the log goes to tmp_path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import discover  # noqa: E402
from criteria import load_criteria  # noqa: E402

CATEGORY_URL = "https://foremarket.se/en/explore?category=driver"
A = "https://foremarket.se/en/product/aaaa1111-0000-4000-8000-000000000001"
B = "https://foremarket.se/en/product/bbbb2222-0000-4000-8000-000000000002"
C = "https://foremarket.se/en/product/cccc3333-0000-4000-8000-000000000003"


def _criteria(tmp_path: Path, max_urls: int = 100):
    base = load_criteria(REPO_ROOT / "criteria.yml")
    crawl = base.crawl.model_copy(
        update={"log_path": str(tmp_path / "crawl.log"), "max_urls_per_category": max_urls}
    )
    return base.model_copy(update={"crawl": crawl})


def _page(entries: list, extra_blocks: list | None = None) -> str:
    collection = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Explore",
        "mainEntity": {"@type": "ItemList", "itemListElement": entries},
    }
    blocks = [collection, *(extra_blocks or [])]
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(block)}</script>' for block in blocks
    )
    return f"<html><head>{scripts}</head><body></body></html>"


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _serve(monkeypatch, html: str, status: int = 200) -> None:
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: _FakeResponse(status, html))


def test_discover_extracts_itemlist_urls(tmp_path, monkeypatch):
    entries = [{"item": {"url": A}}, {"item": {"url": B}}, {"item": {"url": C}}]
    _serve(monkeypatch, _page(entries))

    urls = discover.discover_product_urls(CATEGORY_URL, _criteria(tmp_path))

    assert urls == [A, B, C]


def test_discover_handles_item_shapes(tmp_path, monkeypatch):
    entries = [
        {"item": {"url": A}},  # item.url
        {"url": B},  # bare url object
        {"item": {"item": {"url": C}}},  # item.url nested deeper
    ]
    _serve(monkeypatch, _page(entries))

    urls = discover.discover_product_urls(CATEGORY_URL, _criteria(tmp_path))

    assert urls == [A, B, C]


def test_discover_dedupes_preserving_order(tmp_path, monkeypatch):
    entries = [{"item": {"url": A}}, {"item": {"url": B}}, {"item": {"url": A}}, {"item": {"url": C}}]
    _serve(monkeypatch, _page(entries))

    urls = discover.discover_product_urls(CATEGORY_URL, _criteria(tmp_path))

    assert urls == [A, B, C]


def test_discover_filters_by_product_path(tmp_path, monkeypatch):
    entries = [
        {"item": {"url": A}},
        {"item": {"url": "https://foremarket.se/en/about"}},
        {"item": {"url": B}},
    ]
    _serve(monkeypatch, _page(entries))

    urls = discover.discover_product_urls(CATEGORY_URL, _criteria(tmp_path))

    assert urls == [A, B]


def test_discover_respects_max_cap(tmp_path, monkeypatch, capsys):
    entries = [{"item": {"url": A}}, {"item": {"url": B}}, {"item": {"url": C}}]
    _serve(monkeypatch, _page(entries))

    urls = discover.discover_product_urls(CATEGORY_URL, _criteria(tmp_path, max_urls=2))

    assert urls == [A, B]
    assert "capped at 2" in capsys.readouterr().err


def test_discover_raises_on_non_200(tmp_path, monkeypatch):
    _serve(monkeypatch, "server error", status=500)

    with pytest.raises(RuntimeError, match="HTTP 500"):
        discover.discover_product_urls(CATEGORY_URL, _criteria(tmp_path))


def test_discover_logs_to_crawl_log(tmp_path, monkeypatch):
    criteria = _criteria(tmp_path)
    _serve(monkeypatch, _page([{"item": {"url": A}}, {"item": {"url": B}}]))

    discover.discover_product_urls(CATEGORY_URL, criteria)

    lines = Path(criteria.crawl.log_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # one line per call
    assert CATEGORY_URL in lines[0]
    assert lines[0].rstrip().endswith("| 2 | -")


def test_crawl_respects_robots(tmp_path, monkeypatch, capsys):
    import yaml

    import scrape

    data = yaml.safe_load((REPO_ROOT / "criteria.yml").read_text(encoding="utf-8"))
    data["politeness"]["respect_robots"] = True
    data["crawl"]["log_path"] = str(tmp_path / "crawl.log")
    criteria_path = tmp_path / "criteria.yml"
    criteria_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _serve_robots_and_fail_on_discovery(monkeypatch, "User-agent: *\nDisallow: /en/explore\n")

    code = scrape.main(["--crawl", CATEGORY_URL, "--criteria", str(criteria_path)])

    assert code == 1
    assert "Disallow: /en/explore" in capsys.readouterr().err
    assert not (tmp_path / "crawl.log").exists()  # nothing logged when blocked


def _serve_robots_and_fail_on_discovery(monkeypatch, robots_text: str) -> None:
    """robots.txt comes back as given. Any other fetch fails the test: discovery must not run."""

    def fake_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return _FakeResponse(200, robots_text)
        raise AssertionError(f"discovery should not fetch {url} when blocked")

    monkeypatch.setattr(requests, "get", fake_get)
