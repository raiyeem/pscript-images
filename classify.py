"""Classification for saved images (M6): category, brand, and condition.

Criteria keys read:
  categories[*].name, categories[*].aliases, categories[*].keywords
  fields.brand.canonical, fields.brand.aliases, fields.brand.open_vocabulary,
  fields.brand.review_queue
  fields.condition.enum, fields.condition.aliases, fields.condition.default
  extraction.specs_labels.brand, extraction.specs_labels.condition
  output.unclassified_log, naming.missing_token

The category spec label "Category" is a literal for now. It should move to
extraction.specs_labels.category once that key is approved.
"""

from __future__ import annotations

import csv
from datetime import date
from typing import Any

import pipeline
from criteria import Criteria

CATEGORY_SPEC_LABEL = "Category"
REVIEW_COLUMNS = ["raw_value", "count", "example_url", "first_seen"]


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
    spec_value = (specs.get(CATEGORY_SPEC_LABEL) or "").strip()
    if spec_value:
        matched = _category_from_spec(spec_value, criteria)
        if matched is not None:
            return matched
    return _keyword_category(text, criteria)


def _record_review(criteria: Criteria, raw: str, example_url: str) -> None:
    """Count one sighting of an unknown brand in the review queue. Never promotes it."""
    queue = pipeline.repo_path(criteria.fields.brand.review_queue)
    rows: list[dict[str, str]] = []
    if queue.exists():
        with queue.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

    for row in rows:
        if row["raw_value"] == raw:
            row["count"] = str(int(row["count"]) + 1)
            break
    else:
        rows.append(
            {
                "raw_value": raw,
                "count": "1",
                "example_url": example_url,
                "first_seen": date.today().isoformat(),
            }
        )

    queue.parent.mkdir(parents=True, exist_ok=True)
    with queue.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def normalize_brand(raw: str | None, criteria: Criteria, example_url: str = "") -> tuple[str, str]:
    """(canonical brand, source). source is canonical | alias | raw | missing.

    Unknown brands are kept as slugs with source "raw" and added to the review
    queue. They are never promoted to canonical here.
    """
    missing = criteria.naming.missing_token
    text = (raw or "").strip()
    if not text:
        return (missing, "missing")

    lowered = text.lower()
    slug = pipeline.slugify(lowered)
    if not slug:
        return (missing, "missing")

    brand = criteria.fields.brand
    if slug in brand.canonical:
        return (slug, "canonical")

    for canonical, aliases in brand.aliases.items():
        if lowered in {alias.lower() for alias in aliases}:
            return (canonical, "alias")

    if brand.open_vocabulary:
        _record_review(criteria, text, example_url)
        return (slug, "raw")

    pipeline.append_log(criteria.output.unclassified_log, f"brand not in vocabulary | {text}")
    return (missing, "missing")


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
