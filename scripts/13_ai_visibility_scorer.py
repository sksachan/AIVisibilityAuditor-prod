from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Dict, List

from lib import get_config, read_json, write_json


def _score_query(row: Dict[str, Any], source_row: Dict[str, Any]) -> Dict[str, Any]:
    brand_present = bool(row.get('brand_present'))
    brand_prominence = str(row.get('brand_prominence') or '').lower()
    owned_target = bool(source_row.get('owned_target_page_cited') or row.get('target_page_cited'))
    owned_domain = bool(source_row.get('owned_domain_cited') or row.get('target_domain_cited'))
    citations = source_row.get('citation_mix', {}) or {}
    has_external = sum(v for k, v in citations.items() if k not in {'owned_target_page', 'owned_same_domain'}) > 0
    competitor = bool(source_row.get('competitor_cited'))
    top_type = source_row.get('top_cited_source_type') or 'none'

    owned_page_citation = 35 if owned_target else 15 if owned_domain else 0
    if owned_target:
        citation_rank = 15
    elif owned_domain:
        citation_rank = 8
    else:
        citation_rank = 0
    if 'intro' in brand_prominence or 'prominent' in brand_prominence:
        answer_prominence = 20
    elif brand_present or brand_prominence in {'body', 'present', 'mentioned'}:
        answer_prominence = 12
    elif owned_domain:
        answer_prominence = 6
    else:
        answer_prominence = 0
    sentiment = str(row.get('sentiment') or 'neutral').lower()
    if 'positive' in sentiment or 'recommended' in sentiment:
        sentiment_score = 10
    elif 'negative' in sentiment:
        sentiment_score = 0
    elif 'mixed' in sentiment or 'caveat' in sentiment:
        sentiment_score = 3
    else:
        sentiment_score = 6 if brand_present or owned_domain else 0
    competitor_displacement = 0 if competitor else 10 if has_external or owned_domain else 5
    if top_type in {'owned_target_page', 'owned_same_domain'}:
        source_control = 10
    elif top_type in {'authority_body', 'publisher_review', 'partner_infrastructure'}:
        source_control = 6
    elif top_type in {'aggregator_marketplace', 'forum_social_video', 'low_quality_unknown'}:
        source_control = 3
    elif top_type == 'competitor_owned':
        source_control = 0
    else:
        source_control = 2
    score = owned_page_citation + answer_prominence + citation_rank + sentiment_score + competitor_displacement + source_control
    if owned_target:
        status = 'owned_led'
    elif owned_domain and has_external:
        status = 'mixed'
    elif has_external:
        status = 'external_led'
    else:
        status = 'not_validated'
    diagnosis = []
    if not owned_target:
        diagnosis.append('No mapped owned target page cited')
    if has_external:
        diagnosis.append('External cited sources shape the answer')
    if competitor:
        diagnosis.append('Competitor source appears in citation set')
    if top_type:
        diagnosis.append(f'Top cited source type: {top_type}')
    return {
        'ai_visibility_score': max(0, min(100, score)),
        'visibility_status': status,
        'component_scores': {
            'owned_page_citation': owned_page_citation,
            'answer_prominence': answer_prominence,
            'citation_rank': citation_rank,
            'sentiment_or_framing': sentiment_score,
            'competitor_displacement': competitor_displacement,
            'source_control': source_control,
        },
        'visibility_diagnosis': diagnosis,
    }


def main() -> None:
    cfg = get_config()
    google = read_json(cfg['paths']['google_ai_mode_output'], default={'per_query': []})
    source = read_json('outputs/source_landscape/source_classification.json', default={'queries': []})
    source_by_query = {q.get('query'): q for q in source.get('queries', [])}
    rows: List[Dict[str, Any]] = []
    for idx, item in enumerate(google.get('per_query', []), start=1):
        qsrc = source_by_query.get(item.get('query'), {})
        scored = _score_query(item, qsrc)
        rows.append({
            'query_id': qsrc.get('query_id') or item.get('query_id') or f'q{idx:03d}',
            'query': item.get('query', ''),
            'query_type': item.get('query_type', ''),
            'brand_topic_category': item.get('brand_topic_category', ''),
            'brand_mentioned': bool(item.get('brand_present')),
            'brand_prominence': item.get('brand_prominence', 'absent'),
            'owned_target_page_cited': bool(qsrc.get('owned_target_page_cited') or item.get('target_page_cited')),
            'owned_domain_cited': bool(qsrc.get('owned_domain_cited') or item.get('target_domain_cited')),
            'competitor_cited': bool(qsrc.get('competitor_cited')),
            'publisher_cited': bool(qsrc.get('publisher_cited')),
            'aggregator_cited': bool(qsrc.get('aggregator_cited')),
            'authority_body_cited': bool(qsrc.get('authority_body_cited')),
            'top_cited_source_type': qsrc.get('top_cited_source_type', 'none'),
            'top_cited_domain': qsrc.get('top_cited_domain', ''),
            'citation_mix': qsrc.get('citation_mix', {}),
            **scored,
        })
    by_journey = defaultdict(list)
    for r in rows:
        by_journey[r.get('brand_topic_category') or 'Uncategorised'].append(r)
    brand_topic_summary = []
    for journey, js in by_journey.items():
        brand_topic_summary.append({
            'brand_topic_category': journey,
            'query_count': len(js),
            'avg_ai_visibility_score': round(mean([r['ai_visibility_score'] for r in js]), 1) if js else 0,
            'owned_target_page_citation_rate': round(sum(r['owned_target_page_cited'] for r in js) / max(1, len(js)), 3),
            'owned_domain_citation_rate': round(sum(r['owned_domain_cited'] for r in js) / max(1, len(js)), 3),
            'competitor_citation_rate': round(sum(r['competitor_cited'] for r in js) / max(1, len(js)), 3),
            'publisher_dependency_rate': round(sum(r['publisher_cited'] for r in js) / max(1, len(js)), 3),
            'aggregator_dependency_rate': round(sum(r['aggregator_cited'] for r in js) / max(1, len(js)), 3),
            'winner_status_mix': dict(Counter(r['visibility_status'] for r in js)),
        })
    aggregate = {
        'query_count': len(rows),
        'avg_ai_visibility_score': round(mean([r['ai_visibility_score'] for r in rows]), 1) if rows else 0,
        'owned_target_page_citation_rate': round(sum(r['owned_target_page_cited'] for r in rows) / max(1, len(rows)), 3),
        'owned_domain_citation_rate': round(sum(r['owned_domain_cited'] for r in rows) / max(1, len(rows)), 3),
        'external_dependency_rate': round(sum(r['visibility_status'] == 'external_led' for r in rows) / max(1, len(rows)), 3),
        'competitor_citation_rate': round(sum(r['competitor_cited'] for r in rows) / max(1, len(rows)), 3),
        'publisher_dependency_rate': round(sum(r['publisher_cited'] for r in rows) / max(1, len(rows)), 3),
        'aggregator_dependency_rate': round(sum(r['aggregator_cited'] for r in rows) / max(1, len(rows)), 3),
        'visibility_status_mix': dict(Counter(r['visibility_status'] for r in rows)),
    }
    write_json('outputs/visibility/ai_visibility_scores.json', {
        'schema_version': 'ai_visibility_scores_v1',
        'brand': cfg.get('brand'),
        'market': cfg.get('market'),
        'scoring_model': 'observed_google_ai_mode_visibility_v1',
        'component_weights': {
            'owned_page_citation': 35,
            'answer_prominence': 20,
            'citation_rank': 15,
            'sentiment_or_framing': 10,
            'competitor_displacement': 10,
            'source_control': 10,
        },
        'queries': rows,
        'brand_topic_summary': sorted(brand_topic_summary, key=lambda x: x['avg_ai_visibility_score']),
        'aggregate': aggregate,
    })
    print('Wrote outputs/visibility/ai_visibility_scores.json')


if __name__ == '__main__':
    main()
