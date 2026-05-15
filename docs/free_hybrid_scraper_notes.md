# Free hybrid local scraper

The active crawler no longer calls Firecrawl or any paid crawling API.

Default extraction path:

1. Static HTML fetch with `httpx`.
2. Clean main-content extraction with `trafilatura`.
3. Browser-rendered DOM collection with local Playwright Chromium.
4. Rendered DOM enrichment for section anchors, image alt text, important CTA/support/spec links, PDF/spec links and structured-data signals.
5. Merge and deduplicate static + rendered markdown.
6. Create a per-URL `extraction_manifest` used by scoring.

Outputs are written under:

- `outputs/free_hybrid/owned_pages/markdown/`
- `outputs/free_hybrid/owned_pages/rendered_html/`
- `outputs/free_hybrid/owned_pages/manifests/`
- `outputs/free_hybrid/external_pages/markdown/`
- `outputs/free_hybrid/external_pages/rendered_html/`
- `outputs/free_hybrid/external_pages/manifests/`

Firecrawl-era markdown has been copied to:

- `outputs/firecrawl_markdown_backup/`

Blocked external sources are preserved as evidence rows, but they are excluded from content-quality scoring via `content_score_policy: exclude_from_content_score`.

## 2026-05 local full-page mode

The active crawler now follows a Firecrawl-like local strategy:

- render the target HTML URL with Playwright;
- keep `only_main_content=false` behaviour by converting the full cleaned DOM to markdown;
- preserve header, navigation, footer, tables, all links, image alt text, metadata, canonical, robots and JSON-LD/schema signals;
- remove only active execution/tracking noise such as scripts, styles, cookie banners, ads and small hidden duplicates;
- parse PDFs only when the target URL itself is a PDF;
- collect linked PDF URLs as authority/support signals, but do not parse linked PDFs by default;
- write `markdown`, `rendered_html`, `raw_html` and an `extraction_manifest` per URL.

Scoring remains the same six-dimension /120 framework for owned and external pages. Extraction failure is separated from content weakness: blocked, failed and partial pages are preserved as evidence but excluded from content-quality score comparisons.
