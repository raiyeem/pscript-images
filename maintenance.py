"""Criteria proposals and manifest renormalization (M9).

propose_criteria writes criteria.proposed.yml. That file is output only; nothing
in the codebase loads it, and criteria.yml is never written.

renormalize_manifest re-resolves brand columns from brand_raw using the current
criteria. It optionally renames files to match. Filenames are otherwise frozen
at scrape time.

Criteria keys read:
  fields.brand.review_queue, fields.brand.canonical, fields.brand.aliases,
  fields.brand.placeholders, fields.brand.open_vocabulary
  naming.missing_token, output.unclassified_log
"""

from __future__ import annotations

import csv
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

import pipeline
from classify import resolve_brand
from criteria import Criteria

REPO_ROOT = Path(__file__).resolve().parent
PROPOSAL_FILENAME = "criteria.proposed.yml"
QUEUE_COLUMNS = ["raw_value", "count", "source_urls", "first_seen"]
SOURCE_URL_SEPARATOR = ";"
_NON_ALNUM = re.compile(r"[^a-z0-9]")
_INDEX_SUFFIX = re.compile(r"_(\d+)$")


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def _comparison_key(text: str) -> str:
    """Lowercase, with hyphens, whitespace, and non-alphanumerics removed."""
    return _NON_ALNUM.sub("", text.lower())


def _same_cluster(a: str, b: str) -> bool:
    key_a, key_b = _comparison_key(a), _comparison_key(b)
    if not key_a or not key_b:
        return False
    if _levenshtein(key_a, key_b) <= 2:
        return True
    shorter, longer = sorted((key_a, key_b), key=len)
    return len(shorter) >= 4 and shorter in longer


def _read_queue(queue: Path) -> list[dict[str, Any]]:
    if not queue.exists():
        return []
    entries: list[dict[str, Any]] = []
    with queue.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            urls = [u.strip() for u in (row.get("source_urls") or "").split(SOURCE_URL_SEPARATOR) if u.strip()]
            raw = (row.get("raw_value") or "").strip()
            if not raw:
                continue
            count = int(row["count"]) if (row.get("count") or "").isdigit() else len(urls)
            entries.append({"raw": raw, "count": count, "urls": urls})
    return entries


def _cluster(entries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Single-linkage clusters via union-find over the pairwise rule."""
    parent = list(range(len(entries)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            if _same_cluster(entries[i]["raw"], entries[j]["raw"]):
                parent[find(i)] = find(j)

    groups: dict[int, list[dict[str, Any]]] = {}
    for i, entry in enumerate(entries):
        groups.setdefault(find(i), []).append(entry)
    return list(groups.values())


def propose_criteria(
    criteria: Criteria,
    queue: Path,
    out: Path,
    today: date | None = None,
) -> tuple[int, int]:
    """Write criteria proposals for the unknown brands in the review queue.

    Returns (clusters, raw_values). If the queue is absent or empty, nothing is
    written and (0, 0) is returned.
    """
    entries = _read_queue(queue)
    if not entries:
        return (0, 0)

    proposed_brands: list[dict[str, Any]] = []
    proposed_aliases: dict[str, list[str]] = {}
    for members in _cluster(entries):
        members.sort(key=lambda e: (-e["count"], -len(e["raw"])))
        canonical = pipeline.slugify(members[0]["raw"])
        raw_values = [m["raw"] for m in members]
        reason = (
            f"cluster of {len(members)} raw values" if len(members) > 1 else "single raw value"
        )
        proposed_brands.append(
            {
                "canonical": canonical,
                "reason": reason,
                "sources": [
                    {
                        "raw": m["raw"],
                        "count": m["count"],
                        "example": m["urls"][0] if m["urls"] else "",
                    }
                    for m in members
                ],
            }
        )
        aliases = []
        for raw in raw_values:
            lowered = raw.lower()
            if lowered not in aliases:
                aliases.append(lowered)
        proposed_aliases[canonical] = aliases

    stamp = (today or date.today()).isoformat()
    header = (
        f"# Proposed criteria additions — generated {stamp}, DO NOT auto-load.\n"
        "# Review each entry, then manually apply what you accept to criteria.yml.\n"
    )
    body = yaml.safe_dump(
        {"proposed_brands": proposed_brands, "proposed_aliases": proposed_aliases},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    out.write_text(header + body, encoding="utf-8")
    return (len(proposed_brands), len(entries))


def _index_from_stem(stem: str) -> int | None:
    match = _INDEX_SUFFIX.search(stem)
    return int(match.group(1)) if match else None


def renormalize_manifest(
    criteria: Criteria,
    manifest: Path,
    rename_files: bool = False,
    root: Path = REPO_ROOT,
) -> tuple[int, int, int]:
    """Re-resolve brand and brand_source from brand_raw. Returns (changed, renamed, errors).

    Writes the manifest and manifest.csv.renormalize.log next to it. Condition is
    not re-resolved: the manifest stores normalized values only, not raw condition
    text. sha256, source_url, scraped_at, category, and angle are never changed.
    """
    manifest = Path(manifest)
    with manifest.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != pipeline.MANIFEST_COLUMNS:
            raise ValueError(f"{manifest}: unexpected columns {reader.fieldnames}")
        rows = list(reader)

    log_lines: list[str] = []
    changed = renamed = errors = 0
    for row in rows:
        old_brand, old_source = row["brand"], row["brand_source"]
        new_brand, new_source, _ = resolve_brand(row["brand_raw"], criteria)
        if (new_brand, new_source) == (old_brand, old_source):
            continue

        changed += 1
        row["brand"], row["brand_source"] = new_brand, new_source
        line = f"{row['file']} | {old_brand}/{old_source} → {new_brand}/{new_source}"

        if rename_files:
            old_path = root / row["file"]
            index = _index_from_stem(old_path.stem)
            if index is None or not old_path.exists():
                errors += 1
                log_lines.append(line + " | rename skipped: source missing or unindexed")
                continue
            new_name = pipeline.build_filename(
                criteria,
                category=row["category"],
                brand=new_brand,
                condition=row["condition"],
                angle=row["angle"],
                index=index,
                ext=old_path.suffix.lstrip("."),
            )
            new_path = old_path.with_name(new_name)
            if new_path != old_path and new_path.exists():
                errors += 1
                log_lines.append(line + " | rename skipped: target exists")
                continue
            if new_path != old_path:
                os.replace(old_path, new_path)
                row["file"] = new_path.relative_to(root).as_posix()
                renamed += 1
                line += f" | renamed → {row['file']}"
        log_lines.append(line)

    temp = manifest.with_name(manifest.name + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=pipeline.MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp, manifest)

    log = manifest.with_name(manifest.name + ".renormalize.log")
    log.write_text("".join(f"{line}\n" for line in log_lines), encoding="utf-8")
    return (changed, renamed, errors)
