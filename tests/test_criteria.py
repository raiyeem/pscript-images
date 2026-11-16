"""Tests for the criteria.yml loader and the --validate-only CLI path.

The valid cases read the real criteria.yml at the repo root. The invalid cases
are built in tmp_path by editing a copy, so criteria.yml itself is never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from criteria import Criteria, CriteriaError, load_criteria  # noqa: E402
import scrape  # noqa: E402

REAL_CRITERIA = REPO_ROOT / "criteria.yml"


def _real_text() -> str:
    return REAL_CRITERIA.read_text(encoding="utf-8")


def _write_variant(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "criteria.yml"
    path.write_text(text, encoding="utf-8")
    return path


def _line_of(text: str, needle: str) -> int:
    """1-based line number of the first line containing needle."""
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"{needle!r} not found in criteria text")


# --- valid file -------------------------------------------------------------


def test_real_criteria_loads_and_exposes_parsed_config():
    criteria = load_criteria(REAL_CRITERIA)

    assert isinstance(criteria, Criteria)
    assert criteria.naming.missing_token == "unknown"
    assert criteria.naming.index_padding == 3
    assert criteria.fields.condition.default == "unknown"
    assert criteria.extraction.specs_labels.brand == ["Subcategory"]
    assert criteria.extraction.specs_labels.condition == []
    assert criteria.extraction.condition_map["UsedCondition"] == "good"
    assert criteria.categories[0].name == "Driver"
    assert criteria.politeness.delay_seconds == 1.5


def test_loaded_config_is_frozen(tmp_path):
    criteria = load_criteria(REAL_CRITERIA)
    with pytest.raises(Exception):
        criteria.naming.missing_token = "changed"  # type: ignore[misc]


# --- invalid file: field-level errors name the key and the line -------------


def test_file_template_without_index_names_key_and_line(tmp_path):
    text = _real_text().replace("{index:03d}", "{idx:03d}", 1)
    path = _write_variant(tmp_path, text)

    with pytest.raises(CriteriaError) as info:
        load_criteria(path)

    message = str(info.value)
    expected_line = _line_of(text, "file_template:")
    assert f"{path}:{expected_line}: naming.file_template:" in message
    assert "file_template missing '{index'" in message
    assert "Value error" not in message


def test_missing_required_angles_names_category_index(tmp_path):
    # Removes the first occurrence, which belongs to categories[3] (Irons).
    text = _real_text().replace(
        "required_angles: [face, sole, shaft-grip]", "", 1
    )
    path = _write_variant(tmp_path, text)

    with pytest.raises(CriteriaError) as info:
        load_criteria(path)

    message = str(info.value)
    assert "categories[3].required_angles: Field required" in message


def test_unknown_key_is_rejected_by_name(tmp_path):
    text = _real_text().replace(
        "one_item_per_page: true", "one_item_per_pages: true", 1
    )
    path = _write_variant(tmp_path, text)

    with pytest.raises(CriteriaError) as info:
        load_criteria(path)

    # The missing key is reported first; the typo is the second error.
    message = str(info.value)
    assert "scope.one_item_per_page: Field required" in message
    assert "(+1 more error(s))" in message


# --- invalid file: cross-field checks ---------------------------------------


def test_condition_default_must_be_in_enum(tmp_path):
    text = _real_text().replace("default: unknown", "default: nope", 1)
    path = _write_variant(tmp_path, text)

    with pytest.raises(CriteriaError) as info:
        load_criteria(path)

    assert "fields.condition.default: 'nope' is not in fields.condition.enum" in str(
        info.value
    )


def test_required_angle_must_be_defined_in_angles(tmp_path):
    # Replaces the first occurrence, which belongs to categories[0] (Driver).
    text = _real_text().replace(
        "required_angles: [face, crown, sole, shaft-grip]",
        "required_angles: [face, bogus]",
        1,
    )
    path = _write_variant(tmp_path, text)

    with pytest.raises(CriteriaError) as info:
        load_criteria(path)

    assert (
        "categories[0].required_angles: 'bogus' is not defined in angles.aliases"
        in str(info.value)
    )


# --- CLI: --validate-only ----------------------------------------------------


def test_cli_validate_only_is_silent_and_exits_zero(capsys):
    code = scrape.main(["--criteria", str(REAL_CRITERIA), "--validate-only"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_cli_validate_only_exits_nonzero_with_readable_error(tmp_path, capsys):
    text = _real_text().replace("{index:03d}", "{idx:03d}", 1)
    path = _write_variant(tmp_path, text)

    code = scrape.main(["--criteria", str(path), "--validate-only"])

    captured = capsys.readouterr()
    assert code == 1
    assert "naming.file_template" in captured.err
    assert captured.out == ""
