"""M10 tests: politeness delay, resume, and robots.txt. Everything runs in tmp_path.

Browser, extraction, and downloads are faked. requests.get and time.sleep are monkeypatched.
"""

from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

import pytest
import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scrape  # noqa: E402
from download import DownloadResult  # noqa: E402
from extract import ImageCandidate  # noqa: E402
from pipeline import MANIFEST_COLUMNS  # noqa: E402

PRODUCT_URL = "https://foremarket.se/product/example"


def _write_criteria(tmp_path: Path, respect_robots: bool, delay: float) -> Path:
    """A criteria.yml copy whose output paths all point inside tmp_path."""
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
    data["politeness"]["respect_robots"] = respect_robots
    data["politeness"]["delay_seconds"] = delay
    path = tmp_path / "criteria.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _candidates(count: int) -> list[ImageCandidate]:
    return [
        ImageCandidate(
            url=f"https://img.test/p{i}.jpg",
            alt=f"driver {i}",
            heading=None,
            specs={},
            jsonld=None,
        )
        for i in range(1, count + 1)
    ]


def _seed_file(tmp_path: Path, url: str) -> Path:
    """A real file under tmp_path that a seeded manifest row points at."""
    path = tmp_path / "out" / "images" / "Driver" / url.rsplit("/", 1)[-1]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"old-bytes-" + url.encode())
    return path


def _rows(manifest: Path) -> list[dict[str, str]]:
    with manifest.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _seed_manifest(criteria_path: Path, tmp_path: Path, urls: list[str]) -> None:
    manifest = tmp_path / "out" / "images" / "manifest.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for url in urls:
            writer.writerow(
                {
                    "file": _seed_file(tmp_path, url).as_posix(),
                    "category": "Driver",
                    "brand": "unknown",
                    "brand_raw": "",
                    "brand_source": "missing",
                    "condition": "unknown",
                    "angle": "unknown",
                    "source_url": url,
                    "scraped_at": "2000-01-01T00:00:00+00:00",
                    "sha256": "0" * 64,
                    "criteria_version": "seed",
                    "status": "ok",
                    "error": "",
                }
            )


class _FakePage:
    url = PRODUCT_URL

    def goto(self, url, wait_until=None):
        self.url = url


class _FakeBrowser:
    def new_page(self):
        return _FakePage()

    def close(self):
        pass


class _FakeChromium:
    def launch(self, headless=True):
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakeContext:
    def __enter__(self):
        return _FakePlaywright()

    def __exit__(self, *exc):
        return False


def _fake_sync_playwright():
    return _FakeContext()


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
def sleeps(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr(scrape.time, "sleep", lambda seconds: recorded.append(seconds))
    return recorded


@pytest.fixture
def fake_run(monkeypatch):
    """Patch the browser, extraction, and downloader for one --save run."""

    def setup(candidates: list[ImageCandidate]) -> DownloadSpy:
        monkeypatch.setattr("playwright.sync_api.sync_playwright", _fake_sync_playwright)
        monkeypatch.setattr(
            "extract.extract_images",
            lambda page, criteria, filtered=None: list(candidates),
        )
        spy = DownloadSpy()
        monkeypatch.setattr("download.download_image", spy)
        return spy

    return setup


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _fake_robots(monkeypatch, status: int, text: str = "") -> None:
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: _FakeResponse(status, text))


# --- politeness -------------------------------------------------------------


def test_politeness_sleep_between_downloads(tmp_path, fake_run, sleeps, capsys):
    spy = fake_run(_candidates(2))
    criteria_path = _write_criteria(tmp_path, respect_robots=False, delay=1.5)

    code = scrape.main([PRODUCT_URL, "--save", "--criteria", str(criteria_path)])

    assert code == 0
    assert len(spy.calls) == 2
    assert sleeps == [1.5]  # one wait between two downloads; none before the first or after the last
    assert "2 downloaded, 0 skipped, 0 failed" in capsys.readouterr().out


# --- resume -------------------------------------------------------------------


def test_resume_skips_known_urls(tmp_path, fake_run, sleeps, capsys):
    candidates = _candidates(3)
    spy = fake_run(candidates)
    criteria_path = _write_criteria(tmp_path, respect_robots=False, delay=0)
    _seed_manifest(criteria_path, tmp_path, [candidates[0].url, candidates[1].url])

    code = scrape.main([PRODUCT_URL, "--save", "--criteria", str(criteria_path)])

    assert code == 0
    assert spy.calls == [candidates[2].url]
    assert "1 downloaded, 2 skipped, 0 failed" in capsys.readouterr().out
    manifest = tmp_path / "out" / "images" / "manifest.csv"
    with manifest.open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 3  # 2 seeded + 1 new; skipped rows not appended


def test_resume_no_resume_flag_forces_download(tmp_path, fake_run, sleeps, capsys):
    candidates = _candidates(3)
    spy = fake_run(candidates)
    criteria_path = _write_criteria(tmp_path, respect_robots=False, delay=0)
    _seed_manifest(criteria_path, tmp_path, [candidates[0].url, candidates[1].url])

    code = scrape.main([PRODUCT_URL, "--save", "--criteria", str(criteria_path), "--no-resume"])

    assert code == 0
    assert len(spy.calls) == 3
    assert "3 downloaded, 0 skipped" in capsys.readouterr().out


# --- robots.txt ---------------------------------------------------------------


def test_no_resume_replaces_existing_row(tmp_path, fake_run, sleeps, capsys):
    candidates = _candidates(1)
    spy = fake_run(candidates)
    criteria_path = _write_criteria(tmp_path, respect_robots=False, delay=0)
    _seed_manifest(criteria_path, tmp_path, [candidates[0].url])
    manifest = tmp_path / "out" / "images" / "manifest.csv"
    before = _rows(manifest)[0]

    code = scrape.main([PRODUCT_URL, "--save", "--criteria", str(criteria_path), "--no-resume"])

    rows = _rows(manifest)
    assert code == 0
    assert spy.calls == [candidates[0].url]
    assert len(rows) == 1  # refreshed in place, no second row
    after = rows[0]
    expected_sha = hashlib.sha256(f"bytes-for-{candidates[0].url}".encode()).hexdigest()
    assert after["sha256"] == expected_sha
    assert after["sha256"] != before["sha256"]
    assert after["scraped_at"] > before["scraped_at"]
    assert Path(after["file"]).read_bytes() == f"bytes-for-{candidates[0].url}".encode()


def test_no_resume_preserves_file_path(tmp_path, fake_run, sleeps, capsys):
    candidates = _candidates(1)
    fake_run(candidates)
    criteria_path = _write_criteria(tmp_path, respect_robots=False, delay=0)
    _seed_manifest(criteria_path, tmp_path, [candidates[0].url])
    manifest = tmp_path / "out" / "images" / "manifest.csv"
    before = _rows(manifest)[0]
    folder = Path(before["file"]).parent

    scrape.main([PRODUCT_URL, "--save", "--criteria", str(criteria_path), "--no-resume"])

    after = _rows(manifest)[0]
    assert after["file"] == before["file"]  # file column is immutable under --no-resume
    assert "_002" not in after["file"]
    assert sorted(p.name for p in folder.iterdir()) == [Path(before["file"]).name]


def test_robots_disallowed_blocks_run(tmp_path, fake_run, sleeps, monkeypatch, capsys):
    spy = fake_run(_candidates(2))
    _fake_robots(monkeypatch, 200, "User-agent: *\nDisallow: /product/\n")
    criteria_path = _write_criteria(tmp_path, respect_robots=True, delay=0)

    code = scrape.main([PRODUCT_URL, "--save", "--criteria", str(criteria_path)])

    assert code == 1
    assert spy.calls == []
    err = capsys.readouterr().err
    assert "Disallow: /product/" in err
    assert "/product/example" in err
    assert not (tmp_path / "out").exists()  # nothing written, not even by --reset-style cleanup


def test_robots_missing_proceeds(tmp_path, fake_run, sleeps, monkeypatch, capsys):
    spy = fake_run(_candidates(2))
    _fake_robots(monkeypatch, 404)
    criteria_path = _write_criteria(tmp_path, respect_robots=True, delay=0)

    code = scrape.main([PRODUCT_URL, "--save", "--criteria", str(criteria_path)])

    assert code == 0
    assert len(spy.calls) == 2
    assert "HTTP 404" in capsys.readouterr().err


def test_robots_crawl_delay_respected(tmp_path, fake_run, sleeps, monkeypatch):
    spy = fake_run(_candidates(2))
    _fake_robots(monkeypatch, 200, "User-agent: *\nCrawl-delay: 5\n")
    criteria_path = _write_criteria(tmp_path, respect_robots=True, delay=1.5)

    code = scrape.main([PRODUCT_URL, "--save", "--criteria", str(criteria_path)])

    assert code == 0
    assert len(spy.calls) == 2
    assert sleeps == [5.0]  # Crawl-delay 5 beats delay_seconds 1.5
