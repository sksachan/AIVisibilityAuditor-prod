# Locked orchestration strategy

This repository is now query-loop led. Do not reorient the workflow around generic page scoring or scattered dashboard parsers.

Canonical flow:

```text
query -> top 3 owned URLs -> top 3 external citations -> winning patterns -> CMS/PR recommendations -> rerun -> delta tracking -> refreshed recommendations
```

The canonical output object is `outputs/frontend_report_bundle.json`. The primary array is `query_workbench[]`.

Allowed future changes: scoring weights, thresholds, source-type mappings and UI presentation.

Avoid drift: do not make external page GEO score the core driver. External sources are benchmark evidence for why an answer engine preferred those citations for a specific query.
