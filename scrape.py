"""Entry point for the image scraper.

Implemented so far:
  --validate-only   load and validate criteria.yml
  --dry-run         open the product page, list image candidates, download nothing
  --limit N         keep only the first N candidates (dry-run output)

Not implemented yet: downloading, classification, manifest, coverage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from criteria import Criteria, CriteriaError, load_criteria
from extract import Filtered


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrape.py")
    parser.add_argument(
        "url",
        nargs="?",
        help="product detail page URL (navigated directly; links are never followed)",
    )
    parser.add_argument(
        "--criteria",
        type=Path,
        default=Path("criteria.yml"),
        help="path to the criteria file (default: criteria.yml)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="load and validate the criteria file; print nothing and exit 0 on success",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Loads the page and extracts candidates, but skips downloads. "
            "Not offline — network requests still happen."
        ),
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="keep only the first N candidates",
    )
    return parser


def _filtered_line(item: Filtered) -> str:
    """One log line: reason | url | alt."""
    return f"{item.reason} | {item.src or '-'} | {item.alt or '-'}"


def _write_filtered_log(path: Path, filtered: list[Filtered]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_filtered_line(item) for item in filtered]
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _dry_run(url: str, criteria: Criteria, limit: int | None) -> int:
    from playwright.sync_api import sync_playwright

    from extract import extract_images

    filtered: list[Filtered] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="load")
            candidates = extract_images(page, criteria, filtered=filtered)
        finally:
            browser.close()

    _write_filtered_log(Path(criteria.output.filtered_log), filtered)

    if limit is not None:
        candidates = candidates[:limit]

    for index, candidate in enumerate(candidates, start=1):
        keys = ", ".join(candidate.specs) if candidate.specs else "-"
        print(f"[{index}] {candidate.url} | {candidate.alt or '-'} | {candidate.heading or '-'} | {keys}")

    for item in filtered:
        print(_filtered_line(item), file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        criteria = load_criteria(args.criteria)
    except CriteriaError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.validate_only:
        return 0

    if not args.url:
        print("a product URL is required unless --validate-only is given", file=sys.stderr)
        return 2

    if args.dry_run:
        return _dry_run(args.url, criteria, args.limit)

    print("downloading is not implemented yet; use --dry-run", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
