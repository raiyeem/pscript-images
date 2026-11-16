"""Tests for --renormalize. Everything runs in tmp_path; the real manifest is never touched."""

from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from criteria import load_criteria  # noqa: E402
from maintenance import renormalize_manifest  # noqa: E402
from pipeline import MANIFEST_COLUMNS  # noqa: E402

IMAGE_BYTES = b"fake-jpeg-bytes-for-hashing"
IMAGE_SHA = hashlib.sha256(IMAGE_BYTES).hexdigest()
RELATIVE = "images/Irons/unknown_unknown_unknown_001.jpg"


def _criteria_with_kirkland():
    base = load_criteria(REPO_ROOT / "criteria.yml")
    brand = base.fields.brand.model_copy(
        update={
            "canonical": [*base.fields.brand.canonical, "kirkland"],
            "aliases": {**base.fields.brand.aliases, "kirkland": ["kirkland signature"]},
        }
    )
    fields = base.fields.model_copy(update={"brand": brand})
    return base.model_copy(update={"fields": fields})


def _setup(tmp_path: Path) -> Path:
    """Create one image and a manifest that still says brand=unknown. Returns the manifest path."""
    image = tmp_path / RELATIVE
    image.parent.mkdir(parents=True)
    image.write_bytes(IMAGE_BYTES)
    manifest = tmp_path / "images" / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "file": RELATIVE,
                "category": "Irons",
                "brand": "unknown",
                "brand_raw": "Kirkland Signature",
                "brand_source": "missing",
                "condition": "unknown",
                "angle": "unknown",
                "source_url": "https://a.test/1",
                "scraped_at": "2026-11-16T10:00:00+00:00",
                "sha256": IMAGE_SHA,
                "criteria_version": "abc123def456",
                "status": "ok",
                "error": "",
            }
        )
    return manifest


def _rows(manifest: Path) -> list[dict[str, str]]:
    with manifest.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_renormalize_updates_brand_after_criteria_change(tmp_path):
    manifest = _setup(tmp_path)

    changed, renamed, errors = renormalize_manifest(_criteria_with_kirkland(), manifest, root=tmp_path)

    assert (changed, renamed, errors) == (1, 0, 0)
    row = _rows(manifest)[0]
    assert row["brand"] == "kirkland"
    assert row["brand_source"] == "alias"
    log = (manifest.parent / "manifest.csv.renormalize.log").read_text(encoding="utf-8")
    assert "unknown/missing → kirkland/alias" in log


def test_renormalize_no_rename_by_default(tmp_path):
    manifest = _setup(tmp_path)

    renormalize_manifest(_criteria_with_kirkland(), manifest, root=tmp_path)

    assert (tmp_path / RELATIVE).exists()
    assert not (tmp_path / "images" / "Irons" / "kirkland_unknown_unknown_001.jpg").exists()
    assert _rows(manifest)[0]["file"] == RELATIVE


def test_renormalize_with_rename(tmp_path):
    manifest = _setup(tmp_path)

    changed, renamed, errors = renormalize_manifest(
        _criteria_with_kirkland(), manifest, rename_files=True, root=tmp_path
    )

    new_relative = "images/Irons/kirkland_unknown_unknown_001.jpg"
    assert (changed, renamed, errors) == (1, 1, 0)
    assert _rows(manifest)[0]["file"] == new_relative
    assert (tmp_path / new_relative).exists()
    assert not (tmp_path / RELATIVE).exists()

    # No orphans: every file on disk is listed in the manifest, and vice versa.
    on_disk = {
        path.relative_to(tmp_path).as_posix()
        for path in (tmp_path / "images").rglob("*.jpg")
    }
    in_manifest = {row["file"] for row in _rows(manifest)}
    assert on_disk == in_manifest


def test_renormalize_preserves_sha256(tmp_path):
    manifest = _setup(tmp_path)

    renormalize_manifest(
        _criteria_with_kirkland(), manifest, rename_files=True, root=tmp_path
    )

    row = _rows(manifest)[0]
    assert row["sha256"] == IMAGE_SHA
    assert hashlib.sha256((tmp_path / row["file"]).read_bytes()).hexdigest() == IMAGE_SHA
