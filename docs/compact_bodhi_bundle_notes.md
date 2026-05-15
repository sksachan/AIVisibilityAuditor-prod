# Compact Bodhi Bundle Export Patch

This patch changes only `scripts/11_export_bodhi_bundle.py`.

## What changes

The export step now writes three Bodhi bundle files:

- `outputs/bodhi/bodhi_input_bundle.json` — compact bundle, kept at the legacy path for existing workflows.
- `outputs/bodhi/bodhi_input_bundle_compact.json` — compact bundle for Bodhi upload.
- `outputs/bodhi/bodhi_input_bundle_full.json` — full evidence archive for debugging and traceability.

The dashboard dataset remains separate:

- `outputs/dashboard/ai_visibility_dashboard_dataset.json`

## Intended use

Upload this file to Bodhi:

```text
outputs/bodhi/bodhi_input_bundle_compact.json
```

or, because the legacy path is now compact too:

```text
outputs/bodhi/bodhi_input_bundle.json
```

Use the dashboard dataset separately for the React dashboard.

## Why

The previous Bodhi bundle embedded large repeated structures, including full audit context, visibility matrix, benchmark detail and dashboard dataset. This patch keeps the full archive, but gives Bodhi a lean summary-oriented JSON to reduce token load, timeout risk and repetitive LLM output.
