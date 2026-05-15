from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Dict, List

from lib import get_config, read_json, write_json, normalize_url


def _score_external_pattern(row: Dict[str, Any]) -> Dict[str, Any]:
    features = row.get('feature_scores', {}) or {}
    dims = row.get('dimension_scores', {}) or {}
    def dim(name: str) -> int:
        v = dims.get(name, {})
        return int(v.get('score') or 0) if isinstance(v, dict) else 0
    query_answer_match = min(25, int(round((features.get('query_relevance', 0) / 5) * 25)))
    answer_packaging = min(15, int(round(((features.get('answer_first', 0) + features.get('extractable_passages', 0)) / 10) * 15)))
    evidence_and_proof = min(20, int(round(((features.get('specific_facts', 0) + features.get('statistics', 0) + features.get('source_citations', 0) + features.get('authority_signals', 0)) / 20) * 20)))
    comparison_utility = min(15, int(round((features.get('comparison_readiness', 0) / 5) * 15)))
    conversational_coverage = min(10, int(round((features.get('faq_readiness', 0) / 5) * 10)))
    machine_readability = min(10, int(round(((features.get('schema', 0) + features.get('accessibility', 0)) / 10) * 10)))
    freshness_and_market_relevance = min(5, int(round((features.get('freshness', 0) / 5) * 5)))
    total = sum([query_answer_match, answer_packaging, evidence_and_proof, comparison_utility, conversational_coverage, machine_readability, freshness_and_market_relevance])
    patterns = []
    if answer_packaging >= 10: patterns.append('answer_first_or_extractable_summary')
    if evidence_and_proof >= 14: patterns.append('specific_facts_and_proof')
    if comparison_utility >= 10: patterns.append('comparison_or_tradeoff_framing')
    if conversational_coverage >= 7: patterns.append('faq_or_conversational_coverage')
    if machine_readability >= 7: patterns.append('machine_readable_structure')
    return {
        'external_benchmark_score': total,
        'benchmark_dimension_scores': {
            'query_answer_match': query_answer_match,
            'answer_packaging': answer_packaging,
            'evidence_and_proof': evidence_and_proof,
            'comparison_utility': comparison_utility,
            'conversational_coverage': conversational_coverage,
            'machine_readability': machine_readability,
            'freshness_and_market_relevance': freshness_and_market_relevance,
        },
        'winning_patterns': patterns,
        'source_pattern_summary': ', '.join(patterns) if patterns else 'No strong reusable pattern detected from available evidence.',
    }


def main() -> None:
    cfg = get_config()
    external = read_json(cfg['paths']['external_readiness'], default={'source_analysis': []})
    rows = external.get('source_analysis') or external.get('page_analysis') or []
    scored = []
    for row in rows:
        if row.get('content_score_policy') == 'exclude_from_content_score' or row.get('readiness_score') is None:
            continue
        bench = _score_external_pattern(row)
        out = {k: v for k, v in row.items() if k not in {'extraction_manifest'}}
        out.update(bench)
        scored.append(out)
    by_type = defaultdict(list)
    by_journey = defaultdict(list)
    for r in scored:
        by_type[r.get('source_type') or r.get('source_category') or 'unknown'].append(r)
        by_journey[r.get('brand_topic_category') or 'Uncategorised'].append(r)
    out = {
        'schema_version': 'external_benchmark_scores_v1',
        'brand': cfg.get('brand'),
        'market': cfg.get('market'),
        'benchmark_framework': {
            'query_answer_match': 25,
            'answer_packaging': 15,
            'evidence_and_proof': 20,
            'comparison_utility': 15,
            'conversational_coverage': 10,
            'machine_readability': 10,
            'freshness_and_market_relevance': 5,
        },
        'sources_scored': len(scored),
        'source_patterns': scored,
        'aggregate': {
            'avg_external_benchmark_score': round(mean([r['external_benchmark_score'] for r in scored]), 1) if scored else 0,
            'pattern_mix': dict(Counter(p for r in scored for p in r.get('winning_patterns', []))),
            'source_type_avg_scores': {k: round(mean([r['external_benchmark_score'] for r in v]), 1) for k, v in by_type.items()},
            'journey_avg_scores': {k: round(mean([r['external_benchmark_score'] for r in v]), 1) for k, v in by_journey.items()},
        }
    }
    write_json('outputs/benchmark/winning_source_patterns.json', out)
    print('Wrote outputs/benchmark/winning_source_patterns.json')


if __name__ == '__main__':
    main()
