from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from lib import get_config, get_weights, read_json, write_json


MAX_TEXT = 500
MAX_SHORT_TEXT = 240
MAX_LIST_ITEMS = 10
MAX_EXAMPLES = 12
MAX_BACKLOG_ITEMS = 20


def _clip(value: object, limit: int = MAX_TEXT) -> str:
    text = '' if value is None else str(value)
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


def _compact_list(values, limit: int = MAX_LIST_ITEMS):
    if not isinstance(values, list):
        return []
    return values[:limit]


def _count_mix(rows, key: str) -> dict:
    c = Counter()
    for row in rows or []:
        value = row.get(key)
        if isinstance(value, list):
            c.update([v for v in value if v])
        elif value:
            c[value] += 1
    return dict(c)


def _owned_summary(owned: dict) -> dict:
    pages = owned.get('page_analysis', [])
    gaps = Counter()
    for p in pages:
        fs = p.get('feature_scores', {})
        for k, v in fs.items():
            if isinstance(v, (int, float)) and v <= 2:
                gaps[k] += 1
    mapping_mix = Counter()
    for p in pages:
        for k, v in (p.get('mapping_quality_mix') or {}).items():
            mapping_mix[k] += v
    lowest = []
    def score_value(row: dict) -> float:
        value = row.get('readiness_score')
        if value is None:
            value = row.get('overall_score', 0)
        return value or 0

    for p in sorted(pages, key=score_value)[:10]:
        lowest.append({
            'url': p.get('url', ''),
            'brand_topic_category': p.get('brand_topic_category', ''),
            'page_type': p.get('page_type', ''),
            'readiness_score': p.get('readiness_score', p.get('overall_score', 0)),
            'geo_score_120': p.get('geo_score_120', 0),
            'critical_issues': _compact_list(p.get('critical_issues', []), 3),
        })
    return {
        'owned_readiness_status': owned.get('owned_readiness_status'),
        'pages_received': owned.get('pages_received', len(pages)),
        'pages_scored': owned.get('pages_scored', len(pages)),
        'avg_readiness_score': owned.get('aggregate', {}).get('avg_readiness_score', 0),
        'avg_geo_score_120': owned.get('aggregate', {}).get('avg_geo_score_120', 0),
        'lowest_scoring_pages': lowest,
        'top_owned_gaps': [{'gap': k, 'count': v} for k, v in gaps.most_common(10)],
        'brand_topic_summary': owned.get('aggregate', {}).get('brand_topic_summary', []),
        'mapping_quality_mix': dict(mapping_mix),
    }


def _external_summary(external: dict) -> dict:
    sources = external.get('source_analysis', [])
    source_type_mix = Counter()
    source_quality_mix = Counter()
    for src in sources:
        if src.get('source_type'):
            source_type_mix[src.get('source_type')] += 1
        if src.get('source_quality'):
            source_quality_mix[src.get('source_quality')] += 1
    top_sources = []
    def score_value(row: dict) -> float:
        value = row.get('readiness_score')
        if value is None:
            value = row.get('overall_score', 0)
        return value or 0

    for src in sorted(sources, key=score_value, reverse=True)[:10]:
        top_sources.append({
            'url': src.get('url', ''),
            'source_name': src.get('source_name', ''),
            'source_type': src.get('source_type', ''),
            'source_quality': src.get('source_quality', ''),
            'readiness_score': src.get('readiness_score', src.get('overall_score', 0)),
            'geo_score_120': src.get('geo_score_120', 0),
        })
    return {
        'external_readiness_status': external.get('external_readiness_status'),
        'sources_received': external.get('sources_received', len(sources)),
        'sources_scored': external.get('sources_scored', len(sources)),
        'avg_external_score': external.get('aggregate', {}).get('avg_readiness_score', 0),
        'avg_geo_score_120': external.get('aggregate', {}).get('avg_geo_score_120', 0),
        'source_type_mix': dict(source_type_mix),
        'source_quality_mix': dict(source_quality_mix),
        'top_external_sources': top_sources,
        'top_external_source_types': external.get('aggregate', {}).get('top_external_source_types', []),
        'low_quality_source_count': external.get('aggregate', {}).get('low_quality_source_count', 0),
        'off_market_source_count': external.get('aggregate', {}).get('off_market_source_count', 0),
        'social_or_forum_source_count': external.get('aggregate', {}).get('social_or_forum_source_count', 0),
        'failed_or_unusable_sources': external.get('aggregate', {}).get('failed_or_unusable_sources', 0),
    }


def _audit_scope_summary(audit: dict) -> dict:
    queries = audit.get('queries', [])
    pages = audit.get('pages', [])
    return {
        'brand': audit.get('brand'),
        'market': audit.get('market'),
        'domain': audit.get('domain'),
        'vertical': audit.get('vertical'),
        'query_portfolio_id': audit.get('query_portfolio_id'),
        'scope_multiplier': audit.get('scope_multiplier'),
        'query_count': len(queries),
        'owned_url_count': len(pages),
        'query_type_mix': _count_mix(queries, 'query_type'),
        'brand_topic_category_mix': _count_mix(queries, 'brand_topic_category'),
        'commercial_value_mix': _count_mix(queries, 'commercial_value'),
        'priority_mix': _count_mix(queries, 'priority'),
        'mapping_quality_mix': audit.get('summary', {}).get('mapping_quality_mix', _count_mix(queries, 'mapping_quality')),
        'query_mapped_page_count': audit.get('summary', {}).get('query_mapped_page_count'),
        'max_owned_pages_per_query': audit.get('summary', {}).get('max_owned_pages_per_query', audit.get('scope_multiplier')),
    }


def _compact_queries(audit: dict) -> list[dict]:
    result = []
    for idx, q in enumerate(audit.get('queries', []), start=1):
        result.append({
            'query_id': f'q{idx:03d}',
            'query': q.get('query', ''),
            'query_type': q.get('query_type', ''),
            'brand_topic_category': q.get('brand_topic_category', ''),
            'intent_type': q.get('intent_type', ''),
            'answer_type': q.get('answer_type', ''),
            'commercial_value': q.get('commercial_value', ''),
            'priority': q.get('priority', ''),
            'owned_page_urls': q.get('mapped_pages', [])[:3],
            'mapping_score': q.get('mapping_score', 0),
            'mapping_quality': q.get('mapping_quality', ''),
        })
    return result


def _visibility_summary(visibility: dict) -> dict:
    rows = visibility.get('rows', [])
    brand_topic_summary = defaultdict(lambda: {
        'queries': 0,
        'owned_page_cited_count': 0,
        'owned_domain_cited_count': 0,
        'external_source_count': 0,
    })
    source_type_mix = Counter()
    source_quality_mix = Counter()
    for row in rows:
        j = row.get('brand_topic_category', '') or 'Uncategorised'
        brand_topic_summary[j]['queries'] += 1
        if row.get('owned_page_cited'):
            brand_topic_summary[j]['owned_page_cited_count'] += 1
        if row.get('owned_domain_cited'):
            brand_topic_summary[j]['owned_domain_cited_count'] += 1
        sources = row.get('external_sources') or []
        brand_topic_summary[j]['external_source_count'] += len(sources)
        for src in sources:
            if src.get('source_type'):
                source_type_mix[src.get('source_type')] += 1
            if src.get('source_quality'):
                source_quality_mix[src.get('source_quality')] += 1
    return {
        'visibility_matrix_status': visibility.get('visibility_matrix_status'),
        'max_external_references_per_query': visibility.get('max_external_references_per_query'),
        'query_count': len(rows),
        'owned_page_cited_count': visibility.get('aggregate', {}).get('owned_page_cited_count', 0),
        'owned_domain_cited_count': visibility.get('aggregate', {}).get('owned_domain_cited_count', 0),
        'total_external_references': visibility.get('aggregate', {}).get('total_external_references', 0),
        'source_type_mix': dict(source_type_mix),
        'source_quality_mix': dict(source_quality_mix),
        'visibility_by_journey': [{'brand_topic_category': k, **v} for k, v in brand_topic_summary.items()],
    }


def _source_landscape_summary(external: dict, visibility: dict) -> dict:
    source_type_mix = Counter()
    source_quality_mix = Counter()
    named_sources = Counter()
    for src in external.get('source_analysis', []):
        if src.get('source_type'):
            source_type_mix[src.get('source_type')] += 1
        if src.get('source_quality'):
            source_quality_mix[src.get('source_quality')] += 1
        name = src.get('source_name') or src.get('title') or src.get('url')
        if name:
            named_sources[name] += 1
    # visibility can include references that failed crawl, keep them in the source view
    for row in visibility.get('rows', []):
        for src in row.get('external_sources', []) or []:
            if src.get('source_type'):
                source_type_mix[src.get('source_type')] += 0
            name = src.get('source_name') or src.get('title') or src.get('url')
            if name:
                named_sources[name] += 0
    return {
        'dominant_source_types': [{'source_type': k, 'count': v} for k, v in source_type_mix.most_common(12)],
        'source_quality_mix': dict(source_quality_mix),
        'dominant_sources': [{'source': k, 'count': v} for k, v in named_sources.most_common(12)],
        'publisher_dependency_patterns': external.get('aggregate', {}).get('publisher_dependency_patterns', []),
    }


def _compact_benchmark(benchmark: dict) -> dict:
    rows = benchmark.get('per_query', [])
    winner_distribution = Counter(r.get('winner', 'missing') for r in rows)
    evidence_strength_distribution = Counter(r.get('evidence_strength', r.get('evidence_quality', 'missing')) for r in rows)
    gaps = [r.get('median_score_gap') for r in rows if isinstance(r.get('median_score_gap'), (int, float))]
    brand_topic_summary = defaultdict(lambda: {
        'queries': 0,
        'external_wins': 0,
        'owned_wins': 0,
        'mixed': 0,
        'not_validated': 0,
        'avg_median_score_gap': 0,
        '_gaps': [],
    })
    for row in rows:
        j = row.get('brand_topic_category', '') or 'Uncategorised'
        brand_topic_summary[j]['queries'] += 1
        winner = row.get('winner', 'not_validated')
        if winner in brand_topic_summary[j]:
            brand_topic_summary[j][winner] += 1
        elif winner == 'external':
            brand_topic_summary[j]['external_wins'] += 1
        elif winner == 'owned':
            brand_topic_summary[j]['owned_wins'] += 1
        gap = row.get('median_score_gap')
        if isinstance(gap, (int, float)):
            brand_topic_summary[j]['_gaps'].append(gap)
    clean_journey = []
    for j, data in brand_topic_summary.items():
        gap_values = data.pop('_gaps')
        data['avg_median_score_gap'] = round(mean(gap_values), 1) if gap_values else 0
        clean_journey.append({'brand_topic_category': j, **data})

    def compact_row(row: dict) -> dict:
        return {
            'query': row.get('query', ''),
            'query_type': row.get('query_type', ''),
            'brand_topic_category': row.get('brand_topic_category', ''),
            'mapping_quality': row.get('mapping_quality', ''),
            'evidence_strength': row.get('evidence_strength', ''),
            'confidence': row.get('confidence', ''),
            'median_owned_score': row.get('median_owned_score', 0),
            'median_external_score': row.get('median_external_score', 0),
            'median_score_gap': row.get('median_score_gap', 0),
            'winner': row.get('winner', 'not_validated'),
            'owned_pages': [
                {
                    'url': p.get('url', ''),
                    'title': p.get('title', ''),
                    'score': p.get('readiness_score', p.get('overall_score', 0)),
                    'geo_score_120': p.get('geo_score_120', 0),
                }
                for p in (row.get('owned_pages') or [])[:3]
            ],
            'external_sources': [
                {
                    'url': p.get('url', ''),
                    'title': p.get('title', ''),
                    'source_type': p.get('source_type', ''),
                    'source_quality': p.get('source_quality', ''),
                    'score': p.get('readiness_score', p.get('overall_score', 0)),
                    'snippet': _clip(p.get('snippet', ''), MAX_SHORT_TEXT),
                }
                for p in (row.get('external_sources') or row.get('external_pages') or [])[:3]
            ],
            'owned_gaps': _compact_list(row.get('owned_gaps', []), 6),
            'winning_patterns': _compact_list(row.get('winning_patterns', []), 6),
            'recommended_rule_candidates': _compact_list(row.get('recommended_rule_candidates', []), 3),
        }

    external_gap_examples = sorted(rows, key=lambda r: r.get('median_score_gap', -999), reverse=True)[:MAX_EXAMPLES]
    recoverable_examples = sorted(
        [r for r in rows if r.get('winner') in {'mixed', 'external'} and isinstance(r.get('median_score_gap'), (int, float)) and r.get('median_score_gap') <= 25],
        key=lambda r: abs(r.get('median_score_gap', 999)),
    )[:MAX_EXAMPLES]
    owned_win_examples = sorted(rows, key=lambda r: r.get('median_score_gap', 999))[:5]
    return {
        'benchmark_status': benchmark.get('benchmark_status'),
        'comparison_scope': benchmark.get('comparison_scope', {}),
        'query_count': len(rows),
        'winner_distribution': dict(winner_distribution),
        'evidence_strength_distribution': dict(evidence_strength_distribution),
        'median_gap_summary': {
            'rows': len(gaps),
            'avg_gap': round(mean(gaps), 1) if gaps else 0,
            'min_gap': min(gaps) if gaps else 0,
            'max_gap': max(gaps) if gaps else 0,
        },
        'journey_gap_summary': clean_journey,
        'recurring_winning_patterns': benchmark.get('aggregate', {}).get('recurring_winning_patterns', []),
        'recurring_owned_gaps': benchmark.get('aggregate', {}).get('recurring_owned_gaps', []),
        'top_external_gap_examples': [compact_row(r) for r in external_gap_examples],
        'top_recoverable_examples': [compact_row(r) for r in recoverable_examples],
        'owned_win_examples': [compact_row(r) for r in owned_win_examples],
    }


def _compact_rules(rules: dict) -> dict:
    return {
        'preference_rule_status': rules.get('preference_rule_status'),
        'cross_journey_rules': _compact_list(rules.get('cross_journey_rules', []), 10),
        'rules_by_brand_topic_category': [
            {
                'brand_topic_category': row.get('brand_topic_category', ''),
                'rules': _compact_list(row.get('rules', []), 6),
            }
            for row in (rules.get('rules_by_brand_topic_category', []) or [])[:10]
        ],
        'rules_to_avoid': _compact_list(rules.get('rules_to_avoid', []), 6),
        'aggregate': rules.get('aggregate', {}),
    }


def _compact_backlog(backlog: dict) -> dict:
    return {
        'prioritisation_status': backlog.get('prioritisation_status'),
        'priority_backlog': _compact_list(backlog.get('priority_backlog', []), MAX_BACKLOG_ITEMS),
        'journey_level_priorities': _compact_list(backlog.get('journey_level_priorities', []), 10),
        'aggregate': backlog.get('aggregate', {}),
    }


def _dashboard_dataset(audit: dict, visibility: dict, owned: dict, external: dict, benchmark: dict, backlog: dict, rules: dict, final_summary: dict | None = None) -> dict:
    """Create one frontend-ready dataset so the dashboard does not need to join many files."""
    owned_pages = owned.get('page_analysis', [])
    external_pages = external.get('source_analysis', [])
    query_rows = []
    owned_vs_external_examples = []
    for row in benchmark.get('per_query', []):
        median_owned = row.get('median_owned_score', row.get('median_scores', {}).get('owned_median_readiness_score', 0))
        median_external = row.get('median_external_score', row.get('median_scores', {}).get('external_median_readiness_score', 0))
        median_gap = row.get('median_score_gap', row.get('score_delta_external_minus_owned', 0))
        query_rows.append({
            'query': row.get('query',''),
            'query_type': row.get('query_type',''),
            'brand_topic_category': row.get('brand_topic_category',''),
            'mapping_quality': row.get('mapping_quality',''),
            'evidence_strength': row.get('evidence_strength',''),
            'confidence': row.get('confidence',''),
            'median_owned_score': median_owned,
            'median_external_score': median_external,
            'median_score_gap': median_gap,
            'winner': row.get('winner', 'not_validated'),
            'median_scores': row.get('median_scores', {}),
            'score_delta_external_minus_owned': row.get('score_delta_external_minus_owned', 0),
            'owned_pages': row.get('owned_pages', []),
            'external_sources': row.get('external_sources', []),
            'owned_gaps': row.get('owned_gaps', []),
            'winning_patterns': row.get('winning_patterns', []),
            'owned_page_recommendations': row.get('owned_page_recommendations', []),
            'recommended_rule_candidates': row.get('recommended_rule_candidates', []),
        })
        owned_cards = []
        for p in (row.get('owned_pages') or [])[:3]:
            recs = p.get('page_level_recommendations', [])[:5]
            issues = p.get('critical_issues', [])[:5]
            owned_cards.append({
                'url': p.get('url',''),
                'title': p.get('title',''),
                'score': p.get('overall_score', p.get('readiness_score', 0)),
                'geo_score_120': p.get('geo_score_120', 0),
                'missing_elements': [i.get('issue', str(i)) if isinstance(i, dict) else str(i) for i in issues],
                'recommendations': recs,
            })
        external_cards = []
        for p in (row.get('external_sources') or row.get('external_pages') or [])[:3]:
            external_cards.append({
                'url': p.get('url',''),
                'title': p.get('title',''),
                'score': p.get('overall_score', p.get('readiness_score', 0)),
                'geo_score_120': p.get('geo_score_120', 0),
                'source_type': p.get('source_type',''),
                'source_quality': p.get('source_quality',''),
                'excerpt': _clip(p.get('snippet',''), MAX_SHORT_TEXT),
            })
        why_external = '; '.join(row.get('winning_patterns', [])[:3])
        why_owned = 'Owned page set has stronger median readiness score.' if row.get('winner') == 'owned' else ''
        recommended = ''
        candidates = row.get('recommended_rule_candidates', [])
        if candidates:
            first = candidates[0]
            recommended = first.get('rule', '') if isinstance(first, dict) else str(first)
        owned_vs_external_examples.append({
            'query': row.get('query',''),
            'query_type': row.get('query_type',''),
            'brand_topic_category': row.get('brand_topic_category',''),
            'owned_pages': owned_cards,
            'external_pages': external_cards,
            'median_owned_score': median_owned,
            'median_external_score': median_external,
            'median_score_gap': median_gap,
            'winner': row.get('winner', 'not_validated'),
            'why_external_wins': why_external if row.get('winner') == 'external' else '',
            'why_owned_wins': why_owned,
            'recommended_action': recommended,
            'evidence_quality': {
                'mapping_quality': row.get('mapping_quality',''),
                'evidence_strength': row.get('evidence_strength',''),
                'confidence': row.get('confidence',''),
                'source_quality_notes': row.get('source_quality_notes', []),
            }
        })
    examples = sorted(
        [q for q in query_rows if q.get('median_scores') or isinstance(q.get('median_score_gap'), (int, float))],
        key=lambda x: x.get('median_score_gap', x.get('score_delta_external_minus_owned', 0)),
        reverse=True,
    )
    page_level_recommendations = []
    for p in owned_pages:
        for rec in p.get('page_level_recommendations', [])[:6]:
            page_level_recommendations.append({
                'url': p.get('url',''),
                'title': p.get('title',''),
                'brand_topic_category': p.get('brand_topic_category',''),
                'page_type': p.get('page_type',''),
                'score': p.get('readiness_score', 0),
                'geo_score_120': p.get('geo_score_120', 0),
                'recommendation': rec,
            })
    framework = get_weights().get('framework', {})
    return {
        'dataset_schema_version': 'ai_visibility_dashboard_v3',
        'metadata': {
            'brand': audit.get('brand'),
            'market': audit.get('market'),
            'domain': audit.get('domain'),
            'query_portfolio_id': audit.get('query_portfolio_id'),
            'scoring_framework': framework.get('name', 'GEO / AI Source Readiness Framework'),
        },
        'brand': audit.get('brand'),
        'market': audit.get('market'),
        'domain': audit.get('domain'),
        'executive_kpis': {
            'queries': len(audit.get('queries', [])),
            'owned_urls': len(audit.get('pages', [])),
            'owned_page_cited_count': visibility.get('aggregate', {}).get('owned_page_cited_count', 0),
            'owned_domain_cited_count': visibility.get('aggregate', {}).get('owned_domain_cited_count', 0),
            'total_external_references': visibility.get('aggregate', {}).get('total_external_references', 0),
            'owned_avg_readiness_score': owned.get('aggregate', {}).get('avg_readiness_score', 0),
            'owned_avg_geo_score_120': owned.get('aggregate', {}).get('avg_geo_score_120', 0),
            'external_avg_readiness_score': external.get('aggregate', {}).get('avg_readiness_score', 0),
            'external_avg_geo_score_120': external.get('aggregate', {}).get('avg_geo_score_120', 0),
            'median_owned_score_avg': benchmark.get('aggregate', {}).get('median_owned_score_avg', 0),
            'median_external_score_avg': benchmark.get('aggregate', {}).get('median_external_score_avg', 0),
            'external_wins_count': benchmark.get('aggregate', {}).get('external_wins_count', 0),
            'owned_wins_count': benchmark.get('aggregate', {}).get('owned_wins_count', 0),
        },
        'brand_topic_summary': owned.get('aggregate', {}).get('brand_topic_summary', []),
        'journeys': owned.get('aggregate', {}).get('brand_topic_summary', []),
        'query_rows': query_rows,
        'queries': query_rows,
        'top_external_gap_examples': examples[:10],
        'top_recoverable_examples': sorted([q for q in query_rows if isinstance(q.get('median_score_gap'), (int, float)) and q.get('median_score_gap', 999) > 0], key=lambda x: x.get('median_score_gap', 0))[:10],
        'owned_pages': [{k: p.get(k) for k in ['url','page_type','brand_topic_category','readiness_score','geo_score_120','citation_likelihood','dimension_scores','page_level_recommendations','critical_issues','mapped_queries']} for p in owned_pages],
        'external_sources': [{k: p.get(k) for k in ['url','source_name','source_type','source_quality','readiness_score','geo_score_120','citation_likelihood','dimension_scores','source_quality_notes']} for p in external_pages],
        'owned_vs_external_examples': owned_vs_external_examples,
        'action_backlog': backlog.get('priority_backlog', []),
        'actions': backlog.get('priority_backlog', []),
        'page_level_recommendations': page_level_recommendations,
        'scoring_framework': get_weights().get('framework', {}),
        'preference_rules': rules,
        'evidence_quality': {},
        'caveats': [
            'Dashboard rows use available local evidence; top-three external sources require successful SerpAPI collection.',
            'Weak mappings should be treated as coverage gaps before page-content conclusions are made.',
        ],
    }


def _evidence_quality(audit: dict, visibility: dict, owned: dict, external: dict, site_standards: dict) -> dict:
    return {
        'observed_queries': visibility.get('aggregate', {}).get('queries', len(visibility.get('rows', []))),
        'owned_pages_scored': owned.get('pages_scored', len(owned.get('page_analysis', []))),
        'external_pages_scored': external.get('sources_scored', len(external.get('source_analysis', []))),
        'external_sources_failed': external.get('aggregate', {}).get('failed_or_unusable_sources', 0),
        'owned_page_cited_count': visibility.get('aggregate', {}).get('owned_page_cited_count', 0),
        'owned_domain_cited_count': visibility.get('aggregate', {}).get('owned_domain_cited_count', 0),
        'off_market_source_count': external.get('aggregate', {}).get('off_market_source_count', 0),
        'social_or_forum_source_count': external.get('aggregate', {}).get('social_or_forum_source_count', 0),
        'low_quality_external_source_count': external.get('aggregate', {}).get('low_quality_source_count', 0),
        'mapping_quality_mix': audit.get('summary', {}).get('mapping_quality_mix', {}),
        'site_standards': {
            'robots_txt_available': site_standards.get('signals', {}).get('robots_available'),
            'llms_txt_available': site_standards.get('signals', {}).get('llms_txt_available'),
            'robots_mentions_sitemap': site_standards.get('signals', {}).get('robots_mentions_sitemap'),
            'robots_blocks_common_ai_agents': site_standards.get('signals', {}).get('robots_blocks_common_ai_agents'),
            'json_ld_checked_from_page_markdown': True,
        },
        'known_limitations': [
            'Google AI Mode is the only observed citation evidence in this pilot.',
            'Some external cited sources may be off-market, social/forum, low-authority or inaccessible; these are down-weighted, not discarded.',
            'Existing SerpAPI outputs and free-hybrid local crawl outputs may be reused unless force-refetch flags are enabled. Firecrawl-era markdown is archived for reference only and is not used by the active crawler.',
            'Expanded scope targets up to three mapped owned pages and three AI-cited external sources per query.',
            'Weak mapping-quality rows should be treated as coverage gaps, not as definitive page-level content failures.',
        ],
    }


def _reporting_caveats() -> list[str]:
    return [
        'Some query-to-owned-page mappings are best-available proxy matches. Use mapping_quality before making page-specific recommendations.',
        'Owned-domain citation and owned-page citation are reported separately; domain-level presence does not mean the target page was cited.',
        'Low-quality, social/forum, off-market and weakly crawled external sources are retained as signals but should not be used as proof points without validation.',
        'robots.txt and llms.txt are checked as domain-level standards signals; JSON-LD is checked where visible in crawled page markdown.',
    ]


def _make_compact_bundle(audit: dict, visibility: dict, owned: dict, external: dict, benchmark: dict, rules: dict, backlog: dict, site_standards: dict) -> dict:
    return {
        'bundle_schema_version': 'ai_visibility_local_v3_bodhi_compact',
        'metadata': {
            'brand': audit.get('brand'),
            'market': audit.get('market'),
            'domain': audit.get('domain'),
            'vertical': audit.get('vertical'),
            'query_portfolio_id': audit.get('query_portfolio_id'),
            'scope_multiplier': audit.get('scope_multiplier'),
            'query_count': len(audit.get('queries', [])),
            'owned_url_count': len(audit.get('pages', [])),
            'scoring_framework': get_weights().get('framework', {}).get('name', 'GEO / AI Source Readiness Framework'),
        },
        'audit_scope_summary': _audit_scope_summary(audit),
        'queries': _compact_queries(audit),
        'visibility_summary': _visibility_summary(visibility),
        'owned_readiness_summary': _owned_summary(owned),
        'external_readiness_summary': _external_summary(external),
        'source_landscape_summary': _source_landscape_summary(external, visibility),
        'benchmark_summary': _compact_benchmark(benchmark),
        'preference_rules': _compact_rules(rules),
        'improvement_backlog': _compact_backlog(backlog),
        'scoring_framework': get_weights().get('framework', {}),
        'evidence_quality': _evidence_quality(audit, visibility, owned, external, site_standards),
        'reporting_caveats': _reporting_caveats(),
    }


def _make_full_bundle(audit: dict, visibility: dict, scope: dict, owned: dict, external: dict, benchmark: dict, rules: dict, backlog: dict, dashboard_dataset: dict, site_standards: dict) -> dict:
    return {
        'bundle_schema_version': 'ai_visibility_local_v3_full',
        'audit_context': audit,
        'visibility_matrix': visibility,
        'evidence_scope': scope,
        'owned_readiness': owned,
        'external_readiness': external,
        'source_preference_benchmark': benchmark,
        'dashboard_dataset': dashboard_dataset,
        'preference_rules': rules,
        'improvement_backlog': backlog,
        'evidence_quality': _evidence_quality(audit, visibility, owned, external, site_standards),
        'reporting_caveats': _reporting_caveats(),
    }


def _sibling_path(path_value: str, filename: str) -> str:
    return str(Path(path_value).parent / filename)


def main() -> None:
    cfg = get_config()
    audit = read_json(cfg['paths']['audit_context_output'])
    visibility = read_json(cfg['paths']['visibility_matrix'])
    scope = read_json(cfg['paths']['evidence_scope'])
    owned = read_json(cfg['paths']['owned_readiness'])
    external = read_json(cfg['paths']['external_readiness'])
    benchmark = read_json(cfg['paths']['source_preference_benchmark'])
    rules = read_json(cfg['paths']['preference_rules'])
    backlog = read_json(cfg['paths']['improvement_backlog'])
    standards_path = cfg['paths'].get('site_standards')
    site_standards = read_json(standards_path, default={}) if standards_path else {}

    dashboard_dataset = _dashboard_dataset(audit, visibility, owned, external, benchmark, backlog, rules)
    compact_bundle = _make_compact_bundle(audit, visibility, owned, external, benchmark, rules, backlog, site_standards)
    full_bundle = _make_full_bundle(audit, visibility, scope, owned, external, benchmark, rules, backlog, dashboard_dataset, site_standards)

    if cfg['paths'].get('dashboard_dataset'):
        write_json(cfg['paths']['dashboard_dataset'], dashboard_dataset)

    bodhi_path = cfg['paths']['bodhi_bundle']
    compact_path = cfg['paths'].get('bodhi_bundle_compact') or _sibling_path(bodhi_path, 'bodhi_input_bundle_compact.json')
    full_path = cfg['paths'].get('bodhi_bundle_full') or _sibling_path(bodhi_path, 'bodhi_input_bundle_full.json')

    write_json(full_path, full_bundle)
    write_json(compact_path, compact_bundle)

    # Backwards compatibility: existing workflow scripts still look for paths.bodhi_bundle.
    # Make the legacy output path the compact Bodhi bundle to prevent oversized uploads.
    write_json(bodhi_path, compact_bundle)

    print(f"Wrote compact Bodhi bundle: {compact_path}")
    print(f"Wrote full evidence bundle: {full_path}")
    print(f"Wrote legacy Bodhi bundle path as compact: {bodhi_path}")
    if cfg['paths'].get('dashboard_dataset'):
        print(f"Wrote dashboard dataset: {cfg['paths']['dashboard_dataset']}")


if __name__ == '__main__':
    main()
