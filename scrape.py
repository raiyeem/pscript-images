"""Entry point for the image scraper.

This milestone only loads and validates criteria.yml. Scraping, downloading
and classification are not implemented yet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from criteria import CriteriaError, load_criteria


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrape.py")
    parser.add_argument(
        "url",
        nargs="?",
        help="product page URL (scraping is not implemented yet)",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_criteria(args.criteria)
    except CriteriaError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.validate_only:
        return 0

    print("scraping is not implemented yet; use --validate-only", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
