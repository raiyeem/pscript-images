"""Tests for --crawl-and-save. Discovery, browser, extraction, and downloads are faked. Everything runs in tmp_path."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import discover  # noqa: E402
import pipeline  # noqa: E402
import scrape  # noqa: E402
from download import DownloadResult  # noqa: E402
from extract import ImageCandidate  # noqa: E402
from pipeline import MANIFEST_COLUMNS  # noqa: E402

CATEGORY_URL = "https://foremarket.se/en/explore?category=putter"
PRODUCTS = [f"https://foremarket.se/en/product/prod-{n}" for n in (1, 2, 3)]


def _write_criteria(tmp_path: Path, max_products: int = 3) -> Path:
    """A criteria.yml copy with every output path inside tmp_path and robots off."""
    data = yaml.safe_load((REPO_ROOT / "criteria.yml").read_text(encoding="utf-8"))
    base = tmp_path / "out"
    images = base / "images"
    data["output"].update(
        {
            "root": str(images),
            "manifest": str(images / "manifest.csv"),
            "scrape_log": str(base / "scrape_log.txt"),
            "unclassified_log": str(base / "unclassified.log"),
            "coverage_report": str(base / "coverage.json"),
            "review_dir": str(base / "review"),
            "filtered_log": str(base / "filtered.log"),
            "conversion_errors_log": str(base / "conversion_errors.log"),
            "failed_dir": str(images / "_failed"),
            "tmp_dir": str(images / "_tmp"),
        }
    )
    data["fields"]["brand"]["review_queue"] = str(base / "review" / "brands_unknown.csv")
    data["politeness"]["respect_robots"] = False
    data["politeness"]["delay_seconds"] = 0
    data["crawl"]["log_path"] = str(base / "crawl.log")
    data["crawl"]["api"]["max_products_per_category"] = max_products
    path = tmp_path / "criteria.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _candidates_for(product_url: str) -> list[ImageCandidate]:
    slug = product_url.rsplit("/", 1)[-1]
    return [
        ImageCandidate(url=f"https://img.test/{slug}-{i}.jpg", alt=f"{slug} {i}", heading=None, specs={}, jsonld=None)
        for i in (1, 2)
    ]


class _FakePage:
    url = CATEGORY_URL

    def goto(self, url, wait_until=None):
        self.url = url


class _FakeBrowser:
    def new_page(self):
        return _FakePage()

    def close(self):
        pass


class _FakePlaywright:
    class chromium:  # noqa: N801 - mirrors the real attribute name
        @staticmethod
        def launch(headless=True):
            return _FakeBrowser()


class _FakeContext:
    def __enter__(self):
        return _FakePlaywright()

    def __exit__(self, *exc):
        return False


class DownloadSpy:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url, dest, page=None, *, criteria):
        self.calls.append(url)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        path = dest.with_name(dest.name + ".jpg")
        data = f"bytes-for-{url}".encode()
        path.write_bytes(data)
        return DownloadResult("ok", len(data), "image/jpeg", None, str(path))


@pytest.fixture
def run(monkeypatch):
    """Fake the browser, extraction, downloads, and discovery. Returns the recorders."""
    events: list[str] = []
    spy = DownloadSpy()

    def fake_extract(page, criteria, filtered=None):
        events.append(f"extract:{page.url}")
        if page.url in fail_on:
            raise RuntimeError(fail_on[page.url])
        return _candidates_for(page.url)

    fail_on: dict[str, str] = {}
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: _FakeContext())
    monkeypatch.setattr("extract.extract_images", fake_extract)
    monkeypatch.setattr("download.download_image", spy)
    monkeypatch.setattr(discover, "discover_product_urls", lambda category_url, criteria: list(PRODUCTS))
    monkeypatch.setattr(pipeline, "reset_outputs", lambda criteria: events.append("reset"))
    return {"events": events, "spy": spy, "fail_on": fail_on}


def _product_log_lines(criteria_path: Path) -> list[str]:
    log = criteria_path.parent / "out" / "crawl.log"
    if not log.exists():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if "product=" in line]


def test_crawl_save_processes_each_url(tmp_path, run, capsys):
    criteria_path = _write_criteria(tmp_path)

    code = scrape.main(["--crawl-and-save", CATEGORY_URL, "--save", "--criteria", str(criteria_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert [e for e in run["events"] if e.startswith("extract:")] == [f"extract:{p}" for p in PRODUCTS]
    assert len(run["spy"].calls) == 6  # two images per product
    lines = _product_log_lines(criteria_path)
    assert len(lines) == 3
    assert all("result=ok" in line for line in lines)
    assert "[1/3]" in out and "[2/3]" in out and "[3/3]" in out


def test_crawl_save_continues_on_failure(tmp_path, run, capsys):
    criteria_path = _write_criteria(tmp_path)
    run["fail_on"][PRODUCTS[1]] = "boom"

    code = scrape.main(["--crawl-and-save", CATEGORY_URL, "--save", "--criteria", str(criteria_path)])

    out = capsys.readouterr().out
    assert code == 0
    calls = run["spy"].calls
    assert any("prod-1-" in url for url in calls)
    assert any("prod-3-" in url for url in calls)
    assert not any("prod-2-" in url for url in calls)
    lines = _product_log_lines(criteria_path)
    failed = [line for line in lines if "result=failed" in line]
    assert len(failed) == 1 and "error=boom" in failed[0] and PRODUCTS[1] in failed[0]
    assert "[2/3] failed: boom" in out
    assert "Crawl complete: 2 products processed, 1 failed" in out


def test_crawl_save_reset_only_once(tmp_path, run):
    criteria_path = _write_criteria(tmp_path)

    scrape.main(["--crawl-and-save", CATEGORY_URL, "--save", "--reset", "--criteria", str(criteria_path)])

    events = run["events"]
    assert events.count("reset") == 1
    assert events[0] == "reset"  # before the first product is extracted


def test_crawl_save_requires_save_flag(tmp_path, capsys):
    criteria_path = _write_criteria(tmp_path)

    code = scrape.main(["--crawl-and-save", CATEGORY_URL, "--criteria", str(criteria_path)])

    assert code == 2
    assert "requires --save" in capsys.readouterr().err


def test_crawl_save_accumulates_totals(tmp_path, run, capsys):
    criteria_path = _write_criteria(tmp_path)
    # Seed one of product 1's candidates so it is skipped on resume.
    manifest = tmp_path / "out" / "images" / "manifest.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    seeded = _candidates_for(PRODUCTS[0])[0].url
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "file": str(tmp_path / "old.jpg"),
                "category": "Putter",
                "brand": "unknown",
                "brand_raw": "",
                "brand_source": "missing",
                "condition": "unknown",
                "angle": "unknown",
                "source_url": seeded,
                "scraped_at": "2000-01-01T00:00:00+00:00",
                "sha256": "0" * 64,
                "criteria_version": "seed",
                "status": "ok",
                "error": "",
            }
        )

    scrape.main(["--crawl-and-save", CATEGORY_URL, "--save", "--criteria", str(criteria_path)])

    out = capsys.readouterr().out
    assert "Crawl complete: 3 products processed, 0 failed, 5 total images downloaded, 1 skipped" in out
