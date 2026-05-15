from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any, Dict, List

from lib import get_config, read_json, write_json, normalize_url


def _index_by_url(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for r in rows:
        url = r.get('url') or r.get('source_url') or ''
        if url:
            out[normalize_url(url, strip_query=True)] = r
    return out


def _score(row: Dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = row.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _severity(gap: float) -> str:
    if gap >= 25: return 'severe'
    if gap >= 10: return 'material'
    if gap >= 1: return 'minor'
    return 'owned_at_or_above_benchmark'


def _themes(owned_rows: List[Dict[str, Any]], external_rows: List[Dict[str, Any]], visibility: Dict[str, Any]) -> List[str]:
    themes = []
    dims = Counter()
    for r in owned_rows:
        for d, obj in (r.get('dimension_scores') or {}).items():
            if isinstance(obj, dict) and int(obj.get('score') or 0) <= 15:
                dims[d] += 1
    for d, _ in dims.most_common(4):
        if d == 'faq_readiness': themes.append('Add conversational FAQ coverage that matches the query language')
        elif d == 'structured_data': themes.append('Add schema and machine-readable content modules')
        elif d == 'semantic_depth': themes.append('Add deeper facts, assumptions and decision criteria')
        elif d == 'eeat_signals': themes.append('Add official proof, citations, authority or validation signals')
        elif d == 'content_clarity': themes.append('Add answer-first summaries and clearer headings')
        elif d == 'freshness_index': themes.append('Add visible freshness, validity dates and indexability signals')
    patterns = Counter(p for r in external_rows for p in (r.get('winning_patterns') or []))
    for p, _ in patterns.most_common(3):
        themes.append(f'Match external winning pattern: {p}')
    if visibility.get('competitor_cited'):
        themes.append('Counter competitor displacement with brand-owned comparison and proof')
    return list(dict.fromkeys(themes))[:8]


def main() -> None:
    cfg = get_config()
    scope = read_json(cfg['paths']['evidence_scope'], default={'queries': []})
    owned = read_json(cfg['paths']['owned_readiness'], default={'page_analysis': []})
    external_bench = read_json('outputs/benchmark/winning_source_patterns.json', default={'source_patterns': []})
    ai = read_json('outputs/visibility/ai_visibility_scores.json', default={'queries': []})
    owned_idx = _index_by_url(owned.get('page_analysis', []))
    ext_idx = _index_by_url(external_bench.get('source_patterns', []))
    ai_idx = {r.get('query'): r for r in ai.get('queries', [])}
    per_query = []
    for i, q in enumerate(scope.get('queries', []), start=1):
        owned_rows = []
        for p in q.get('owned_pages', []):
            r = owned_idx.get(normalize_url(p.get('url', ''), strip_query=True))
            if r: owned_rows.append(r)
        external_rows = []
        for p in q.get('external_pages', []) or q.get('external_sources', []):
            r = ext_idx.get(normalize_url(p.get('url', ''), strip_query=True))
            if r: external_rows.append(r)
        owned_scores = [_score(r, 'geo_score_120', 'readiness_score') for r in owned_rows]
        owned_scores = [s for s in owned_scores if s is not None]
        ext_scores = [_score(r, 'external_benchmark_score', 'readiness_score') for r in external_rows]
        ext_scores = [s for s in ext_scores if s is not None]
        best_owned = max(owned_scores) if owned_scores else 0
        best_external = max(ext_scores) if ext_scores else 0
        gap = round(best_external - best_owned, 1)
        vis = ai_idx.get(q.get('query'), {})
        status = vis.get('visibility_status') or ('external_led' if external_rows and not vis.get('owned_target_page_cited') else 'not_validated')
        per_query.append({
            'query_id': q.get('query_id') or f'q{i:03d}',
            'query': q.get('query', ''),
            'query_type': q.get('query_type', ''),
            'brand_topic_category': q.get('brand_topic_category', ''),
            'visibility_status': status,
            'owned_target_page_cited': bool(vis.get('owned_target_page_cited')),
            'owned_domain_cited': bool(vis.get('owned_domain_cited')),
            'winning_external_source_types': list(dict.fromkeys([(r.get('source_type') or r.get('source_category') or 'unknown') for r in external_rows])),
            'owned_geo_score_120_best': best_owned,
            'owned_geo_score_120_median': median(owned_scores) if owned_scores else 0,
            'external_benchmark_score_best': best_external,
            'external_benchmark_score_median': median(ext_scores) if ext_scores else 0,
            'source_preference_gap': gap,
            'gap_severity': _severity(gap),
            'gap_reasons': _themes(owned_rows, external_rows, vis),
            'owned_pages': [{'url': r.get('url'), 'geo_score_120': r.get('geo_score_120'), 'readiness_score': r.get('readiness_score'), 'dimension_scores': r.get('dimension_scores', {})} for r in owned_rows],
            'external_sources': [{'url': r.get('url') or r.get('source_url'), 'external_benchmark_score': r.get('external_benchmark_score'), 'source_type': r.get('source_type') or r.get('source_category'), 'winning_patterns': r.get('winning_patterns', [])} for r in external_rows],
        })
    gaps = [r['source_preference_gap'] for r in per_query]
    out = {
        'schema_version': 'source_preference_gap_v1',
        'brand': cfg.get('brand'),
        'market': cfg.get('market'),
        'per_query': per_query,
        'aggregate': {
            'query_count': len(per_query),
            'avg_source_preference_gap': round(mean(gaps), 1) if gaps else 0,
            'median_source_preference_gap': round(median(gaps), 1) if gaps else 0,
            'gap_severity_mix': dict(Counter(r['gap_severity'] for r in per_query)),
            'visibility_status_mix': dict(Counter(r['visibility_status'] for r in per_query)),
        }
    }
    write_json('outputs/benchmark/owned_vs_external_gap_analysis.json', out)
    print('Wrote outputs/benchmark/owned_vs_external_gap_analysis.json')


if __name__ == '__main__':
    main()
