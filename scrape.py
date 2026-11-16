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
from dataclasses import dataclass, field
import os
import sys
import time
import uuid
from urllib.parse import urlsplit
from pathlib import Path

from classify import ReviewCollector, classify, first_spec, normalize_brand, normalize_condition
from criteria import Criteria, CriteriaError, load_criteria
from extract import Filtered
from politeness import check_robots

_DOWNLOAD_TEST_STEM = Path(__file__).resolve().parent / "_download_test"
_KNOWN_MAGIC = {
    "ffd8ff": "JPEG",
    "52494646": "RIFF (WebP container)",
    "89504e47": "PNG",
}


@dataclass
class SaveTotals:
    """What one save run (one product page) produced. Accumulated across products in a crawl."""

    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    conversion_errors: int = 0
    saved_rows: list[dict[str, str]] = field(default_factory=list)
    filtered: list[Filtered] = field(default_factory=list)


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
        help="at most N images per product. Applies per product, not to the whole crawl.",
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
    parser.add_argument(
        "--reset",
        action="store_true",
        help="with --save: delete output.root (images, manifest, _failed, _tmp) and coverage.json first",
    )
    parser.add_argument(
        "--propose-criteria",
        action="store_true",
        help="write a proposals file from the review queue. Output only; criteria.yml is not changed.",
    )
    parser.add_argument(
        "--renormalize",
        metavar="MANIFEST",
        default=None,
        help="re-resolve brand columns in MANIFEST from brand_raw using the current criteria",
    )
    parser.add_argument(
        "--rename-files",
        action="store_true",
        help="with --renormalize: also rename files on disk to the new brand slug (destructive)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="with --save: download every candidate, even if its source_url is already in the manifest",
    )
    parser.add_argument(
        "--crawl",
        metavar="CATEGORY_URL",
        default=None,
        help="list the product URLs on a category page. Discovery only: no downloads, no manifest changes.",
    )
    parser.add_argument(
        "--crawl-and-save",
        metavar="CATEGORY_URL",
        default=None,
        help=(
            "discover a category's product URLs and save each one. Requires --save. "
            "Resume is always on; --reset runs once before the first product."
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


def _save(
    url: str,
    criteria: Criteria,
    criteria_file: Path,
    limit: int | None,
    no_resume: bool = False,
    delay: float = 0.0,
) -> SaveTotals:
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
    downloaded = failed = conversion_errors = skipped = 0
    # One manifest row per source_url. Existing rows are either skipped (resume) or
    # refreshed in place (--no-resume); a refresh never adds a row or a file.
    existing = pipeline.existing_rows_by_url(criteria)
    updates: dict[str, dict[str, str]] = {}
    pending_sleep = False
    saved_rows: list[dict[str, str]] = []
    review = ReviewCollector()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="load")
            candidates = extract_images(page, criteria, filtered=filtered)
            if limit is not None:
                candidates = candidates[:limit]

            for candidate in candidates:
                existing_row = existing.get(candidate.url)
                if existing_row is not None and not no_resume:
                    skipped += 1
                    continue

                if existing_row is not None:
                    # --no-resume: re-download into the file the manifest already names.
                    # No classification, no new index, no new row. A failure leaves the row as it was.
                    if pending_sleep:
                        if delay > 0:
                            time.sleep(delay)
                        pending_sleep = False
                    result = download_image(
                        candidate.url, tmp_root / uuid.uuid4().hex, page=page, criteria=criteria
                    )
                    if result.status == "ok":
                        target = pipeline.manifest_file_path(existing_row["file"])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(result.path, target)
                        updates[candidate.url] = {
                            **existing_row,
                            "sha256": pipeline.file_sha256(target),
                            "scraped_at": pipeline.utc_now_iso(),
                            "criteria_version": version,
                            "status": "ok",
                            "error": "",
                        }
                        downloaded += 1
                        pending_sleep = True
                    elif result.path:
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
                    continue

                category = classify(f"{candidate.url} {candidate.alt or ''}", candidate.specs, criteria)
                folder_key = category or missing
                if category is None:
                    pipeline.append_log(
                        criteria.output.unclassified_log,
                        f"no category match | {candidate.url} | {candidate.alt or '-'}",
                    )

                brand_raw = first_spec(candidate.specs, criteria.extraction.specs_labels.brand)
                brand, brand_source = normalize_brand(
                    brand_raw, criteria, product_url=url, review=review
                )
                condition = normalize_condition(
                    first_spec(candidate.specs, criteria.extraction.specs_labels.condition), criteria
                )
                angle = missing  # M8 not started

                # Politeness: wait between downloads. Sleeping happens before the next download
                # after a success, so there is no wait before the first image or after the last.
                if pending_sleep:
                    if delay > 0:
                        time.sleep(delay)
                    pending_sleep = False

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

                    row = {
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
                    }
                    pipeline.append_manifest(criteria, row)
                    saved_rows.append(row)
                    downloaded += 1
                    pending_sleep = True
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

    if updates:
        pipeline.replace_manifest_rows(criteria, updates)
        saved_rows.extend(updates.values())

    review.flush(criteria)
    try:
        tmp_root.rmdir()  # only removes the folder when it is empty
    except OSError:
        pass

    return SaveTotals(
        downloaded=downloaded,
        skipped=skipped,
        failed=failed,
        conversion_errors=conversion_errors,
        saved_rows=saved_rows,
        filtered=filtered,
    )


def _finish_run(source_url: str, criteria: Criteria, criteria_file: Path, totals: SaveTotals) -> None:
    """Write the filtered log and coverage report for a run, then print its summary."""
    import pipeline

    _write_filtered_log(Path(criteria.output.filtered_log), totals.filtered)
    version = pipeline.criteria_version(criteria_file)
    coverage_path = pipeline.write_coverage(criteria, totals.saved_rows, source_url, version)
    print(
        f"{totals.downloaded} downloaded, {totals.skipped} skipped, {totals.failed} failed, "
        f"{totals.conversion_errors} conversion_errors"
    )
    print(f"coverage: {coverage_path}")


def _crawl(category_url: str, criteria: Criteria) -> int:
    from discover import discover_product_urls

    if criteria.politeness.respect_robots:
        allowed, _ = check_robots(category_url, criteria)
        if not allowed:
            return 1  # blocked before discovery, so crawl.log is not written

    try:
        urls = discover_product_urls(category_url, criteria)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for url in urls:
        print(url)
    print(f"{len(urls)} URLs discovered from {category_url}")
    return 0


def _propose(criteria: Criteria) -> int:
    from maintenance import PROPOSAL_FILENAME, REPO_ROOT, propose_criteria

    queue = pipeline_repo_path(criteria.fields.brand.review_queue)
    clusters, raw_values = propose_criteria(criteria, queue, REPO_ROOT / PROPOSAL_FILENAME)
    if raw_values == 0:
        print("no unknowns to propose")
        return 0
    print(f"{clusters} cluster(s) proposed from {raw_values} raw value(s)")
    print(f"written: {REPO_ROOT / PROPOSAL_FILENAME}")
    return 0


def _renormalize(criteria: Criteria, manifest_arg: str, rename_files: bool) -> int:
    from maintenance import renormalize_manifest

    manifest = pipeline_repo_path(manifest_arg)
    changed, renamed, errors = renormalize_manifest(criteria, manifest, rename_files=rename_files)
    print(f"{changed} row(s) changed, {renamed} file(s) renamed, {errors} rename error(s)")
    print(f"log: {manifest.name}.renormalize.log next to {manifest}")
    return 0


def pipeline_repo_path(value: str | Path) -> Path:
    import pipeline

    return pipeline.repo_path(value)


def _log_product(
    criteria: Criteria,
    category_url: str,
    product_url: str,
    result: str,
    downloaded: int,
    skipped: int,
    error: str,
) -> None:
    import pipeline

    line = (
        f"{pipeline.utc_now_iso()} | {category_url} | product={product_url} | result={result} | "
        f"downloaded={downloaded} | skipped={skipped} | error={error or '-'}"
    )
    pipeline.append_log(criteria.crawl.log_path, line)


def _crawl_and_save(
    category_url: str,
    criteria: Criteria,
    criteria_file: Path,
    limit: int | None,
    reset: bool,
) -> int:
    """Discover a category's product URLs and save each one. Resume is always on."""
    import pipeline
    from discover import discover_product_urls

    delay = criteria.politeness.delay_seconds
    if criteria.politeness.respect_robots:
        allowed, delay = check_robots(category_url, criteria)
        if not allowed:
            return 1  # blocked before discovery and before --reset

    try:
        product_urls = discover_product_urls(category_url, criteria)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    total_products = len(product_urls)
    print(f"Discovered {total_products} URLs from {category_url}")
    if reset:
        pipeline.reset_outputs(criteria)  # once, before the first product

    totals = SaveTotals()
    succeeded = failed_products = 0
    for number, product_url in enumerate(product_urls, start=1):
        print(f"[{number}/{total_products}] {product_url}")
        try:
            product = _save(product_url, criteria, criteria_file, limit, no_resume=False, delay=delay)
        except Exception as exc:  # one bad product must not stop the crawl
            message = str(exc) or type(exc).__name__
            failed_products += 1
            _log_product(criteria, category_url, product_url, "failed", 0, 0, message)
            print(f"[{number}/{total_products}] failed: {message}")
            continue

        succeeded += 1
        totals.downloaded += product.downloaded
        totals.skipped += product.skipped
        totals.failed += product.failed
        totals.conversion_errors += product.conversion_errors
        totals.saved_rows.extend(product.saved_rows)
        totals.filtered.extend(product.filtered)
        _log_product(criteria, category_url, product_url, "ok", product.downloaded, product.skipped, "-")
        print(
            f"[{number}/{total_products}] ok: downloaded={product.downloaded} "
            f"skipped={product.skipped} failed={product.failed}"
        )

    _finish_run(category_url, criteria, criteria_file, totals)
    print(
        f"Crawl complete: {succeeded} products processed, {failed_products} failed, "
        f"{totals.downloaded} total images downloaded, {totals.skipped} skipped"
    )
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

    if args.rename_files and not args.renormalize:
        print("--rename-files only applies together with --renormalize", file=sys.stderr)
        return 2

    if args.crawl_and_save:
        if not args.save:
            print("--crawl-and-save requires --save", file=sys.stderr)
            return 2
        if args.no_resume:
            print("--no-resume is not meaningful with --crawl-and-save (resume is always on)", file=sys.stderr)
            return 2
        if args.crawl or args.dry_run:
            print("--crawl-and-save cannot be combined with --crawl or --dry-run", file=sys.stderr)
            return 2
        return _crawl_and_save(args.crawl_and_save, criteria, args.criteria, args.limit, args.reset)

    if args.crawl:
        return _crawl(args.crawl, criteria)

    if args.propose_criteria:
        return _propose(criteria)

    if args.renormalize:
        return _renormalize(criteria, args.renormalize, args.rename_files)

    if args.download_one:
        return _download_one(args.download_one, criteria)

    if not args.url:
        print("a product URL is required unless --validate-only is given", file=sys.stderr)
        return 2

    if args.dry_run and args.save:
        print("--dry-run and --save cannot be combined", file=sys.stderr)
        return 2

    if args.reset and not args.save:
        print("--reset only applies together with --save", file=sys.stderr)
        return 2

    if args.save:
        delay = criteria.politeness.delay_seconds
        if criteria.politeness.respect_robots:
            allowed, delay = check_robots(args.url, criteria)
            if not allowed:
                return 1  # checked before --reset, so a blocked run deletes nothing
        if args.reset:
            import pipeline

            pipeline.reset_outputs(criteria)
        totals = _save(
            args.url,
            criteria,
            args.criteria,
            args.limit,
            no_resume=args.no_resume,
            delay=delay,
        )
        _finish_run(args.url, criteria, args.criteria, totals)
        return 0

    if args.dry_run:
        return _dry_run(args.url, criteria, args.limit)

    print("use --dry-run or --save", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
