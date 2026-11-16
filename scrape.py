"""Entry point for the image scraper.

Implemented so far:
  --validate-only   load and validate criteria.yml
  --dry-run         open the product page, list image candidates, download nothing
  --save            open the product page, download candidates, write files and manifest rows
  --limit N         keep only the first N candidates
  --download-one    manual test of the downloader (never called by the pipeline)

Classification is a keyword stub in --save. The real classifier comes in M6.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from classify import classify, first_spec, normalize_brand, normalize_condition
from criteria import Criteria, CriteriaError, load_criteria
from extract import Filtered

_DOWNLOAD_TEST_STEM = Path(__file__).resolve().parent / "_download_test"
_KNOWN_MAGIC = {
    "ffd8ff": "JPEG",
    "52494646": "RIFF (WebP container)",
    "89504e47": "PNG",
}


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
        "--save",
        action="store_true",
        help="download candidates into the category folders and append manifest rows",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="keep only the first N candidates",
    )
    parser.add_argument(
        "--download-one",
        metavar="URL",
        default=None,
        help=(
            "manual test: download one image to _download_test.<ext> at the repo root "
            "and print the DownloadResult. Never called by the pipeline."
        ),
    )
    return parser


def _download_one(url: str, criteria: Criteria) -> int:
    from download import download_image

    result = download_image(url, _DOWNLOAD_TEST_STEM, criteria=criteria)
    print(result)
    if result.path is None:
        return 1
    data = Path(result.path).read_bytes()
    magic = data[:4].hex()
    label = next((name for sig, name in _KNOWN_MAGIC.items() if magic.startswith(sig)), "unrecognised")
    print(f"file: {result.path}")
    print(f"size: {len(data)} bytes")
    print(f"magic: {magic} ({label})")
    return 0 if result.status == "ok" else 1


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


def _save(url: str, criteria: Criteria, criteria_file: Path, limit: int | None) -> int:
    from playwright.sync_api import sync_playwright

    import pipeline
    from download import download_image
    from extract import extract_images

    missing = criteria.naming.missing_token
    pipeline.ensure_folders(criteria)
    version = pipeline.criteria_version(criteria_file)
    counts = pipeline.existing_counts(criteria)
    tmp_root = pipeline.repo_path(criteria.output.tmp_dir)
    filtered: list[Filtered] = []
    downloaded = failed = conversion_errors = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="load")
            candidates = extract_images(page, criteria, filtered=filtered)
            if limit is not None:
                candidates = candidates[:limit]

            for candidate in candidates:
                category = classify(f"{candidate.url} {candidate.alt or ''}", candidate.specs, criteria)
                folder_key = category or missing
                if category is None:
                    pipeline.append_log(
                        criteria.output.unclassified_log,
                        f"no category match | {candidate.url} | {candidate.alt or '-'}",
                    )

                brand_raw = first_spec(candidate.specs, criteria.extraction.specs_labels.brand)
                brand, brand_source = normalize_brand(brand_raw, criteria, example_url=candidate.url)
                condition = normalize_condition(
                    first_spec(candidate.specs, criteria.extraction.specs_labels.condition), criteria
                )
                angle = missing  # M8 not started

                result = download_image(
                    candidate.url, tmp_root / uuid.uuid4().hex, page=page, criteria=criteria
                )

                if result.status == "ok":
                    folder = pipeline.category_folder(criteria, category)
                    folder.mkdir(parents=True, exist_ok=True)
                    ext = Path(result.path).suffix.lstrip(".")

                    index = counts.get(folder_key, 0) + 1
                    while True:
                        name = pipeline.build_filename(
                            criteria,
                            category=folder_key,
                            brand=brand,
                            condition=condition,
                            angle=angle,
                            index=index,
                            ext=ext,
                        )
                        final = folder / name
                        if not final.exists():
                            break
                        index += 1
                    os.replace(result.path, final)
                    counts[folder_key] = index

                    pipeline.append_manifest(
                        criteria,
                        {
                            "file": pipeline.relative_posix(final),
                            "category": folder_key,
                            "brand": brand,
                            "brand_raw": brand_raw,
                            "brand_source": brand_source,
                            "condition": condition,
                            "angle": angle,
                            "source_url": candidate.url,
                            "scraped_at": pipeline.utc_now_iso(),
                            "sha256": pipeline.file_sha256(final),
                            "criteria_version": version,
                            "status": "ok",
                            "error": "",
                        },
                    )
                    downloaded += 1
                elif result.path:
                    # The file exists but conversion failed: move it out of the category tree and log it.
                    failed_path = pipeline.move_to_failed(criteria, result.path)
                    pipeline.append_log(
                        criteria.output.conversion_errors_log,
                        f"{candidate.url} | {failed_path} | {result.error_message}",
                    )
                    conversion_errors += 1
                else:
                    pipeline.append_log(
                        criteria.output.scrape_log,
                        f"{candidate.url} | {result.status} | {result.error_message}",
                    )
                    failed += 1
        finally:
            browser.close()

    _write_filtered_log(Path(criteria.output.filtered_log), filtered)
    try:
        tmp_root.rmdir()  # only removes the folder when it is empty
    except OSError:
        pass

    print(f"{downloaded} downloaded, {failed} failed, {conversion_errors} conversion_errors")
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

    if args.download_one:
        return _download_one(args.download_one, criteria)

    if not args.url:
        print("a product URL is required unless --validate-only is given", file=sys.stderr)
        return 2

    if args.dry_run and args.save:
        print("--dry-run and --save cannot be combined", file=sys.stderr)
        return 2

    if args.save:
        return _save(args.url, criteria, args.criteria, args.limit)

    if args.dry_run:
        return _dry_run(args.url, criteria, args.limit)

    print("use --dry-run or --save", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
