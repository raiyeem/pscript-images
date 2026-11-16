"""Tests for extract.excluded_url_pattern (seller avatar exclusion)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from extract import excluded_url_pattern  # noqa: E402

PATTERNS = ["user-profile", "/profile/", "avatar", "seller"]


def test_seller_avatar_url_is_excluded():
    url = "https://foremarket-prod-user-profile-pictures.s3.eu-central-1.amazonaws.com/abc.jpeg"
    assert excluded_url_pattern(url, PATTERNS) == "user-profile"


def test_product_image_url_is_not_excluded():
    url = "https://assets.foremarket.se/products/5879f714-e35a-4a71-9785-bd4af07ad6d9-1.webp"
    assert excluded_url_pattern(url, PATTERNS) is None


def test_pattern_match_is_case_insensitive():
    assert excluded_url_pattern("https://example.com/AVATAR/1.jpg", PATTERNS) == "avatar"
