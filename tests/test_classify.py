"""Tests for classify.py. The review queue is redirected to tmp_path.

Criteria models are frozen, so the fixture builds a copy with the review queue
path changed (monkeypatch cannot set attributes on frozen models).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import classify as classify_module  # noqa: E402
from criteria import load_criteria  # noqa: E402

PRODUCT_URL = "https://foremarket.se/en/product/example-product-1"


@pytest.fixture
def criteria(tmp_path):
    base = load_criteria(REPO_ROOT / "criteria.yml")
    brand = base.fields.brand.model_copy(
        update={"review_queue": str(tmp_path / "brands_unknown.csv")}
    )
    fields = base.fields.model_copy(update={"brand": brand})
    output = base.output.model_copy(update={"unclassified_log": str(tmp_path / "unclassified.log")})
    return base.model_copy(update={"fields": fields, "output": output})


# --- category -------------------------------------------------------------


def test_classify_driver_from_spec(criteria):
    assert classify_module.classify("", {"Category": "Driver"}, criteria) == "Driver"


def test_classify_irons_from_alias(criteria):
    assert classify_module.classify("", {"Category": "Iron"}, criteria) == "Irons"


def test_classify_apparel_from_men_apparel_alias(criteria):
    assert classify_module.classify("", {"Category": "Men Apparel"}, criteria) == "Apparel"


def test_classify_putter_from_alt_text(criteria):
    assert classify_module.classify(f"{PRODUCT_URL} Scotty Cameron putter", {}, criteria) == "Putter"


def test_classify_returns_none_without_match(criteria):
    assert classify_module.classify(f"{PRODUCT_URL} generic item", {}, criteria) is None


# --- brand ----------------------------------------------------------------


def test_normalize_brand_canonical(criteria):
    assert classify_module.normalize_brand("Wilson", criteria) == ("wilson", "canonical")


def test_normalize_brand_alias(criteria):
    assert classify_module.normalize_brand("Wilsson", criteria) == ("wilson", "alias")


def test_normalize_brand_queues_raw_values(criteria):
    brand, source = classify_module.normalize_brand(
        "Kirkland Signature", criteria, product_url=PRODUCT_URL
    )

    assert (brand, source) == ("kirkland-signature", "raw")
    queue = Path(criteria.fields.brand.review_queue).read_text(encoding="utf-8")
    assert "Kirkland Signature" in queue  # raw_value keeps the value as given
    assert PRODUCT_URL in queue  # the product page is what gets queued
    assert "webp" not in queue  # never an image URL


OTHER_URL = "https://foremarket.se/en/product/example-product-2"


def test_review_queue_counts_products_not_images(criteria):
    # One product page with three image candidates, all with Subcategory "Kirkland Signature".
    # The save flow calls normalize_brand once per image, always with the product page URL.
    image_urls = [f"https://assets.foremarket.se/products/kirk-{n}.webp" for n in (1, 2, 3)]
    for _ in image_urls:
        classify_module.normalize_brand("Kirkland Signature", criteria, product_url=PRODUCT_URL)

    lines = Path(criteria.fields.brand.review_queue).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # header + one row
    assert lines[1].split(",")[1] == "1"  # count is products, not images
    assert PRODUCT_URL in lines[1]
    assert not any(image in lines[1] for image in image_urls)


def test_review_queue_counts_distinct_urls(criteria):
    classify_module.normalize_brand("Kirkland Signature", criteria, product_url=PRODUCT_URL)
    classify_module.normalize_brand("Kirkland Signature", criteria, product_url=OTHER_URL)

    lines = Path(criteria.fields.brand.review_queue).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "raw_value,count,source_urls,first_seen"
    assert len(lines) == 2  # header + one row
    assert lines[1].split(",")[1] == "2"
    assert PRODUCT_URL in lines[1] and OTHER_URL in lines[1]


def test_review_queue_same_url_counts_once(criteria):
    classify_module.normalize_brand("Kirkland Signature", criteria, product_url=PRODUCT_URL)
    classify_module.normalize_brand("Kirkland Signature", criteria, product_url=PRODUCT_URL)

    lines = Path(criteria.fields.brand.review_queue).read_text(encoding="utf-8").splitlines()
    assert lines[1].split(",")[1] == "1"


def test_review_collector_merges_across_runs(criteria):
    first = classify_module.ReviewCollector()
    first.add("Kirkland Signature", PRODUCT_URL)
    first.flush(criteria)

    second = classify_module.ReviewCollector()
    second.add("Kirkland Signature", OTHER_URL)
    second.add("Kirkland Signature", PRODUCT_URL)
    second.flush(criteria)

    lines = Path(criteria.fields.brand.review_queue).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[1].split(",")[1] == "2"


def test_normalize_brand_placeholder_other_is_missing_and_not_queued(criteria):
    assert classify_module.normalize_brand("Other", criteria, product_url=PRODUCT_URL) == (
        "unknown",
        "missing",
    )
    assert not Path(criteria.fields.brand.review_queue).exists()
    assert "brand placeholder | Other" in Path(criteria.output.unclassified_log).read_text(encoding="utf-8")


def test_normalize_brand_empty(criteria):
    assert classify_module.normalize_brand("", criteria) == ("unknown", "missing")


# --- condition ------------------------------------------------------------


def test_normalize_condition_alias_brand_new(criteria):
    assert classify_module.normalize_condition("brand new", criteria) == "new"


def test_normalize_condition_alias_used_good(criteria):
    assert classify_module.normalize_condition("Used - Good", criteria) == "good"


def test_normalize_condition_default(criteria):
    assert classify_module.normalize_condition("cosmic ray", criteria) == "unknown"
