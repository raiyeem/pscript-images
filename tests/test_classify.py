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

PRODUCT_URL = "https://assets.foremarket.se/products/example-1.webp"


@pytest.fixture
def criteria(tmp_path):
    base = load_criteria(REPO_ROOT / "criteria.yml")
    brand = base.fields.brand.model_copy(
        update={"review_queue": str(tmp_path / "brands_unknown.csv")}
    )
    fields = base.fields.model_copy(update={"brand": brand})
    return base.model_copy(update={"fields": fields})


# --- category -------------------------------------------------------------


def test_classify_driver_from_spec(criteria):
    assert classify_module.classify("", {"Category": "Driver"}, criteria) == "Driver"


def test_classify_irons_from_alias(criteria):
    assert classify_module.classify("", {"Category": "Iron"}, criteria) == "Irons"


def test_classify_putter_from_alt_text(criteria):
    assert classify_module.classify(f"{PRODUCT_URL} Scotty Cameron putter", {}, criteria) == "Putter"


def test_classify_returns_none_without_match(criteria):
    assert classify_module.classify(f"{PRODUCT_URL} generic item", {}, criteria) is None


# --- brand ----------------------------------------------------------------


def test_normalize_brand_canonical(criteria):
    assert classify_module.normalize_brand("Wilson", criteria) == ("wilson", "canonical")


def test_normalize_brand_alias(criteria):
    assert classify_module.normalize_brand("Wilsson", criteria) == ("wilson", "alias")


def test_normalize_brand_raw_goes_to_review_queue(criteria):
    brand, source = classify_module.normalize_brand(
        "Kirkland Signature", criteria, example_url=PRODUCT_URL
    )

    assert (brand, source) == ("kirkland-signature", "raw")
    queue = Path(criteria.fields.brand.review_queue).read_text(encoding="utf-8")
    assert "Kirkland Signature" in queue  # raw_value keeps the value as given
    assert PRODUCT_URL in queue


def test_review_queue_increments_existing_entry(criteria):
    classify_module.normalize_brand("Kirkland Signature", criteria, example_url=PRODUCT_URL)
    classify_module.normalize_brand("Kirkland Signature", criteria, example_url=PRODUCT_URL)

    lines = Path(criteria.fields.brand.review_queue).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # header + one row
    assert lines[1].split(",")[1] == "2"


def test_normalize_brand_empty(criteria):
    assert classify_module.normalize_brand("", criteria) == ("unknown", "missing")


# --- condition ------------------------------------------------------------


def test_normalize_condition_alias_brand_new(criteria):
    assert classify_module.normalize_condition("brand new", criteria) == "new"


def test_normalize_condition_alias_used_good(criteria):
    assert classify_module.normalize_condition("Used - Good", criteria) == "good"


def test_normalize_condition_default(criteria):
    assert classify_module.normalize_condition("cosmic ray", criteria) == "unknown"
