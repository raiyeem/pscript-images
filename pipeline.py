"""Folders, filenames, keyword classification stub, and the manifest (M5).

Criteria keys read:
  output.root, output.manifest, output.scrape_log, output.unclassified_log,
  output.conversion_errors_log
  naming.folder_template, naming.file_template, naming.missing_token
  categories[*].name, categories[*].keywords

Classification here is a keyword fallback stub. The real classifier replaces it in M6.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from criteria import Criteria

REPO_ROOT = Path(__file__).resolve().parent

MANIFEST_COLUMNS = [
    "file",
    "category",
    "brand",
    "brand_raw",
    "brand_source",
    "condition",
    "angle",
    "source_url",
    "scraped_at",
    "sha256",
    "criteria_version",
    "status",
    "error",
]
REQUIRED_MANIFEST_FIELDS = ("file", "sha256", "criteria_version", "status", "scraped_at")

# Characters Windows forbids in names, plus whitespace (filename fields only).
_FILENAME_RESERVED = re.compile(r'[\s\\/:*?"<>|]')
_FOLDER_RESERVED = re.compile(r'[\\/:*?"<>|]')
_REPEATED_DASH = re.compile(r"-{2,}")


def repo_path(value: str | Path) -> Path:
    """Resolve a criteria path against the repo root. Absolute paths are kept."""
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def relative_posix(path: str | Path) -> str:
    """Path relative to the repo root, with forward slashes."""
    return Path(path).resolve().relative_to(REPO_ROOT).as_posix()


def criteria_version(path: str | Path) -> str:
    """First 12 hex chars of the SHA-256 of the criteria file (see CLAUDE.md)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_field(value: Any) -> str:
    """Filename field: lowercase, spaces and reserved characters become '-', runs collapse."""
    text = _FILENAME_RESERVED.sub("-", str(value).strip().lower())
    return _REPEATED_DASH.sub("-", text)


def _clean_folder(value: Any) -> str:
    """Folder name: keeps case and spaces; only reserved characters become '-'."""
    text = _FOLDER_RESERVED.sub("-", str(value).strip())
    return _REPEATED_DASH.sub("-", text)


class _Fields(dict):
    """format_map helper: any placeholder without a value becomes naming.missing_token."""

    def __init__(self, missing: str, **values: Any) -> None:
        super().__init__(values)
        self._missing = missing

    def __missing__(self, key: str) -> str:
        return self._missing


def category_folder(criteria: Criteria, category_name: str | None) -> Path:
    """Folder for a category. None (no keyword match) uses naming.missing_token."""
    missing = criteria.naming.missing_token
    name = _clean_folder(category_name) if category_name else missing
    relative = criteria.naming.folder_template.format_map(_Fields(missing, category=name))
    return repo_path(criteria.output.root) / relative


def ensure_folders(criteria: Criteria) -> None:
    """Create one folder per configured category."""
    for category in criteria.categories:
        category_folder(criteria, category.name).mkdir(parents=True, exist_ok=True)


def build_filename(
    criteria: Criteria,
    category: str | None,
    brand: str | None,
    condition: str | None,
    angle: str | None,
    index: int,
    ext: str,
) -> str:
    """Fill naming.file_template. index is 1-based. ext has no leading dot. Returns the name only."""
    if index < 1:
        raise ValueError(f"index must be 1-based, got {index}")
    missing = criteria.naming.missing_token

    def value(raw: str | None) -> str:
        cleaned = _clean_field(raw) if raw not in (None, "") else ""
        return cleaned or missing

    fields = _Fields(
        missing,
        category=value(category),
        brand=value(brand),
        condition=value(condition),
        angle=value(angle),
        index=index,
        ext=value(ext),
    )
    return criteria.naming.file_template.format_map(fields)


_SLUG_SPLIT = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Lowercase ASCII slug: runs of non-alphanumerics become '-', ends trimmed."""
    return _SLUG_SPLIT.sub("-", value.strip().lower()).strip("-")


def category_from_specs(criteria: Criteria, specs: dict[str, str]) -> str | None:
    """Match specs["Category"] case-insensitively against category names and aliases. First match wins."""
    value = specs.get("Category", "").strip().lower()
    if not value:
        return None
    for category in criteria.categories:
        candidates = [category.name, *category.aliases]
        if any(candidate.lower() == value for candidate in candidates):
            return category.name
    return None


def keyword_category(criteria: Criteria, url: str, alt: str | None) -> str | None:
    """Fallback: first category whose keyword appears in the URL or alt text."""
    text = f"{url} {alt or ''}".lower()
    for category in criteria.categories:
        if any(keyword.lower() in text for keyword in category.keywords):
            return category.name
    return None


def classify(criteria: Criteria, url: str, alt: str | None, specs: dict[str, str]) -> str | None:
    """Spec Category first; keyword fallback only when the spec is absent or unrecognised."""
    return category_from_specs(criteria, specs) or keyword_category(criteria, url, alt)


def existing_counts(criteria: Criteria) -> dict[str, int]:
    """Rows already in the manifest, per category value. Used to continue numbering."""
    manifest = repo_path(criteria.output.manifest)
    if not manifest.exists():
        return {}
    counts: dict[str, int] = {}
    with manifest.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            category = row.get("category", "")
            counts[category] = counts.get(category, 0) + 1
    return counts


def append_manifest(criteria: Criteria, row: dict[str, Any]) -> None:
    """Append one row. Writes the header first if the manifest is new or empty.

    Only saved, converted files get rows. Failed files go to output.failed_dir instead.
    """
    missing = [key for key in REQUIRED_MANIFEST_FIELDS if not row.get(key)]
    if missing:
        raise ValueError(f"manifest row missing required field(s): {', '.join(missing)}")
    if row["status"] != "ok":
        raise ValueError(f"manifest rows are only written for status 'ok', got {row['status']!r}")

    manifest = repo_path(criteria.output.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    write_header = not manifest.exists() or manifest.stat().st_size == 0
    with manifest.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=MANIFEST_COLUMNS, restval="", extrasaction="raise"
        )
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_log(path: str | Path, line: str) -> None:
    log = repo_path(path)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


def move_to_failed(criteria: Criteria, path: str | Path) -> Path:
    """Move a file whose conversion failed into output.failed_dir. Returns the new path."""
    source = Path(path)
    target_dir = repo_path(criteria.output.failed_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    os.replace(source, target)
    return target
