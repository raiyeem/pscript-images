# pscript-images

A criteria-driven image scraper for product pages. Every domain value (categories, brands, conditions, angles, filename template, output paths, and the site-specific extraction rules) lives in `criteria.yml`. The code reads those values and never embeds them.

The first target is a golf marketplace (foremarket.se), but nothing in the code is specific to that site. Pointing the scraper at another site means editing `criteria.yml`, not the Python.

## Features

- **Criteria-driven.** `criteria.yml` is validated with pydantic at startup. Errors name the file, line, and key path.
- **Category discovery.** Crawls a category page through the site's filter API (paginated), with a JSON-LD fallback for categories the API does not cover.
- **Image extraction.** Waits for lazy-loaded content in a headless Chromium session (Playwright), then filters out small, excluded, seller, and avatar images.
- **Downloads.** Uses `requests` first. On HTTP 403 it retries inside the Playwright session. Images are converted to JPEG (Pillow).
- **Classification.** Category and brand come from the product's spec table, with keyword fallback. Brands are normalised against a canonical list and aliases. Unknown brands are queued for human review, never auto-promoted.
- **Output.** Organised folders, a `manifest.csv` with one row per image, `coverage.json` (required angles captured vs. missing), and per-run logs.
- **Resumable.** Already-downloaded URLs are skipped. `--no-resume` refreshes existing rows in place.
- **Polite.** Checks `robots.txt` before crawling, honours `Crawl-delay`, and sleeps between downloads.

## Requirements

- Windows, PowerShell
- Python 3.14
- Chromium for Playwright

## Setup

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m playwright install chromium
```

## Usage

```powershell
# Check criteria.yml without touching the network
.\venv\Scripts\python.exe scrape.py --validate-only

# Dry run on one product page (no files written)
.\venv\Scripts\python.exe scrape.py "https://foremarket.se/en/product/<id>" --dry-run

# Save one product page
.\venv\Scripts\python.exe scrape.py "https://foremarket.se/en/product/<id>" --save

# Discover the product URLs in a category (no downloads)
.\venv\Scripts\python.exe scrape.py --crawl "https://foremarket.se/en/explore?category=driver"

# Discover a category and save every product in it
.\venv\Scripts\python.exe scrape.py --crawl-and-save "https://foremarket.se/en/explore?category=driver" --save

# Start that category fresh (clears previous outputs first)
.\venv\Scripts\python.exe scrape.py --crawl-and-save "https://foremarket.se/en/explore?category=driver" --save --reset

# Re-download products already in the manifest
.\venv\Scripts\python.exe scrape.py "<product url>" --save --no-resume
```

Other options:

| Option | Purpose |
| --- | --- |
| `--limit N` | Cap images per product |
| `--download-one URL` | Download a single image URL (debugging) |
| `--propose-criteria` | Write `criteria.proposed.yml` from the review queue (never edits `criteria.yml`) |
| `--renormalize MANIFEST` | Re-apply brand normalisation to an existing manifest |
| `--rename-files` | With `--renormalize`, also rename files to match |

`--crawl-and-save` requires `--save`. It cannot be combined with `--no-resume`, `--crawl`, or `--dry-run`.

## Configuration

`criteria.yml` is the single source of truth. Its main sections:

| Section | Controls |
| --- | --- |
| `output` | Output paths, image format (`jpeg`, `png`, `original`), JPEG quality |
| `naming` | Folder and filename templates, missing-value token, index padding |
| `fields.brand` / `fields.condition` | Canonical values, aliases, placeholders, review queue |
| `categories` | Category names, aliases, keywords, required angles |
| `angles` | Angle aliases |
| `extraction` | Spec labels, minimum image size, excluded extensions and URL patterns, scroll and wait settings |
| `politeness` | Delay between downloads, `robots.txt` handling, user agent, timeouts |
| `crawl` | Discovery limits, log path, filter API settings, category ID map |

Every saved image appends one row to `manifest.csv`. The columns are:

`file, category, brand, brand_raw, brand_source, condition, angle, source_url, scraped_at, sha256, criteria_version, status, error`

`criteria_version` is the first 12 hex characters of the SHA-256 of `criteria.yml`, so each row records which config produced it.

## Output layout

```
images/
  <Category>/
    <brand>_<condition>_<angle>_<index>.jpg
  manifest.csv
  _failed/          files that failed conversion
coverage.json
crawl.log           one line per product during --crawl-and-save
filtered.log        images removed by extraction rules
review/brands_unknown.csv
```

Generated outputs are gitignored.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

The tests fake the browser, extraction, and downloads, and run inside `tmp_path`. They do not touch the network or the real output folders.

## Responsible use

This tool downloads product photos from a third-party website. Before running it against any site:

- Check that the site's terms of service allow automated access.
- Respect `robots.txt`. The scraper checks it and stops on an explicit disallow for its user agent, but that check does not establish that you may use the images.
- Keep the politeness delay in place.
- Do not redistribute the images without the rights holder's permission. Images are typically copyrighted.

## Project notes

- `CLAUDE.md` holds the working rules for Claude Code sessions on this repo.
- `probe_notes.md` records the site probes that informed the extraction and crawl rules.
- `plan.md` is the milestone plan.
