"""Tests for --propose-criteria. Everything runs in tmp_path; criteria.yml is only read."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from criteria import load_criteria  # noqa: E402
from maintenance import propose_criteria  # noqa: E402


@pytest.fixture
def criteria():
    return load_criteria(REPO_ROOT / "criteria.yml")


def _write_queue(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["raw_value", "count", "source_urls", "first_seen"])
        writer.writeheader()
        writer.writerows(rows)


def test_propose_with_no_queue(criteria, tmp_path):
    out = tmp_path / "criteria.proposed.yml"

    result = propose_criteria(criteria, tmp_path / "absent.csv", out)

    assert result == (0, 0)
    assert not out.exists()


def test_propose_clusters_duplicates(criteria, tmp_path):
    queue = tmp_path / "brands_unknown.csv"
    _write_queue(
        queue,
        [
            {
                "raw_value": "Kirkland Signature",
                "count": "2",
                "source_urls": "https://a.test/1;https://a.test/2",
                "first_seen": "2026-11-16",
            },
            {
                "raw_value": "Kirkland Sig",
                "count": "1",
                "source_urls": "https://a.test/3",
                "first_seen": "2026-11-16",
            },
        ],
    )
    out = tmp_path / "criteria.proposed.yml"

    clusters, raw_values = propose_criteria(criteria, queue, out)

    assert (clusters, raw_values) == (1, 2)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Proposed criteria additions")
    data = yaml.safe_load(text.split("\n", 2)[2])
    assert len(data["proposed_brands"]) == 1
    entry = data["proposed_brands"][0]
    assert entry["canonical"] == "kirkland-signature"
    assert sum(source["count"] for source in entry["sources"]) == 3
    assert data["proposed_aliases"]["kirkland-signature"] == ["kirkland signature", "kirkland sig"]


def test_propose_never_writes_criteria_yml(criteria, tmp_path):
    criteria_file = REPO_ROOT / "criteria.yml"
    before = criteria_file.read_bytes()
    queue = tmp_path / "brands_unknown.csv"
    _write_queue(
        queue,
        [{"raw_value": "Kirkland Signature", "count": "1", "source_urls": "https://a.test/1", "first_seen": "2026-11-16"}],
    )

    propose_criteria(criteria, queue, tmp_path / "criteria.proposed.yml")

    assert criteria_file.read_bytes() == before


def test_propose_output_is_not_loaded(criteria):
    # The proposal filename must appear in exactly one module: the one that writes it.
    hits = []
    for path in REPO_ROOT.rglob("*.py"):
        parts = set(path.relative_to(REPO_ROOT).parts)
        if parts & {"venv", "tests", ".git", "node_modules"}:
            continue
        if "criteria.proposed" in path.read_text(encoding="utf-8"):
            hits.append(path.name)
    assert hits == ["maintenance.py"]
