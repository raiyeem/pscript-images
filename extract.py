"""Extract product image candidates from a loaded product detail page.

Criteria keys read:
  extraction.jsonld_types          which JSON-LD @type values count as the product block
  extraction.min_dimension         reject images smaller than this on either side
  extraction.excluded_extensions   reject images with these extensions
  extraction.scroll_steps          number of scroll steps used to trigger lazy loading
  extraction.scroll_wait_ms        wait after each scroll step, in milliseconds
  extraction.wait_for_selector     element whose presence proves SSR content is rendered
  extraction.wait_timeout_ms       timeout for both readiness waits, in milliseconds
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from criteria import Criteria, Extraction


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    alt: str | None
    heading: str | None
    specs: dict[str, str]
    jsonld: dict[str, Any] | None


@dataclass(frozen=True)
class Filtered:
    src: str | None
    alt: str | None
    reason: str


_COLLECT_JS = """
() => {
  const heads = [...document.querySelectorAll('h1,h2')];
  const headingFor = (el) => {
    let best = null;
    for (const h of heads) {
      if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) best = h;
    }
    return best ? best.textContent.trim() : null;
  };
  const imgs = [...document.querySelectorAll('img')].map(img => ({
    src: img.getAttribute('src'),
    alt: img.getAttribute('alt'),
    heading: headingFor(img),
    naturalWidth: img.naturalWidth,
    naturalHeight: img.naturalHeight,
  }));
  const specs = [];
  for (const dt of document.querySelectorAll('dt')) {
    const dd = dt.nextElementSibling;
    if (dd && dd.tagName === 'DD') specs.push([dt.textContent.trim(), dd.textContent.trim()]);
  }
  const jsonld = [...document.querySelectorAll('script[type="application/ld+json"]')]
    .map(s => s.textContent);
  return { imgs, specs, jsonld };
}
"""


_LARGE_IMAGE_JS = """
(minDim) => [...document.querySelectorAll('img')].some(
  img => img.naturalWidth >= minDim && img.naturalHeight >= minDim
)
"""


def _wait_until_ready(page: Any, settings: Extraction) -> None:
    """Block until SSR content and a large image are present, or raise RuntimeError.

    Never returns on timeout: an empty result must mean the page had no images,
    not that extraction gave up.
    """
    timeout = settings.wait_timeout_ms
    seconds = f"{timeout / 1000:g}s"
    selector = settings.wait_for_selector
    try:
        page.wait_for_selector(selector, state="attached", timeout=timeout)
    except PlaywrightTimeout as exc:
        raise RuntimeError(
            f"extraction timed out: selector {selector!r} not found after {seconds}"
        ) from exc

    minimum = settings.min_dimension
    try:
        page.wait_for_function(_LARGE_IMAGE_JS, arg=minimum, timeout=timeout)
    except PlaywrightTimeout as exc:
        raise RuntimeError(
            f"extraction timed out: no image with naturalWidth >= {minimum} "
            f"and naturalHeight >= {minimum} after {seconds}"
        ) from exc


def _scroll_to_load(page: Any, steps: int, wait_ms: int) -> None:
    """Scroll down in steps so lazy-loaded images request their src."""
    height = page.evaluate("() => document.documentElement.scrollHeight")
    viewport = page.evaluate("() => window.innerHeight")
    for step in range(1, steps + 1):
        target = round((height - viewport) * step / steps)
        page.evaluate("y => window.scrollTo(0, y)", target)
        page.wait_for_timeout(wait_ms)


def _extension(url: str) -> str:
    """File extension of the real image, unwrapping Next.js /_next/image?url=... links."""
    parts = urlsplit(url)
    path = parts.path
    if path.startswith("/_next/image"):
        inner = parse_qs(parts.query).get("url", [""])[0]
        path = urlsplit(inner).path or path
    return PurePosixPath(path).suffix.lower()


def _find_product_jsonld(raw_blocks: list[str], jsonld_types: list[str]) -> dict[str, Any] | None:
    """Return the first JSON-LD block whose @type is in jsonld_types, else None."""
    wanted = set(jsonld_types)
    for text in raw_blocks:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("@type")
            types = block_type if isinstance(block_type, list) else [block_type]
            if wanted.intersection(t for t in types if isinstance(t, str)):
                return block
    return None


def _build_specs(pairs: list[list[str]]) -> dict[str, str]:
    """Label -> value from dt/dd pairs. The first occurrence wins (desktop and mobile copies)."""
    specs: dict[str, str] = {}
    for label, value in pairs:
        if label and label not in specs:
            specs[label] = value
    return specs


def extract_images(
    page: Any,
    criteria: Criteria,
    filtered: list[Filtered] | None = None,
) -> list[ImageCandidate]:
    """Return product image candidates in DOM order, deduplicated by URL.

    Each rejected <img> is appended to `filtered` (when given) with a reason.
    """
    rejected = filtered if filtered is not None else []
    settings = criteria.extraction
    excluded = tuple(extension.lower() for extension in settings.excluded_extensions)

    _wait_until_ready(page, settings)
    _scroll_to_load(page, settings.scroll_steps, settings.scroll_wait_ms)
    raw = page.evaluate(_COLLECT_JS)

    specs = _build_specs(raw["specs"])
    jsonld = _find_product_jsonld(raw["jsonld"], settings.jsonld_types)

    candidates: list[ImageCandidate] = []
    seen: set[str] = set()
    for item in raw["imgs"]:
        src = item["src"]
        alt = item["alt"]
        if not src:
            rejected.append(Filtered(src=None, alt=alt, reason="no src"))
            continue

        url = urljoin(page.url, src)
        extension = _extension(url)
        if extension in excluded:
            rejected.append(Filtered(src=url, alt=alt, reason=f"excluded extension {extension}"))
            continue

        width, height = item["naturalWidth"], item["naturalHeight"]
        if width == 0 or height == 0:
            rejected.append(
                Filtered(src=url, alt=alt, reason="not loaded (naturalWidth or naturalHeight is 0)")
            )
            continue
        if width < settings.min_dimension or height < settings.min_dimension:
            rejected.append(Filtered(src=url, alt=alt, reason=f"too small {width}x{height}"))
            continue

        if url in seen:
            rejected.append(Filtered(src=url, alt=alt, reason="duplicate of an earlier image"))
            continue
        seen.add(url)

        candidates.append(
            ImageCandidate(
                url=url,
                alt=alt,
                heading=item["heading"],
                specs=specs,
                jsonld=jsonld,
            )
        )
    return candidates
