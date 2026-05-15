# AI Visibility Pipeline – local final operating model

This project is a local Python implementation for the AI Search Visibility workflow.

## Input JSON files

The zip includes three optional user-supplied input examples:

- `inputs/brand_topic_categories/nissan_japan_brand_topic_categories.json`
- `inputs/query_portfolios/nissan_japan_query_portfolio.json`
- `inputs/owned_urls/nissan_japan_owned_urls.json`

These mirror the Bodhi-upload scenario where the user provides brand topic categories, query portfolio and owned URLs. If omitted in a future Bodhi flow, an LLM node can generate synthetic topic/query inputs and the Python sitemap resolver can supply owned URL candidates.

## No paid crawler dependency

The active crawler is the local full-page scraper. Firecrawl is not required. SerpAPI is only used by `scripts/02_collect_google_ai_mode.py`; skip that step when cached Google AI Mode JSON exists.

## Recommended local run without SerpAPI refetch

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium

# Paste cached Google AI Mode JSON into outputs/google_ai_mode/ first, then run:
python3 scripts/00_collect_site_standards.py
python3 scripts/01_build_audit_context.py
python3 scripts/03_build_visibility_matrix.py
python3 scripts/04_select_evidence_scope.py
python3 scripts/05_scrape_owned_pages.py
python3 scripts/06_scrape_external_pages.py
python3 scripts/07_score_pages.py
python3 scripts/08_benchmark_owned_vs_external.py
python3 scripts/09_generate_preference_rules.py
python3 scripts/10_generate_improvement_backlog.py
python3 scripts/11_export_bodhi_bundle.py
python3 scripts/12_source_classifier.py
python3 scripts/13_ai_visibility_scorer.py
python3 scripts/14_external_benchmark_scorer.py
python3 scripts/15_source_preference_gap.py
python3 scripts/16_owned_page_content_recommendation_generator.py
python3 scripts/17_pr_publisher_opportunity_generator.py
python3 scripts/18_export_integrated_dashboard_bundle.py
python3 scripts/99_validate_pipeline_outputs.py
```

## New output files

- `outputs/visibility/ai_visibility_scores.json`
- `outputs/source_landscape/source_classification.json`
- `outputs/source_landscape/competitor_publisher_landscape.json`
- `outputs/benchmark/winning_source_patterns.json`
- `outputs/benchmark/owned_vs_external_gap_analysis.json`
- `outputs/recommendations/owned_page_content_recommendations.json`
- `outputs/recommendations/cms_content_generation_briefs.json`
- `outputs/pr_publisher_opportunities/pr_opportunity_plan.json`
- `outputs/dashboard/ai_visibility_dashboard_dataset.json`
- `outputs/bodhi/bodhi_input_bundle.json`

## Scoring separation

- Owned pages are scored strictly using the 6 x 20 GEO readiness framework.
- AI visibility is scored from observed Google AI Mode citation evidence.
- External pages are used as observed winning-source benchmarks.
- CMS recommendations are generated as HTML-module-level briefs for Bodhi LLM content generation.
