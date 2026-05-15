# Local AI Visibility Pipeline — v3

This project builds a local, evidence-backed AI visibility and GEO readiness dataset for a brand/market audit.

## What changed in this patch

- Removed Firecrawl from the active crawling path; the default crawler is now free/local.
- Added `scripts/local_hybrid_scraper.py`, which combines static trafilatura extraction with Playwright-rendered DOM enrichment.
- Added per-URL extraction manifests so scoring reads structured evidence signals, not just markdown length.
- Backed up Firecrawl-era markdown under `outputs/firecrawl_markdown_backup/` for future reference.
- Cleaned out local virtualenv/cache/test artefacts from the project package.

## What changed in v3

- Uses a documented **GEO / AI Source Readiness Framework** based on six 20-point dimensions, for a total score out of 120.
- Applies the same page scoring logic to **owned pages** and **external pages**.
- Maps up to **3 owned URLs per query** from the owned URL inventory.
- Collects up to **3 Google AI Mode reference URLs per query** from SerpAPI.
- Benchmarks each query using **median owned score vs median external score** while preserving every individual page score.
- Adds page-level content improvement recommendations for each owned page.
- Exports a dashboard-ready dataset at `outputs/dashboard/ai_visibility_dashboard_dataset.json`.

## Scoring framework

The scoring framework is defined in `config/scoring_weights.yaml`.

Each page is scored across:

1. Content Clarity — 20 points
2. Semantic Depth — 20 points
3. Structured Data — 20 points
4. E-E-A-T Signals — 20 points
5. Freshness & Index — 20 points
6. FAQ Readiness — 20 points

Total: `geo_score_120` out of 120.

For backwards compatibility, each page also keeps `readiness_score` out of 100.

## Run

```bash
cd local_ai_visibility
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
# Add SERPAPI_API_KEY
./run_all.sh
```

## Refetch logic

- SerpAPI is reused only if existing Google AI Mode output has sufficient top-3 references for most queries.
- If existing output does not have top-3 references, `02_collect_google_ai_mode.py` will refetch SerpAPI unless `force_refetch_serpapi` is already true or API key is missing.
- The free hybrid local scraper reuses collected pages where possible and only crawls missing selected URLs. It uses static trafilatura extraction plus Playwright-rendered DOM enrichment; no paid crawling API is used by default.

## Key outputs

- `outputs/audit_context/audit_context.json` — 70 queries, owned URL mapping, up to 3 owned pages per query.
- `outputs/visibility/visibility_matrix.json` — Google AI Mode visibility and up to 3 external references per query.
- `outputs/evidence_scope/evidence_scope.json` — selected owned and external pages per query.
- `outputs/page_scores/owned_page_scores.json` — owned page GEO readiness scores and page-level recommendations.
- `outputs/page_scores/external_page_scores.json` — external page GEO readiness scores and source quality flags.
- `outputs/benchmark/source_preference_benchmark.json` — query-level owned vs external median benchmark.
- `outputs/actions/improvement_backlog.json` — prioritised actions.
- `outputs/dashboard/ai_visibility_dashboard_dataset.json` — frontend-ready dashboard dataset.
- `outputs/bodhi/bodhi_input_bundle.json` — compact bundle for downstream report workflow.
