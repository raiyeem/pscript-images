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


def _criteria(
    tmp_path: Path,
    max_urls: int = 100,
    category_ids: dict[str, int] | None = None,
    max_products: int = 50,
):
    """Defaults to an empty category map, so these tests exercise the JSON-LD path only."""
    base = load_criteria(REPO_ROOT / "criteria.yml")
    api = base.crawl.api.model_copy(update={"max_products_per_category": max_products})
    crawl = base.crawl.model_copy(
        update={
            "log_path": str(tmp_path / "crawl.log"),
            "max_urls_per_category": max_urls,
            "category_ids": {} if category_ids is None else category_ids,
            "api": api,
        }
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
    assert "| method=jsonld | 2 | 0 | -" in lines[0]


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


# --- API pagination -----------------------------------------------------------


class _FakePostResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = json.dumps(self._payload).encode()

    def json(self):
        return self._payload


def _product_id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _api_page(offset: int, limit: int, total: int) -> dict:
    ids = [_product_id(i) for i in range(offset, min(offset + limit, total))]
    return {"totalCount": total, "data": [{"id": pid} for pid in ids]}


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(discover.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


def _serve_api(monkeypatch, responder) -> list[dict]:
    """responder(body) -> _FakePostResponse. Returns the list of request bodies sent."""
    bodies: list[dict] = []

    def fake_post(url, headers=None, data=None, timeout=None):
        body = json.loads(data)
        bodies.append(body)
        return responder(body)

    monkeypatch.setattr(requests, "post", fake_post)
    return bodies


def test_discover_api_paginates(tmp_path, monkeypatch, no_sleep):
    criteria = _criteria(tmp_path, category_ids={"driver": 1}, max_products=36)
    bodies = _serve_api(
        monkeypatch,
        lambda body: _FakePostResponse(200, _api_page(body["offset"], body["limit"], total=255)),
    )

    urls = discover.discover_product_urls(CATEGORY_URL, criteria)

    assert len(urls) == 36
    assert urls[0] == f"https://foremarket.se/en/product/{_product_id(0)}"
    assert urls[-1] == f"https://foremarket.se/en/product/{_product_id(35)}"
    assert [b["offset"] for b in bodies] == [0, 12, 24]
    assert all(b["categoryIds"] == [1] for b in bodies)
    assert len(no_sleep) == 2  # a delay between each pair of page requests, none before the first


def test_discover_api_stops_at_cap(tmp_path, monkeypatch, no_sleep):
    criteria = _criteria(tmp_path, category_ids={"driver": 1}, max_products=5)
    bodies = _serve_api(
        monkeypatch,
        lambda body: _FakePostResponse(200, _api_page(body["offset"], body["limit"], total=255)),
    )

    urls = discover.discover_product_urls(CATEGORY_URL, criteria)

    assert len(urls) == 5
    assert len(bodies) == 1  # one 12-item page covers the cap of 5


def test_discover_falls_back_to_jsonld_on_api_500(tmp_path, monkeypatch, no_sleep):
    criteria = _criteria(tmp_path, category_ids={"driver": 1})
    _serve_api(monkeypatch, lambda body: _FakePostResponse(500))
    _serve(monkeypatch, _page([{"item": {"url": A}}, {"item": {"url": B}}, {"item": {"url": C}}]))

    urls = discover.discover_product_urls(CATEGORY_URL, criteria)

    assert urls == [A, B, C]
    line = Path(criteria.crawl.log_path).read_text(encoding="utf-8").splitlines()[0]
    assert "method=jsonld" in line
    assert "api HTTP 500" in line


def test_discover_api_unknown_category_uses_jsonld(tmp_path, monkeypatch, no_sleep):
    criteria = _criteria(tmp_path, category_ids={"putter": 4})  # driver is not in the map
    bodies = _serve_api(monkeypatch, lambda body: pytest.fail("API must not be called"))
    _serve(monkeypatch, _page([{"item": {"url": A}}]))

    urls = discover.discover_product_urls(CATEGORY_URL, criteria)

    assert urls == [A]
    assert bodies == []


def test_discover_logs_method(tmp_path, monkeypatch, no_sleep):
    api_criteria = _criteria(tmp_path, category_ids={"driver": 1}, max_products=12)
    _serve_api(
        monkeypatch,
        lambda body: _FakePostResponse(200, _api_page(body["offset"], body["limit"], total=255)),
    )
    discover.discover_product_urls(CATEGORY_URL, api_criteria)

    jsonld_criteria = _criteria(tmp_path / "second", category_ids={})
    (tmp_path / "second").mkdir()
    _serve(monkeypatch, _page([{"item": {"url": A}}]))
    discover.discover_product_urls(CATEGORY_URL, jsonld_criteria)

    api_line = Path(api_criteria.crawl.log_path).read_text(encoding="utf-8").splitlines()[0]
    jsonld_line = Path(jsonld_criteria.crawl.log_path).read_text(encoding="utf-8").splitlines()[0]
    assert "method=api | 12 | 1 | -" in api_line
    assert "method=jsonld | 1 | 0 | -" in jsonld_line
