# Strict Owned URL GEO Scoring v5.6

This patch fixes query-workbench owned URL scoring so the final report preserves strict upstream GEO scores instead of applying a loose fallback heuristic.

## Problem fixed

`build_query_workbench_bundle.py` previously recognised only `score_120` and `geo_readiness_score` when a page had already been scored. Records carrying `geo_score_120`, `readiness_score`, or nested `dimension_scores` were ignored and rescored with a fallback that could over-award Content Clarity, often showing 20/20 across multiple pages.

## New behaviour

The mapper now preserves the first available score from:

- `score_120`
- `geo_score_120`
- `current_geo_score_120`
- `geo_readiness_score`
- `readiness_score`

It also normalises dimension structures from either flat values or nested `{score: ...}` objects.

If no scored evidence exists, the fallback is now stricter. It requires answer-first query coverage, numeric/proof signals, schema/FAQ evidence and freshness signals before a page can reach higher bands. Caps prevent long official pages from looking citation-ready purely because they have large amounts of catalogue text.

## Rationale

The scoring model follows the GEO evidence basis that generative engines reward citation-ready content: answer-first structure, statistics, quotations/citations, source-backed claims, fluency and extractability. It should therefore distinguish between pages with visible query answers and pages that are official but generic.
