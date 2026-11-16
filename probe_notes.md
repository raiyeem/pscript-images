# Probe notes: dev.foremarket.se

Probed with Playwright MCP on 2026-11-16. No scraper code written.

## Page and scroll

- Navigated to `https://dev.foremarket.se`, which redirected to `https://dev.foremarket.se/en` (title: "Foremarket").
- Scrolled in 5 equal steps to the bottom, waiting 1.5 s after each step. Page height stayed at 4915 px, so no new content loaded during the scroll.
- Console on load: 1 error, 1 warning (not inspected further).
- Only the landing page was probed. No links were followed.

## Images (32 `<img>` elements)

"Heading" is the nearest preceding `<h1>`/`<h2>` in DOM order. `loaded` is `complete && naturalWidth > 0` at probe time. No `data-src` attributes were found on any image.

| # | src | srcset | alt | nearest heading | loaded |
|---|-----|--------|-----|-----------------|--------|
| 0 | `/_next/image?url=%2Flogo.png&w=256&q=75` | `…w=128… 1x, …w=256… 2x` | Foremarket | none | yes |
| 1 | `/logos/bankid.svg` | — | BankID | none | yes |
| 2 | `/logos/bankid.svg` | — | BankID | none | no |
| 3 | `/app-store-badge.svg` | — | Download on the App Store | H1 "Buy & sell golf equipment smarter than ever" | yes |
| 4 | `/google-play-badge.svg` | — | Get it on Google Play | H1 (same) | yes |
| 5 | `/_next/image?url=%2Fgolf-professional-hero.jpg&w=3840&q=75` | 8 widths 640w–3840w (`/_next/image?url=%2Fgolf-professional-hero.jpg&w=N&q=75 Nw`) | Golf course aerial view | H1 (same) | yes |
| 6 | `https://dev-assets.foremarket.se/products/a2b5c292-ae08-444f-bb5f-9f4e603b786f-1.webp` | — | Try UX | H2 "Listings" | yes |
| 7 | `https://dev-assets.foremarket.se/products/6056c30c-7450-4a33-8ca4-6ea853071202-1.webp` | — | Cobra Head SSS | H2 "Listings" | yes |
| 8 | `https://dev-assets.foremarket.se/products/6b4ab43d-bd27-4126-aff4-cc1ffc969c64-1.webp` | — | Water pot | H2 "Listings" | yes |
| 9 | `https://dev-assets.foremarket.se/products/798d235f-3b6a-4e3e-aa13-2c8f17329613-2.webp` | — | Format MTB | H2 "Listings" | yes |
| 10 | `https://dev-assets.foremarket.se/products/7f4cf11d-1d94-4d4e-9ae3-45f6710d61d1-2.webp` | — | Format MTB | H2 "Listings" | yes |
| 11 | `https://dev-assets.foremarket.se/products/eba15c9a-a1c0-44f9-9cb1-65ea4a303218-1.webp` | — | `**Open-Source Intelligence**: collecting and analy…` | H2 "Listings" | yes |
| 12 | `https://dev-assets.foremarket.se/products/8deeaa4b-c5ad-44ea-b47d-dc89e591863c-1.webp` | — | hey | H2 "Listings" | yes |
| 13 | `https://dev-assets.foremarket.se/products/32129d33-7f28-471a-b125-455c8a2e7279-1.webp` | — | Bettinardi Golf Irons Set of 7 Dynamic Gold Shafts | H2 "Listings" | no |
| 14 | `https://dev-assets.foremarket.se/products/43710f30-4d66-4b96-91cb-3f69b9883f05-1.webp` | — | 2 devs | H2 "Listings" | no |
| 15 | `https://dev-assets.foremarket.se/products/4f5502e0-8a8d-4e9f-8d5d-88f2284a61d3-1.webp` | — | TEST LISTING 2 - Playwright QA (delete me) | H2 "Listings" | no |
| 16 | `https://dev-assets.foremarket.se/categories/ios/driver.png` | — | Driver | H2 "Category" | no |
| 17 | `https://dev-assets.foremarket.se/categories/ios/fairway-wood.png` | — | Fairway Wood | H2 "Category" | no |
| 18 | `https://dev-assets.foremarket.se/categories/ios/iron.png` | — | Iron | H2 "Category" | no |
| 19 | `https://dev-assets.foremarket.se/categories/ios/hybrid.png` | — | Hybrid / Utility Iron | H2 "Category" | no |
| 20 | `https://dev-assets.foremarket.se/categories/ios/putter.png` | — | Putter | H2 "Category" | no |
| 21 | `https://dev-assets.foremarket.se/categories/ios/wedge.png` | — | Wedge | H2 "Category" | no |
| 22 | `https://dev-assets.foremarket.se/categories/ios/shaft.png` | — | Shaft | H2 "Category" | no |
| 23 | `https://dev-assets.foremarket.se/categories/ios/men-apparel.png` | — | Men Apparel | H2 "Category" | no |
| 24 | `https://dev-assets.foremarket.se/categories/ios/driver.png` | — | Driver | H2 "Category" | yes |
| 25 | `https://dev-assets.foremarket.se/categories/ios/fairway-wood.png` | — | Fairway Wood | H2 "Category" | yes |
| 26 | `https://dev-assets.foremarket.se/categories/ios/iron.png` | — | Iron | H2 "Category" | yes |
| 27 | `https://dev-assets.foremarket.se/categories/ios/hybrid.png` | — | Hybrid / Utility Iron | H2 "Category" | yes |
| 28 | `https://dev-assets.foremarket.se/categories/ios/putter.png` | — | Putter | H2 "Category" | yes |
| 29 | `https://dev-assets.foremarket.se/products/foremarket-product-default-image.jpg` | — | weeeeee | H2 "Premium clubs at outlet prices" | yes |
| 30 | `https://dev-assets.foremarket.se/products/foremarket-product-default-image.jpg` | — | weeeeee | H2 "Premium clubs at outlet prices" | yes |
| 31 | `/logo-White.svg` | — | Foremarket | H2 "Turn your clubs into cash" | yes |

Notes:
- Rows 13–23 are not loaded. Rows 24–28 are the same category images, loaded. This is likely a lazy or duplicated render. Row 22 and 23 have an empty `currentSrc`.
- Several alt texts look like dev or QA data ("TEST LISTING 2 - Playwright QA (delete me)", "hey", "2 devs", "weeeeee"). Treat them as page content, not as reliable labels.
- Row 11 alt contains Markdown bold markers (`**…**`).

## JSON-LD (`script[type="application/ld+json"]`): 2 blocks

1. Organization
   ```json
   {"@context":"https://schema.org","@type":"Organization","name":"Foremarket","url":"https://dev.foremarket.se","logo":"https://dev.foremarket.se/logo.png","email":"info@zwitch.se"}
   ```
2. WebSite
   ```json
   {"@context":"https://schema.org","@type":"WebSite","name":"Foremarket","url":"https://dev.foremarket.se","inLanguage":["en","sv"]}
   ```

Findings:
- `brand.name`: **not present**.
- `itemCondition`: **not present**.
- No `Product` or `ProductGroup` block exists on this page, so the `extraction.prefer_jsonld` path (criteria.yml `extraction`) has nothing to read here. Product pages need their own probe.

## Follow-up: why rows 13–23 are not loaded

Viewport at probe time was 1034×501. (The 1920×1080 in the analytics request is the screen size, not the viewport.)

Row 13 (Bettinardi, listing carousel):
- The `<img>` exists with a real, non-empty absolute `src` (`https://dev-assets.foremarket.se/products/32129d33-…-1.webp`). It is not a placeholder or data: URI.
- `loading="lazy"`, `complete=false`, `naturalWidth=0`.
- Its parent is a horizontal snap scroller (`overflow-x:auto`, clientWidth 987, scrollWidth 2492, scrollLeft 0). The image sits at x≈1771, beyond the 1034 px viewport. My vertical scroll never brought it into view.
- The browser never requested it. It is absent from the resource timing entries. Rows 14 and 15 (same carousel) are also absent.

Rows 16–23 (category thumbnails):
- Rows 16–23 sit in a `lg:hidden` block (display 0×0 at this width). Rows 24–28 are the desktop copies of the same category images, and they loaded.
- Rows 16–20 were requested (resource timing shows them). Rows 21–23 (wedge, shaft, men-apparel) were never requested.
- Row 16 reports `naturalWidth=161` on the later check, so it did load. My earlier "not loaded" value was a snapshot taken while the image was still decoding.

Direct `fetch()` of the asset URLs from the page fails with "Failed to fetch". This is probably CORS on the assets host, so it doesn't tell us whether the URLs are valid. Resource timing for the asset host shows status 0 (opaque), so it cannot confirm status codes either.

Conclusion: this is a scroll problem, not broken data. The `src` values are present and well-formed. The listing carousel needs horizontal scrolling to trigger lazy loading. Rows 21–23 are hidden-duplicate thumbnails that never entered view. Validating their URLs would need a request from inside the Playwright session (the 403 path), not `fetch()`.

## Product detail page — wilsson-dynapower-forged-5-pw-regular

URL: `https://foremarket.se/en/product/wilsson-dynapower-forged-5-pw-regular` (probed as given; no links followed). Page height 2130 px. Viewport 1034×501.

### Gallery and scroll

- Scrolled vertically to the bottom in 5 steps with 1.5 s waits.
- Checked every element with `overflow-x: auto|scroll` and `scrollWidth > clientWidth`. **None found**, so there is no horizontal carousel. Nothing to scroll horizontally.
- The gallery is a vertical thumbnail column (x≈18, five 76×76 thumbs, y≈191–559) beside a main image (314×520 at x≈128).
- Some images sit in a hidden block (0×0 rect), probably a mobile carousel. They are duplicates of the visible images.

### Every `<img>` (18 total, in DOM order)

| doc# | src | alt | gallery position | rect (w×h) |
|---|---|---|---|---|
| 0 | `/_next/image?url=%2Flogo.png&w=256&q=75` (srcset) | Foremarket | header logo | 120×45 |
| 1 | `/logos/bankid.svg` | BankID | header | 48×40 |
| 2 | `/logos/bankid.svg` | BankID | hidden duplicate | 0×0 |
| 3 | `https://assets.foremarket.se/products/5879f714-…-1.webp` | …regular thumbnail 1 | hidden copy, slot 1 | 0×0 |
| 4 | `…-2.webp` | …regular thumbnail 2 | hidden copy, slot 2 | 0×0 |
| 5 | `…-3.webp` | …regular thumbnail 3 | hidden copy, slot 3 | 0×0 |
| 6 | `…-4.webp` | …regular thumbnail 4 | hidden copy, slot 4 | 0×0 |
| 7 | `…-5.webp` | …regular thumbnail 5 | hidden copy, slot 5 | 0×0 |
| 8 | `…-1.webp` | Wilsson Dynapower Forged 5-Pw regular | hidden copy, main | 0×0 |
| 9 | no `src` | ROBERT E. | seller avatar slot (hidden) | 0×0 |
| 10 | `…-1.webp` | …regular thumbnail 1 | **thumbnail 1 (visible)** | 76×76 |
| 11 | `…-2.webp` | …regular thumbnail 2 | **thumbnail 2** | 76×76 |
| 12 | `…-3.webp` | …regular thumbnail 3 | **thumbnail 3** | 76×76 |
| 13 | `…-4.webp` | …regular thumbnail 4 | **thumbnail 4** | 76×76 |
| 14 | `…-5.webp` | …regular thumbnail 5 | **thumbnail 5** | 76×76 |
| 15 | `…-1.webp` | Wilsson Dynapower Forged 5-Pw regular | **main image (visible)** | 314×520 |
| 16 | no `src` | ROBERT E. | seller avatar (visible) | 46×46 |
| 17 | `/logo-White.svg` | Foremarket | footer | 165×62 |

(`…` = `https://assets.foremarket.se/products/5879f714-e35a-4a71-9785-bd4af07ad6d9`.)

Notes:
- Visible gallery = docs 10–15: 5 thumbnails plus 1 main image, all the same product (`5879f714-…`).
- Docs 3–8 are hidden copies of the same images. A scraper must dedupe by URL, not count `<img>` elements.
- Docs 9 and 16 are seller-avatar `<img>`s with no `src`. They are not product images.

### JSON-LD: 3 blocks (full text)

1. Organization
   ```json
   {"@context":"https://schema.org","@type":"Organization","name":"Foremarket","url":"https://foremarket.se","logo":"https://foremarket.se/logo.png","email":"info@zwitch.se"}
   ```
2. WebSite
   ```json
   {"@context":"https://schema.org","@type":"WebSite","name":"Foremarket","url":"https://foremarket.se","inLanguage":["en","sv"]}
   ```
3. Product
   ```json
   {"@context":"https://schema.org","@type":"Product","name":"Wilsson Dynapower Forged 5-Pw regular","description":"Wilson Dynapwr Forged järnset med KBS-skaft och Lamkin-grepp. Klubborna har skyddsplast kvar. Specifikationer: \n\n- Modell: Wilson Dynapwr Forged\n- Skaft: KBS tour lite regular\n- Grepp: Lamkin standard\n- Antal: 6 stycken\n-Kvitto finns","image":"https://assets.foremarket.se/products/5879f714-e35a-4a71-9785-bd4af07ad6d9-1.webp","offers":{"@type":"Offer","priceCurrency":"SEK","price":7000,"availability":"https://schema.org/InStock","url":"https://foremarket.se/en/product/wilsson-dynapower-forged-5-pw-regular","seller":{"@type":"Person","name":"ROBERT E.","url":"https://foremarket.se/en/profile/ed0ae76a-ec76-4ad4-bdba-55e29250f217"}}}
   ```

**Brand:** `brand.name` is **not** in JSON-LD. The Product block has no `brand` key.
**Condition:** `itemCondition` is **not** in JSON-LD.

Where brand appears on the page (not in JSON-LD):
- Specifications list, `<div>` with `<dt class="text-sm font-medium text-muted-foreground">Subcategory</dt><dd class="text-right text-sm font-semibold text-green-950">Wilson</dd>`. Rendered twice in the DOM. Visible text: "Subcategory / Wilson".
- Product `<h1>`: "Wilsson Dynapower Forged 5-Pw regular". Note the spelling **Wilsson** (double s).
- Description text: "Wilson Dynapwr Forged järnset …". Spelling **Wilson**.

So the brand data uses two spellings: "Wilson" in the Subcategory field and the description, and "Wilsson" in the title. The field is labelled Subcategory, not brand. The criteria `extraction.brand_keys` (`brand.name`, `brand`) will not find it, so it needs a DOM path. Under the current canonical list (`wilson` is canonical), "Wilsson" would fall to `brand_source=raw`.

Where condition appears (not in JSON-LD, no structured field found):
- No `<dt>`/`<dd>` labelled Condition. Visible specs are Category (Iron), Subcategory (Wilson), Shaft (Regular), Delivery, Shipping, Purchase protection.
- "Regular" is the shaft flex, not condition.
- Free-text hints only, in the description: "Klubborna har skyddsplast kvar" ("the clubs still have protective plastic on") and "Kvitto finns" ("receipt available"). These are not a condition field. Per CLAUDE.md ("model proposes, code authorizes"), a text hint must not set `condition`. With no structured value, `condition` should resolve to the `criteria.naming.missing_token` / `criteria.fields.condition.default` (`unknown`).

### Asset fetch from page context

Test: `fetch('https://assets.foremarket.se/products/5879f714-…-1.webp')` run inside the page (`browser_evaluate`).
- **Result: fails** with `TypeError: Failed to fetch`.
- Network log for that fetch: `[FAILED] net::ERR_FAILED`, type `fetch`, initiator `fetch`.
- `mode: 'no-cors'` gives an opaque response (`status 0`), so no status or bytes are readable.

The same image loaded fine as an `<img>` (network log #226): **HTTP 200**, **content-type `image/jpeg`**, **content-length 158698 bytes** (about 155 KB). Response headers include `via CloudFront`, `server AmazonS3`, `accept-ranges bytes`, and **no `access-control-allow-origin`**. The `ERR_FAILED` is a CORS block on the cross-origin fetch.

Conclusion for the M4 downloader:
- Plain `fetch()` from the page cannot read these bytes. The page's origin is `foremarket.se` and the assets host is `assets.foremarket.se`, and the assets host sends no CORS header.
- So an in-page `fetch()` will not work as a primary path, and it will not work as a fallback either.
- The 200 and size above were observed through the browser's network stack, not from page JavaScript. The downloader needs a request that isn't subject to page CORS. Playwright's request API (`context.request` / `page.request`, which runs outside page JS and shares the browser's cookies) is the likely candidate. **I did not test that here.** Test it before choosing it as primary.

### Extraction readiness

The gallery renders after the `load` event. Extraction waits for a `<dt>` selector (spec table rendered), then for at least one `<img>` with `naturalWidth >= extraction.min_dimension` and `naturalHeight >= extraction.min_dimension`. Both waits are gated by `extraction.wait_timeout_ms`. A timeout raises `RuntimeError`; it never returns an empty list. See criteria.yml for the selector and timeout.

### Classification signal (for M6)

- The specs table contains a `Category` field alongside `Subcategory`. Observed value on this page: `Category: Iron`. `extract_images` captures both in `specs`.
- M6's `classify()` must try `specs.get("Category")` first, normalising it against `criteria.categories[*].name` and `aliases`. For example, `Iron` matches the `Irons` category through its alias `iron`.
- Fall back to keyword matching only when the spec is absent or unrecognised.
- `heading` is `None` for this source, because the `<h1>` sits after the gallery in the DOM. The keyword fallback therefore has less to work with here.

## Follow-up: Python requests download test, thumbnail alts, condition coverage

### Python `requests` download of the main image

- `requests` was not installed in `venv` (Python 3.14.7). I installed `requests 2.34.2` (with `urllib3 2.8.0`, `certifi 2026.10.23`, `charset_normalizer 3.5.2`, `idna 3.20`) with `venv\Scripts\python.exe -m pip install requests`.
- Command: `requests.get(<main image URL>, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)`.
- Output: `200 image/jpeg 158698`. This matches the browser-side observation (200, image/jpeg, 158,698 bytes).
- Conclusion: no CORS block for a server-side client. `requests` works for this asset host. It is viable as M4's primary path. Test more images before relying on it, especially the 403 case from CLAUDE.md.

### Gallery thumbnail alts (in order)

1. `…/5879f714-e35a-4a71-9785-bd4af07ad6d9-1.webp` — alt: "Wilsson Dynapower Forged 5-Pw regular thumbnail 1"
2. `…-2.webp` — alt: "Wilsson Dynapower Forged 5-Pw regular thumbnail 2"
3. `…-3.webp` — alt: "Wilsson Dynapower Forged 5-Pw regular thumbnail 3"
4. `…-4.webp` — alt: "Wilsson Dynapower Forged 5-Pw regular thumbnail 4"
5. `…-5.webp` — alt: "Wilsson Dynapower Forged 5-Pw regular thumbnail 5"

The alts carry only the index, not the angle. The main image's alt is "Wilsson Dynapower Forged 5-Pw regular" with no index. For M8 (angle detection), the alt text gives no angle signal. The angle would have to come from the image content.

### Condition coverage across product pages

- Checked 1 product page (this one). It has Product JSON-LD with no `itemCondition`. The DOM has no condition field.
- The dev landing page has no Product JSON-LD at all.
- I have not checked any other product detail page. I only navigate to URLs you give me, so I did not follow links to a used listing.
- Result so far: condition is absent on the one product page checked. Whether it is systematically absent is not yet established. It needs at least one other product page, ideally a used listing.

## M8 scope

This data source does not label image angles; `{angle}` will be `unknown` for all downloads. Angle labeling is a manual post-processing step if needed.

Condition field is absent on the sampled product page; accepted as unknown for this source. If a labelled condition field is found later, add it to extraction.specs_labels.condition.

## M9 scope

Some pages (Odyssey, Golfkläder) put `Other` in `Subcategory`, so the brand is only in the title. `normalize_brand` does not read titles. Consider a brand-from-title fallback as a future enhancement.

Technical debt: manifest lacks condition_raw — condition aliases cannot be renormalized retroactively. If a manifest migration is ever worth doing, add condition_raw and re-scrape; otherwise this is a known limitation of older manifests.

## M10 scope

Known limitation: robots.txt `Allow:` directives are not parsed; only `Disallow:` prefix rules and `Crawl-delay` are honored. Combined rules like `Disallow: /product/` with `Allow: /product/specific-slug` will still block the specific slug. Preserves safe direction (block when disallowed) but is not fully RFC 9309 compliant.

Coverage report scope: `coverage.json`'s top-level `criteria_version` is the version of the run that produced the report — not every manifest row's version. After a `--no-resume` refresh against a different `criteria.yml`, the manifest can hold rows from multiple criteria versions, but the coverage report still describes only the current run. The manifest's per-row `criteria_version` column is the authoritative record of what produced each row's bytes.

## Open items

- Probe a product detail page (a URL you give me) to check for `Product` JSON-LD with `brand.name` and `itemCondition`, and to see its image markup.
- The listing thumbnails are served from `dev-assets.foremarket.se/products/…`, which is a different host from the page. Check whether that host needs the in-session download path for the 403 rule.
