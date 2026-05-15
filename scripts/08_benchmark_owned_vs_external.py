from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any, Dict, List

from lib import get_config, get_weights, read_json, write_json, confidence_from_source_quality, dedupe_list

FEATURE_TO_RULE = {
    'answer_first': ('answer_first', 'Add a concise answer-first summary near the top of the page.'),
    'query_relevance': ('journey_coverage', 'Map the query to a more directly relevant owned page or create a dedicated section for this journey intent.'),
    'extractable_passages': ('content_structure', 'Break key information into self-contained passages with clear headings and lists.'),
    'specific_facts': ('evidence_quality', 'Add validated, query-relevant product facts, specifications and named examples.'),
    'statistics': ('quantified_facts', 'Add validated numeric evidence such as range, cost, capacity, timing or warranty figures.'),
    'source_citations': ('authority_trust', 'Support factual claims with credible source references or clearly attributed proof points.'),
    'comparison_readiness': ('comparison_readiness', 'Add comparison-ready guidance, trade-offs, tables or pros-and-cons blocks.'),
    'faq_readiness': ('faq', 'Add concise Q&A blocks matching conversational buyer questions.'),
    'schema': ('schema', 'Add or improve structured data where supported by visible page content.'),
    'freshness': ('freshness', 'Add visible freshness signals such as updated date, validity period or latest specification reference.'),
    'neutral_tone': ('neutral_tone', 'Reduce promotional language and use neutral, factual buyer guidance.'),
    'authority_signals': ('authority_trust', 'Add validated trust signals such as warranty, safety, service, expert or official proof.'),
    'accessibility': ('technical_accessibility', 'Ensure the page is accessible, text-rich and does not require interaction for core information.'),
}


def _find_by_url(items: List[Dict[str, Any]], url: str) -> Dict[str, Any] | None:
    return next((x for x in items if x.get('url') == url or x.get('resolved_url') == url), None)


def _median(values: List[float]) -> float:
    vals = [float(v) for v in values if v is not None]
    return round(float(median(vals)), 1) if vals else 0.0


def _median_feature_scores(items: List[Dict[str, Any]]) -> Dict[str, float]:
    keys = sorted({k for item in items for k in (item.get('feature_scores') or {}).keys()})
    return {k: _median([(item.get('feature_scores') or {}).get(k, 0) for item in items]) for k in keys}


def _median_dimension_scores(items: List[Dict[str, Any]]) -> Dict[str, float]:
    keys = sorted({k for item in items for k in (item.get('dimension_scores') or {}).keys()})
    return {k: _median([((item.get('dimension_scores') or {}).get(k) or {}).get('score', 0) for item in items]) for k in keys}


def _external_evidence_strength(external_items, score_delta, weights, mapping_quality):
    if not external_items:
        return 'none'
    thresholds = weights.get('thresholds', {})
    min_score = int(thresholds.get('external_win_min_score', 55))
    meaningful = int(thresholds.get('meaningful_gap_delta', 10))
    if mapping_quality == 'weak':
        return 'owned_mapping_gap'
    median_external = _median([x.get('readiness_score', 0) for x in external_items])
    if median_external < min_score:
        return 'weak'
    if score_delta >= meaningful:
        return 'strong'
    if score_delta > 0:
        return 'moderate'
    return 'weak'


def _page_card(page, selection_meta=None):
    selection_meta = selection_meta or {}
    return {
        'url': (page or {}).get('url') or selection_meta.get('url',''),
        'rank': selection_meta.get('rank'),
        'title': (page or {}).get('title','') or selection_meta.get('title',''),
        'source_name': (page or {}).get('source_name','') or selection_meta.get('source_name',''),
        'source_type': (page or {}).get('source_type','') or selection_meta.get('source_type',''),
        'source_quality': (page or {}).get('source_quality','not_available'),
        'overall_score': (page or {}).get('readiness_score', 0),
        'geo_score_120': (page or {}).get('geo_score_120', 0),
        'citation_likelihood': (page or {}).get('citation_likelihood',''),
        'feature_scores': (page or {}).get('feature_scores', {}),
        'dimension_scores': (page or {}).get('dimension_scores', {}),
        'word_count': (page or {}).get('word_count', 0),
        'snippet': selection_meta.get('snippet',''),
        'page_level_recommendations': (page or {}).get('page_level_recommendations', [])[:6],
        'critical_issues': (page or {}).get('critical_issues', [])[:5],
        'source_quality_notes': (page or {}).get('source_quality_notes', []),
    }


def main() -> None:
    cfg = get_config()
    weights = get_weights()
    feature_delta_threshold = 2
    scope = read_json(cfg['paths']['evidence_scope'])
    owned = read_json(cfg['paths']['owned_readiness']).get('page_analysis', [])
    external = read_json(cfg['paths']['external_readiness']).get('source_analysis', [])
    per_query = []
    pattern_counter = Counter()
    mapping_quality_counter = Counter()
    all_external_win_counts = Counter()

    for row in scope.get('queries', []):
        mapping_quality = row.get('mapping_quality', 'not_validated')
        mapping_quality_counter[mapping_quality] += 1
        owned_selection = row.get('owned_pages') or []
        external_selection = row.get('external_pages') or []
        owned_items = []
        external_items = []
        for sel in owned_selection:
            item = _find_by_url(owned, sel.get('url',''))
            if item:
                owned_items.append((item, sel))
        for sel in external_selection:
            item = _find_by_url(external, sel.get('url',''))
            if item:
                external_items.append((item, sel))

        owned_pages = [_page_card(item, sel) for item, sel in owned_items]
        external_pages = [_page_card(item, sel) for item, sel in external_items]
        owned_items_raw = [item for item, _ in owned_items]
        external_items_raw = [item for item, _ in external_items]

        owned_median = _median([p.get('overall_score', 0) for p in owned_pages])
        external_median = _median([p.get('overall_score', 0) for p in external_pages])
        owned_geo_median = _median([p.get('geo_score_120', 0) for p in owned_pages])
        external_geo_median = _median([p.get('geo_score_120', 0) for p in external_pages])
        score_delta = round(external_median - owned_median, 1)
        evidence_strength = _external_evidence_strength(external_items_raw, score_delta, weights, mapping_quality)
        meaningful_delta = int(weights.get('thresholds', {}).get('meaningful_gap_delta', 10))
        if not owned_pages or not external_pages:
            winner = 'not_validated'
        elif score_delta >= meaningful_delta and evidence_strength in {'strong', 'moderate'}:
            winner = 'external'
        elif score_delta <= -meaningful_delta:
            winner = 'owned'
        else:
            winner = 'mixed'

        owned_features = _median_feature_scores(owned_items_raw)
        ext_features = _median_feature_scores(external_items_raw)
        owned_dimensions = _median_dimension_scores(owned_items_raw)
        external_dimensions = _median_dimension_scores(external_items_raw)
        deltas = {k: round(ext_features.get(k, 0) - owned_features.get(k, 0), 1) for k in sorted(set(owned_features) | set(ext_features))}
        dimension_deltas = {k: round(external_dimensions.get(k, 0) - owned_dimensions.get(k, 0), 1) for k in sorted(set(owned_dimensions) | set(external_dimensions))}

        winning_patterns = []
        rule_candidates = []
        owned_gaps = []
        for feat, delta in sorted(deltas.items(), key=lambda kv: kv[1], reverse=True):
            if delta >= feature_delta_threshold:
                label, rule = FEATURE_TO_RULE.get(feat, ('content_structure', feat))
                if evidence_strength == 'owned_mapping_gap' and feat == 'query_relevance':
                    label, rule = ('journey_coverage', 'Improve query-to-page coverage by mapping or creating a more specific owned page for this intent.')
                pattern = f"External source set is stronger on {feat.replace('_',' ')}."
                if evidence_strength in {'strong', 'moderate'}:
                    winning_patterns.append(pattern)
                    pattern_counter[feat] += 1
                owned_gaps.append(rule)
                rule_candidates.append({'rule': rule, 'rule_type': label})
        if evidence_strength == 'owned_mapping_gap':
            owned_gaps.insert(0, 'Mapped owned pages include weak proxy matches for this query intent.')
            rule_candidates.insert(0, {'rule': 'Improve query-to-page coverage by mapping or creating a more specific owned page for this intent.', 'rule_type': 'journey_coverage'})

        benchmark_status_for_query = 'no_external_evidence'
        if external_pages:
            benchmark_status_for_query = {
                'strong': 'strong_external_evidence',
                'moderate': 'moderate_external_evidence',
                'weak': 'weak_external_evidence',
                'owned_mapping_gap': 'owned_mapping_gap'
            }.get(evidence_strength, 'weak_external_evidence')
        confidence = 'low'
        if owned_pages and external_pages:
            quality_mode = Counter([p.get('source_quality','medium') for p in external_pages]).most_common(1)[0][0]
            confidence = confidence_from_source_quality(quality_mode, True)
            if evidence_strength in {'weak','owned_mapping_gap'}:
                confidence = 'low' if quality_mode == 'low' else 'medium'

        primary_owned = owned_pages[0] if owned_pages else {}
        primary_external = external_pages[0] if external_pages else {}
        source_quality_notes = list({note for p in external_pages for note in p.get('source_quality_notes', [])})
        for p in external_pages:
            if p.get('source_type'):
                all_external_win_counts[p.get('source_type')] += 1

        per_query.append({
            'query': row.get('query',''),
            'query_type': row.get('query_type',''),
            'brand_topic_category': row.get('brand_topic_category',''),
            'mapped_owned_page': primary_owned.get('url',''),
            'mapped_owned_pages': [p.get('url','') for p in owned_pages],
            'mapping_quality': mapping_quality,
            'mapping_score': (row.get('owned_pages') or [{}])[0].get('mapping_score', 0),
            'benchmark_status_for_query': benchmark_status_for_query,
            'comparison_scope': {
                'owned_pages_compared': len(owned_pages),
                'external_pages_compared': len(external_pages),
                'target_owned_pages_per_query': int(cfg.get('max_owned_pages_per_query', 3)),
                'target_external_pages_per_query': int(cfg.get('max_external_pages_per_query', 3)),
            },
            'owned_pages': owned_pages,
            'external_sources': external_pages,
            'external_pages': external_pages,
            'median_owned_score': owned_median,
            'median_external_score': external_median,
            'median_score_gap': score_delta,
            'winner': winner,
            'median_scores': {
                'owned_median_readiness_score': owned_median,
                'external_median_readiness_score': external_median,
                'owned_median_geo_score_120': owned_geo_median,
                'external_median_geo_score_120': external_geo_median,
                'external_minus_owned_median_delta': score_delta,
            },
            # Backwards-compatible single-page fields for downstream scripts.
            'owned_page': {
                'url': primary_owned.get('url',''),
                'overall_score': primary_owned.get('overall_score', 0),
                'geo_score_120': primary_owned.get('geo_score_120', 0),
                'feature_scores': primary_owned.get('feature_scores', {}),
                'dimension_scores': primary_owned.get('dimension_scores', {}),
                'gaps': list(dict.fromkeys(owned_gaps))[:5],
                'page_level_recommendations': primary_owned.get('page_level_recommendations', [])[:6],
            },
            'external_source': {
                'url': primary_external.get('url') or None,
                'source_name': primary_external.get('source_name',''),
                'source_type': primary_external.get('source_type',''),
                'source_quality': primary_external.get('source_quality','not_available'),
                'overall_score': primary_external.get('overall_score', 0),
                'geo_score_120': primary_external.get('geo_score_120', 0),
                'feature_scores': primary_external.get('feature_scores', {}),
                'dimension_scores': primary_external.get('dimension_scores', {}),
                'strengths': winning_patterns[:5],
                'source_quality_notes': source_quality_notes,
                'snippet': primary_external.get('snippet',''),
            },
            'score_delta_external_minus_owned': score_delta,
            'gap_deltas': deltas,
            'dimension_deltas': dimension_deltas,
            'winning_patterns': winning_patterns[:6],
            'owned_gaps': list(dict.fromkeys(owned_gaps))[:6],
            'owned_page_recommendations': [
                {'url': p.get('url'), 'recommendations': p.get('page_level_recommendations', [])[:5], 'critical_issues': p.get('critical_issues', [])[:4]}
                for p in owned_pages
            ],
            'recommended_rule_candidates': list({rc['rule']: rc for rc in rule_candidates}.values())[:6],
            'evidence_strength': evidence_strength,
            'confidence': confidence,
            'source_quality_notes': source_quality_notes
        })

    out = {
        'benchmark_status': 'success' if per_query else 'failed',
        'comparison_scope': f"{cfg.get('max_owned_pages_per_query', 3)} owned x {cfg.get('max_external_pages_per_query', 3)} external",
        'scoring_framework': 'GEO / AI Source Readiness Framework, six dimensions x 20 = 120; median comparison uses 0..100 readiness score for compatibility.',
        'per_query': per_query,
        'aggregate': {
            'queries_compared': len(per_query),
            'queries_with_3_owned_pages': sum(1 for x in per_query if x.get('comparison_scope', {}).get('owned_pages_compared', 0) >= 3),
            'queries_with_3_external_pages': sum(1 for x in per_query if x.get('comparison_scope', {}).get('external_pages_compared', 0) >= 3),
            'strong_external_evidence_count': sum(1 for x in per_query if x.get('evidence_strength') == 'strong'),
            'moderate_external_evidence_count': sum(1 for x in per_query if x.get('evidence_strength') == 'moderate'),
            'weak_external_evidence_count': sum(1 for x in per_query if x.get('evidence_strength') == 'weak'),
            'owned_mapping_gap_count': sum(1 for x in per_query if x.get('evidence_strength') == 'owned_mapping_gap'),
            'external_wins_count': sum(1 for x in per_query if x['score_delta_external_minus_owned'] > 0 and x.get('evidence_strength') in {'strong','moderate'}),
            'owned_wins_count': sum(1 for x in per_query if x['score_delta_external_minus_owned'] < 0),
            'mapping_quality_mix': dict(mapping_quality_counter),
            'recurring_winning_patterns': pattern_counter.most_common(12),
            'dominant_external_source_types': all_external_win_counts.most_common(12),
            'median_owned_score_avg': round(sum(x['median_scores']['owned_median_readiness_score'] for x in per_query) / len(per_query), 1) if per_query else 0,
            'median_external_score_avg': round(sum(x['median_scores']['external_median_readiness_score'] for x in per_query) / len(per_query), 1) if per_query else 0,
            'summary': 'Owned page sets were benchmarked against external source sets for each query using median scores. Individual page scores and page-level recommendations are preserved.'
        }
    }
    write_json(cfg['paths']['source_preference_benchmark'], out)
    print(f"Wrote {cfg['paths']['source_preference_benchmark']}")


if __name__ == '__main__':
    main()
