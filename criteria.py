"""Pydantic v2 models that mirror criteria.yml.

Read-only: this module reads and validates the file. It never writes it.
Every model forbids unknown keys, so a typo in criteria.yml fails loudly
instead of being silently ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class CriteriaError(Exception):
    """Raised when criteria.yml cannot be read, parsed, or validated."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Output(_Strict):
    root: str
    manifest: str
    scrape_log: str
    unclassified_log: str
    coverage_report: str
    review_dir: str
    filtered_log: str
    conversion_errors_log: str
    failed_dir: str
    tmp_dir: str
    image_format: Literal["jpeg", "png", "original"]
    jpeg_quality: int = Field(ge=1, le=100)


class Naming(_Strict):
    folder_template: str
    file_template: str
    missing_token: str = Field(min_length=1)
    index_padding: int = Field(ge=1)

    @field_validator("file_template")
    @classmethod
    def _file_template_has_index(cls, value: str) -> str:
        if "{index" not in value:
            raise ValueError("file_template missing '{index'")
        return value


class BrandField(_Strict):
    open_vocabulary: bool
    review_queue: str
    placeholders: list[str]
    canonical: list[str]
    aliases: dict[str, list[str]]


class ConditionField(_Strict):
    open_vocabulary: bool
    default: str
    enum: list[str]
    aliases: dict[str, list[str]]


class Fields(_Strict):
    brand: BrandField
    condition: ConditionField


class Category(_Strict):
    name: str
    aliases: list[str]
    keywords: list[str]
    required_angles: list[str]


class Angles(_Strict):
    aliases: dict[str, list[str]]


class SpecsLabels(_Strict):
    brand: list[str]
    category: list[str]
    condition: list[str]


class Extraction(_Strict):
    prefer_jsonld: bool
    jsonld_types: list[str]
    brand_keys: list[str]
    condition_keys: list[str]
    condition_map: dict[str, str]
    specs_labels: SpecsLabels
    min_dimension: int = Field(ge=1)
    excluded_extensions: list[str]
    scroll_steps: int = Field(ge=1)
    scroll_wait_ms: int = Field(ge=0)
    wait_for_selector: str = Field(min_length=1)
    wait_timeout_ms: int = Field(ge=1)
    excluded_url_patterns: list[str]

    @field_validator("excluded_extensions")
    @classmethod
    def _extensions_are_lowercase_with_dot(cls, value: list[str]) -> list[str]:
        for extension in value:
            if not extension.startswith(".") or extension != extension.lower():
                raise ValueError(
                    f"extension {extension!r} must start with '.' and be lowercase"
                )
        return value


class Politeness(_Strict):
    delay_seconds: float = Field(ge=0)
    max_images_per_page: int = Field(ge=1)
    respect_robots: bool
    ua_name: str = Field(min_length=1)
    user_agent: str = Field(min_length=1)
    connect_timeout_s: float = Field(gt=0)
    read_timeout_s: float = Field(gt=0)


class Scope(_Strict):
    page_type: str
    one_item_per_page: bool


class Criteria(_Strict):
    version: int
    output: Output
    naming: Naming
    fields: Fields
    categories: list[Category]
    angles: Angles
    extraction: Extraction
    politeness: Politeness
    scope: Scope

    @model_validator(mode="after")
    def _cross_checks(self) -> Criteria:
        enum = self.fields.condition.enum
        if self.fields.condition.default not in enum:
            raise ValueError(
                f"fields.condition.default: {self.fields.condition.default!r} "
                "is not in fields.condition.enum"
            )
        for source, target in self.extraction.condition_map.items():
            if target not in enum:
                raise ValueError(
                    f"extraction.condition_map.{source}: {target!r} "
                    "is not in fields.condition.enum"
                )
        for index, category in enumerate(self.categories):
            for angle in category.required_angles:
                if angle not in self.angles.aliases:
                    raise ValueError(
                        f"categories[{index}].required_angles: {angle!r} "
                        "is not defined in angles.aliases"
                    )
        return self


def _format_loc(loc: tuple[Any, ...]) -> str:
    """Turn ('categories', 3, 'required_angles') into 'categories[3].required_angles'."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def _yaml_line(text: str, loc: tuple[Any, ...]) -> int | None:
    """Best-effort 1-based line in the YAML text where the key path starts."""
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None
    line: int | None = None
    for part in loc:
        if node is None:
            break
        if isinstance(node, yaml.MappingNode) and isinstance(part, str):
            match = next(((k, v) for k, v in node.value if k.value == part), None)
            if match is None:
                # Key is missing: point at the parent key, or the document start.
                return line if line is not None else node.start_mark.line + 1
            key_node, node = match
            line = key_node.start_mark.line + 1
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int):
            if part >= len(node.value):
                break
            node = node.value[part]
            line = node.start_mark.line + 1
        else:
            break
    return line


def _readable_error(path: Path, text: str, exc: ValidationError) -> str:
    errors = exc.errors()
    first = errors[0]
    loc = tuple(first["loc"])
    message = first["msg"].removeprefix("Value error, ")
    line = _yaml_line(text, loc)
    where = f"{path}:{line}" if line is not None else str(path)
    key = _format_loc(loc)
    detail = f"{key}: {message}" if key else message
    extra = f" (+{len(errors) - 1} more error(s))" if len(errors) > 1 else ""
    return f"{where}: {detail}{extra}"


def load_criteria(path: Path | str) -> Criteria:
    """Read and validate criteria.yml. Raises CriteriaError with the first bad key."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CriteriaError(f"{path}: cannot read file: {exc.strerror}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"{path}:{mark.line + 1}" if mark is not None else str(path)
        problem = getattr(exc, "problem", None) or str(exc)
        raise CriteriaError(f"{where}: YAML parse error: {problem}") from exc

    try:
        return Criteria.model_validate(data)
    except ValidationError as exc:
        raise CriteriaError(_readable_error(path, text, exc)) from exc
