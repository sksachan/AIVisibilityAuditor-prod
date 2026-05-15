from __future__ import annotations

import importlib.util
from pathlib import Path

STEPS = [
    '00_collect_site_standards.py',
    '01_build_audit_context.py',
    '02_collect_google_ai_mode.py',
    '03_build_visibility_matrix.py',
    '04_select_evidence_scope.py',
    '05_scrape_owned_pages.py',
    '06_scrape_external_pages.py',
    '07_score_pages.py',
    '08_benchmark_owned_vs_external.py',
    '09_generate_preference_rules.py',
    '10_generate_improvement_backlog.py',
    '11_export_bodhi_bundle.py',
    '12_source_classifier.py',
    '13_ai_visibility_scorer.py',
    '14_external_benchmark_scorer.py',
    '15_source_preference_gap.py',
    '16_owned_page_content_recommendation_generator.py',
    '17_pr_publisher_opportunity_generator.py',
    '18_export_integrated_dashboard_bundle.py',
    '99_validate_pipeline_outputs.py',
]


def run(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    mod.main()


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    for step in STEPS:
        run(root / step)
