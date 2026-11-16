"""Download one image to disk, then convert it to the configured format.

Primary path: requests. If it returns 403 and a Playwright page is supplied,
retry through the page's request context (same browser session).

Flow: body -> <original>.part -> convert_image (per criteria.output.image_format)
-> final file. Every exit path leaves no .part file behind.

Policy values (user agent, timeouts, output format) come from criteria.yml.
CONTENT_TYPE_EXTENSIONS is a protocol mapping (MIME type -> extension), not policy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit

import requests
from PIL import Image

from criteria import Criteria

CHUNK_SIZE = 64 * 1024
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
FORMAT_EXTENSIONS = {"jpeg": ".jpg", "png": ".png"}
FORMAT_CONTENT_TYPES = {"jpeg": "image/jpeg", "png": "image/png"}
FORMAT_PIL_NAMES = {"jpeg": "JPEG", "png": "PNG"}
PART_SUFFIX = ".part"


@dataclass(frozen=True)
class DownloadResult:
    status: str  # ok | http_403 | http_<status> | error
    bytes_written: int = 0
    content_type: str | None = None
    error_message: str | None = None
    path: str | None = None


def _content_type(headers: Any) -> str | None:
    """Lower-cased media type without parameters, from requests or Playwright headers."""
    value = next((v for k, v in headers.items() if k.lower() == "content-type"), None)
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower()


def _request_headers(criteria: Criteria, page: Any | None) -> dict[str, str]:
    headers = {"User-Agent": criteria.politeness.user_agent}
    if page is not None:
        headers["Referer"] = page.url
    return headers


def _timeout(criteria: Criteria) -> tuple[float, float]:
    return (criteria.politeness.connect_timeout_s, criteria.politeness.read_timeout_s)


def _resolve_path(dest: Path, url: str, content_type: str | None) -> Path | None:
    """Path for the downloaded bytes, with an extension. None if no extension can be determined.

    A dest that already has a suffix is used as given. Otherwise the extension
    comes from the URL, then from the content-type. Never writes a file with
    no extension.
    """
    if dest.suffix:
        return dest
    url_extension = PurePosixPath(urlsplit(url).path).suffix.lower()
    extension = url_extension or CONTENT_TYPE_EXTENSIONS.get(content_type or "")
    if not extension:
        return None
    return dest.with_name(dest.name + extension)


def _output_path(src: Path, target_format: str) -> Path:
    """Converted path: the .part suffix is dropped, then the target extension is applied."""
    name = src.name
    if name.endswith(PART_SUFFIX):
        name = name[: -len(PART_SUFFIX)]
    return src.with_name(name).with_suffix(FORMAT_EXTENSIONS[target_format])


def convert_image(src_path: str | Path, target_format: str, jpeg_quality: int) -> str:
    """Convert an image file to target_format ("jpeg", "png", or "original").

    Returns the path of the converted file. Returns src_path unchanged when no
    conversion is needed. On success the source file is deleted. On any failure
    a RuntimeError is raised and the source file is left in place.
    """
    src = Path(src_path)
    if target_format == "original":
        return str(src)
    if target_format not in FORMAT_PIL_NAMES:
        raise RuntimeError(f"unknown image_format {target_format!r}")

    try:
        with Image.open(src) as img:
            if img.format == FORMAT_PIL_NAMES[target_format]:
                return str(src)
            out = _output_path(src, target_format)
            if out == src:
                raise ValueError(f"conversion would overwrite the source file {src}")
            if target_format == "jpeg":
                working = img.convert("RGB")  # JPEG has no alpha channel
                save_kwargs: dict[str, Any] = {"quality": jpeg_quality}
            else:
                working = img.convert("RGBA")  # keep alpha for PNG
                save_kwargs = {}
            try:
                working.save(out, format=FORMAT_PIL_NAMES[target_format], **save_kwargs)
            except Exception:
                out.unlink(missing_ok=True)  # remove a partial output; the source is untouched
                raise
    except Exception as exc:
        raise RuntimeError(f"image conversion failed for {src}: {exc}") from exc

    src.unlink()
    return str(out)


def _store(original: Path, chunks: Iterable[bytes], content_type: str | None, criteria: Criteria) -> DownloadResult:
    """Write the body to <original>.part, convert it, and produce the final file.

    Guarantee: no .part file survives this function. The outer finally removes
    it on every path. A failed conversion keeps the downloaded bytes under the
    original name and reports status "error".
    """
    part = original.with_name(original.name + PART_SUFFIX)
    try:
        return _store_inner(original, part, chunks, content_type, criteria)
    except Exception as exc:  # never raise out of a download
        return DownloadResult("error", error_message=f"{type(exc).__name__}: {exc}", content_type=content_type)
    finally:
        if part.exists():
            part.unlink(missing_ok=True)


def _store_inner(
    original: Path,
    part: Path,
    chunks: Iterable[bytes],
    content_type: str | None,
    criteria: Criteria,
) -> DownloadResult:
    written = 0
    try:
        original.parent.mkdir(parents=True, exist_ok=True)
        with part.open("wb") as handle:
            for chunk in chunks:
                if chunk:
                    handle.write(chunk)
                    written += len(chunk)
    except requests.exceptions.Timeout as exc:
        return DownloadResult("error", written, content_type, f"timeout while writing: {exc}")
    except Exception as exc:  # every failure becomes a result, never an exception
        return DownloadResult("error", written, content_type, f"{type(exc).__name__}: {exc}")

    output_format = criteria.output.image_format
    try:
        converted = Path(convert_image(part, output_format, criteria.output.jpeg_quality))
    except RuntimeError as exc:
        os.replace(part, original)  # keep the downloaded bytes; never delete them on a failed conversion
        return DownloadResult(
            "error",
            written,
            content_type,
            f"{exc}; downloaded bytes kept as {original.name}",
            str(original),
        )

    if converted == part:  # format "original", or the source already had the target format
        os.replace(part, original)
        final = original
    else:  # convert_image wrote the converted file and deleted the .part source
        final = converted

    final_type = content_type if output_format == "original" else FORMAT_CONTENT_TYPES[output_format]
    return DownloadResult("ok", written, final_type, None, str(final))


def _save_primary(
    response: requests.Response, url: str, dest: Path, content_type: str | None, criteria: Criteria
) -> DownloadResult:
    original = _resolve_path(dest, url, content_type)
    if original is None:
        return DownloadResult(
            "error",
            content_type=content_type,
            error_message=f"no file extension from URL or content-type {content_type!r}",
        )
    return _store(original, response.iter_content(chunk_size=CHUNK_SIZE), content_type, criteria)


def _fallback(url: str, dest: Path, page: Any, criteria: Criteria) -> DownloadResult:
    """Retry a 403 through the Playwright page's request context."""
    try:
        api = page.context.request.get(url, headers=_request_headers(criteria, page))
    except Exception as exc:
        return DownloadResult("error", error_message=f"fallback request failed: {exc}")

    content_type = _content_type(api.headers)
    if api.status == 403:
        return DownloadResult("http_403", content_type=content_type, error_message="fallback HTTP 403")
    if api.status != 200:
        return DownloadResult(
            "error", content_type=content_type, error_message=f"fallback HTTP {api.status}"
        )

    original = _resolve_path(dest, url, content_type)
    if original is None:
        return DownloadResult(
            "error",
            content_type=content_type,
            error_message=f"no file extension from URL or content-type {content_type!r}",
        )
    try:
        body = api.body()
    except Exception as exc:
        return DownloadResult(
            "error", content_type=content_type, error_message=f"fallback body read failed: {exc}"
        )
    return _store(original, [body], content_type, criteria)


def download_image(url: str, dest: Path | str, page: Any | None = None, *, criteria: Criteria) -> DownloadResult:
    """Download url, convert per criteria.output.image_format, and return a DownloadResult.

    dest may omit the extension; it is then taken from the URL or the content-type.
    """
    dest = Path(dest)
    try:
        response = requests.get(
            url,
            headers=_request_headers(criteria, page),
            timeout=_timeout(criteria),
            stream=True,
        )
    except requests.exceptions.Timeout as exc:
        return DownloadResult("error", error_message=f"timeout connecting: {exc}")
    except requests.exceptions.RequestException as exc:
        return DownloadResult("error", error_message=f"request failed: {exc}")

    try:
        status = response.status_code
        content_type = _content_type(response.headers)
        if status == 200:
            return _save_primary(response, url, dest, content_type, criteria)
        if status == 403 and page is not None:
            return _fallback(url, dest, page, criteria)
        return DownloadResult(
            f"http_{status}", content_type=content_type, error_message=f"HTTP {status}"
        )
    finally:
        response.close()
