from __future__ import annotations

from pathlib import Path
import json
import sys
from lib import get_config, resolve_path

REQUIRED = [
    'outputs/visibility/ai_visibility_scores.json',
    'outputs/source_landscape/source_classification.json',
    'outputs/source_landscape/competitor_publisher_landscape.json',
    'outputs/page_scores/owned_page_scores.json',
    'outputs/page_scores/external_page_scores.json',
    'outputs/benchmark/winning_source_patterns.json',
    'outputs/benchmark/owned_vs_external_gap_analysis.json',
    'outputs/recommendations/owned_page_content_recommendations.json',
    'outputs/pr_publisher_opportunities/pr_opportunity_plan.json',
    'outputs/dashboard/ai_visibility_dashboard_dataset.json',
    'outputs/bodhi/bodhi_input_bundle.json',
]


def read(path: str):
    p = resolve_path(path)
    if not p.exists():
        raise AssertionError(f'Missing required output: {path}')
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        raise AssertionError(f'Invalid JSON {path}: {e}')


def main() -> None:
    errors = []
    loaded = {}
    for path in REQUIRED:
        try:
            loaded[path] = read(path)
        except AssertionError as e:
            errors.append(str(e))
    if not errors:
        owned = loaded['outputs/page_scores/owned_page_scores.json']
        if not owned.get('page_analysis'):
            errors.append('owned_page_scores.json has no page_analysis rows')
        else:
            bad = [r.get('url') for r in owned['page_analysis'] if r.get('geo_score_120') is None and r.get('content_score_policy') != 'exclude_from_content_score']
            if bad:
                errors.append(f'Owned rows missing geo_score_120: {len(bad)}')
        ai = loaded['outputs/visibility/ai_visibility_scores.json']
        if not ai.get('queries'):
            errors.append('ai_visibility_scores.json has no query rows')
        src = loaded['outputs/source_landscape/source_classification.json']
        if 'sources' not in src:
            errors.append('source_classification.json missing sources array')
        recs = loaded['outputs/recommendations/owned_page_content_recommendations.json']
        pages = recs.get('pages', [])
        if not pages:
            errors.append('owned_page_content_recommendations.json has no pages')
        else:
            html_recs = sum(len(p.get('recommended_content_changes', [])) for p in pages)
            if html_recs == 0:
                errors.append('owned_page_content_recommendations.json contains no HTML-level recommendations')
    report = {
        'validation_status': 'failed' if errors else 'success',
        'errors': errors,
        'required_files_checked': REQUIRED,
    }
    Path(resolve_path('outputs/validation')).mkdir(parents=True, exist_ok=True)
    Path(resolve_path('outputs/validation/validation_report.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if errors:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(1)
    print('Validation passed. Wrote outputs/validation/validation_report.json')


if __name__ == '__main__':
    main()
