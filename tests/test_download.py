"""Unit tests for download.download_image and download.convert_image.

No network and no browser. Fake responses stand in for requests and Playwright.
Existing download tests use image_format "original" because their fake bodies
are not real images, so conversion would fail on them by design.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import download  # noqa: E402
from criteria import load_criteria  # noqa: E402

PAGE_URL = "https://foremarket.se/en/product/example"
IMAGE_URL = "https://assets.foremarket.se/products/example-1.jpg"
JPEG_BYTES = b"\xff\xd8\xff\xe0test"


def _criteria(image_format: str = "original"):
    base = load_criteria(REPO_ROOT / "criteria.yml")
    output = base.output.model_copy(update={"image_format": image_format})
    return base.model_copy(update={"output": output})


def _webp_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(buffer, format="WEBP")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status_code, headers=None, chunks=(), raise_after=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self._raise_after = raise_after

    def iter_content(self, chunk_size=None):
        for chunk in self._chunks:
            yield chunk
        if self._raise_after is not None:
            raise self._raise_after

    def close(self):
        pass


class FakeApiResponse:
    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def body(self):
        return self._body


class FakePage:
    def __init__(self, api_response=None):
        self.url = PAGE_URL
        self.api_calls = []
        self._api_response = api_response
        self.context = SimpleNamespace(request=SimpleNamespace(get=self._get))

    def _get(self, url, **kwargs):
        self.api_calls.append((url, kwargs))
        return self._api_response


def _no_part_files(folder: Path) -> bool:
    return not list(folder.glob("*.part"))


# --- download flow (original format; fake bodies are not real images) -------


def test_fallback_on_403(tmp_path, monkeypatch):
    monkeypatch.setattr(
        download.requests, "get", lambda *a, **k: FakeResponse(403, {"content-type": "text/html"})
    )
    page = FakePage(FakeApiResponse(200, {"Content-Type": "image/jpeg"}, JPEG_BYTES))

    result = download.download_image(IMAGE_URL, tmp_path / "pic", page=page, criteria=_criteria())

    assert result.status == "ok"
    assert result.bytes_written == len(JPEG_BYTES)
    assert result.path == str(tmp_path / "pic.jpg")
    assert (tmp_path / "pic.jpg").read_bytes() == JPEG_BYTES
    assert _no_part_files(tmp_path)
    assert page.api_calls and page.api_calls[0][0] == IMAGE_URL


def test_no_part_file_on_http_error(tmp_path, monkeypatch):
    monkeypatch.setattr(download.requests, "get", lambda *a, **k: FakeResponse(500))

    result = download.download_image(IMAGE_URL, tmp_path / "pic", criteria=_criteria())

    assert result.status == "http_500"
    assert result.path is None
    assert list(tmp_path.iterdir()) == []


def test_no_part_file_on_timeout(tmp_path, monkeypatch):
    # Body starts streaming, then the read times out. The .part file must be removed.
    response = FakeResponse(
        200,
        {"content-type": "image/jpeg"},
        chunks=[b"partial-bytes"],
        raise_after=requests.exceptions.ReadTimeout("read timed out"),
    )
    monkeypatch.setattr(download.requests, "get", lambda *a, **k: response)

    result = download.download_image(IMAGE_URL, tmp_path / "pic", criteria=_criteria())

    assert result.status == "error"
    assert "timeout" in (result.error_message or "")
    assert result.path is None
    assert list(tmp_path.iterdir()) == []


def test_extension_from_content_type(tmp_path, monkeypatch):
    # URL has no extension, so the extension must come from content-type.
    monkeypatch.setattr(
        download.requests,
        "get",
        lambda *a, **k: FakeResponse(
            200, {"Content-Type": "image/png; charset=binary"}, chunks=[b"\x89PNG\r\n\x1a\n"]
        ),
    )

    result = download.download_image(
        "https://assets.foremarket.se/products/12345", tmp_path / "pic", criteria=_criteria()
    )

    assert result.status == "ok"
    assert result.content_type == "image/png"
    assert result.path == str(tmp_path / "pic.png")
    assert (tmp_path / "pic.png").exists()
    assert _no_part_files(tmp_path)


# --- conversion ------------------------------------------------------------


def test_convert_webp_to_jpeg(tmp_path):
    source = tmp_path / "source.webp"
    source.write_bytes(_webp_bytes())

    out = download.convert_image(str(source), "jpeg", 90)

    assert Path(out).suffix == ".jpg"
    assert Path(out).read_bytes()[:3] == b"\xff\xd8\xff"
    assert not source.exists()


def test_convert_keeps_original_on_error(tmp_path):
    source = tmp_path / "bad.webp"
    source.write_bytes(b"not an image")

    with pytest.raises(RuntimeError) as info:
        download.convert_image(str(source), "jpeg", 90)

    assert "bad.webp" in str(info.value)
    assert source.exists()
    assert source.read_bytes() == b"not an image"


def test_download_converts_webp_body_to_jpeg(tmp_path, monkeypatch):
    webp = _webp_bytes()
    monkeypatch.setattr(
        download.requests,
        "get",
        lambda *a, **k: FakeResponse(200, {"Content-Type": "image/webp"}, chunks=[webp]),
    )

    result = download.download_image(
        "https://assets.foremarket.se/products/example-1.webp", tmp_path / "pic", criteria=_criteria("jpeg")
    )

    assert result.status == "ok"
    assert result.content_type == "image/jpeg"
    assert result.path == str(tmp_path / "pic.jpg")
    assert (tmp_path / "pic.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    assert not (tmp_path / "pic.webp").exists()
    assert _no_part_files(tmp_path)
