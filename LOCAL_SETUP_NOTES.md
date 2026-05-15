# Local setup notes

This clean project package excludes `.env`, `.venv`, backup folders and generated `outputs/` artefacts.

Suggested setup:

```bash
cd local_ai_visibility
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

Run pipeline excluding SerpAPI refetch:

```bash
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
```

Do not run `scripts/02_collect_google_ai_mode.py` unless you intentionally want a SerpAPI refetch.
