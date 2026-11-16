"""Classification for saved images (M6): category, brand, and condition.

Criteria keys read:
  categories[*].name, categories[*].aliases, categories[*].keywords
  fields.brand.canonical, fields.brand.aliases, fields.brand.open_vocabulary,
  fields.brand.placeholders, fields.brand.review_queue
  fields.condition.enum, fields.condition.aliases, fields.condition.default
  extraction.specs_labels.category, extraction.specs_labels.brand,
  extraction.specs_labels.condition
  output.unclassified_log, naming.missing_token
"""

from __future__ import annotations

import csv
from datetime import date
from typing import Any

import pipeline
from criteria import Criteria

REVIEW_COLUMNS = ["raw_value", "count", "source_urls", "first_seen"]
SOURCE_URL_SEPARATOR = ";"


def first_spec(specs: dict[str, str], labels: list[str]) -> str:
    """First non-empty value among the given spec labels, or ''."""
    for label in labels:
        value = (specs.get(label) or "").strip()
        if value:
            return value
    return ""


def _category_from_spec(value: str, criteria: Criteria) -> str | None:
    wanted = value.strip().lower()
    for category in criteria.categories:
        names = {category.name.lower(), *(alias.lower() for alias in category.aliases)}
        if wanted in names:
            return category.name
    return None


def _keyword_category(text: str, criteria: Criteria) -> str | None:
    lowered = text.lower()
    for category in criteria.categories:
        if any(keyword.lower() in lowered for keyword in category.keywords):
            return category.name
    return None


def classify(text: str, specs: dict[str, Any], criteria: Criteria) -> str | None:
    """Canonical category name, or None. Spec Category first, then keywords in text.

    The caller decides whether None becomes "unknown".
    """
    spec_value = first_spec(specs, criteria.extraction.specs_labels.category)
    if spec_value:
        matched = _category_from_spec(spec_value, criteria)
        if matched is not None:
            return matched
    return _keyword_category(text, criteria)


def _split_urls(value: str) -> list[str]:
    return [part for part in (piece.strip() for piece in value.split(SOURCE_URL_SEPARATOR)) if part]


class ReviewCollector:
    """Collects unknown brands during a run and writes the review queue once at the end.

    Each row counts distinct source URLs: count == len(source_urls). Merging keeps
    existing rows, adds new URLs, and never double-counts a URL.
    """

    def __init__(self) -> None:
        self._pending: dict[str, list[str]] = {}

    def add(self, raw: str, product_url: str) -> None:
        """Record one product page where this raw brand was seen. Image URLs are never recorded."""
        urls = self._pending.setdefault(raw, [])
        if product_url and product_url not in urls:
            urls.append(product_url)

    def flush(self, criteria: Criteria) -> None:
        """Merge pending sightings into the queue file and write it once."""
        if not self._pending:
            return
        queue = pipeline.repo_path(criteria.fields.brand.review_queue)
        today = date.today().isoformat()

        entries: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        if queue.exists():
            with queue.open("r", newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    raw = row["raw_value"]
                    legacy_url = row.get("example_url", "")  # pre-M9 schema
                    urls = _split_urls(row.get("source_urls") or legacy_url)
                    entries[raw] = {"urls": urls, "first_seen": row.get("first_seen") or today}
                    order.append(raw)

        for raw, urls in self._pending.items():
            if raw not in entries:
                entries[raw] = {"urls": [], "first_seen": today}
                order.append(raw)
            for url in urls:
                if url not in entries[raw]["urls"]:
                    entries[raw]["urls"].append(url)

        queue.parent.mkdir(parents=True, exist_ok=True)
        with queue.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            for raw in order:
                entry = entries[raw]
                writer.writerow(
                    {
                        "raw_value": raw,
                        "count": len(entry["urls"]),
                        "source_urls": SOURCE_URL_SEPARATOR.join(entry["urls"]),
                        "first_seen": entry["first_seen"],
                    }
                )
        self._pending.clear()


ACTION_NONE = None
ACTION_PLACEHOLDER = "placeholder"
ACTION_OUT_OF_VOCABULARY = "not_in_vocabulary"
ACTION_QUEUE = "queue"


def resolve_brand(raw: str | None, criteria: Criteria, product_url: str) -> tuple[str, str, str | None]:
    """Pure brand resolution. Returns (brand, source, action). No logging, no file writes.

    product_url is accepted for symmetry with normalize_brand. This function never records
    anything, so it is not used here.

    source is canonical | alias | raw | missing. action says what the caller should
    record: ACTION_PLACEHOLDER or ACTION_OUT_OF_VOCABULARY (log), ACTION_QUEUE (review
    queue), or None.
    """
    missing = criteria.naming.missing_token
    text = (raw or "").strip()
    if not text:
        return (missing, "missing", ACTION_NONE)

    lowered = text.lower()
    slug = pipeline.slugify(lowered)
    if not slug:
        return (missing, "missing", ACTION_NONE)

    brand = criteria.fields.brand
    if slug in brand.canonical:
        return (slug, "canonical", ACTION_NONE)

    if lowered in {placeholder.lower() for placeholder in brand.placeholders}:
        return (missing, "missing", ACTION_PLACEHOLDER)

    for canonical, aliases in brand.aliases.items():
        if lowered in {alias.lower() for alias in aliases}:
            return (canonical, "alias", ACTION_NONE)

    if brand.open_vocabulary:
        return (slug, "raw", ACTION_QUEUE)

    return (missing, "missing", ACTION_OUT_OF_VOCABULARY)


def normalize_brand(
    raw: str | None,
    criteria: Criteria,
    product_url: str = "",
    review: ReviewCollector | None = None,
) -> tuple[str, str]:
    """(canonical brand, source). source is canonical | alias | raw | missing.

    Placeholder values such as "Other" are treated as missing and logged, not queued.
    Unknown brands are kept as slugs with source "raw" and recorded in the review
    queue. They are never promoted to canonical here. Pass a ReviewCollector to
    batch writes; without one, the queue is written immediately.
    """
    brand, source, action = resolve_brand(raw, criteria, product_url)
    text = (raw or "").strip()
    if action == ACTION_PLACEHOLDER:
        pipeline.append_log(criteria.output.unclassified_log, f"brand placeholder | {text}")
    elif action == ACTION_OUT_OF_VOCABULARY:
        pipeline.append_log(criteria.output.unclassified_log, f"brand not in vocabulary | {text}")
    elif action == ACTION_QUEUE:
        if review is not None:
            review.add(text, product_url)
        else:
            single = ReviewCollector()
            single.add(text, product_url)
            single.flush(criteria)
    return (brand, source)


def normalize_condition(raw: str | None, criteria: Criteria) -> str:
    """Enum value for a condition string, or fields.condition.default."""
    condition = criteria.fields.condition
    text = (raw or "").strip().lower()
    if not text:
        return condition.default

    for value in condition.enum:
        if text == value.lower():
            return value

    for value, aliases in condition.aliases.items():
        if value in condition.enum and text in {alias.lower() for alias in aliases}:
            return value

    return condition.default
