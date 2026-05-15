from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict

from lib import get_config, read_json, write_json


def _opportunity_type(source_mix: Counter) -> str:
    if source_mix.get('authority_body', 0) or source_mix.get('partner_infrastructure', 0):
        return 'authority_source'
    if source_mix.get('publisher_review', 0):
        return 'comparison_narrative'
    if source_mix.get('forum_social_video', 0):
        return 'community_trust'
    if source_mix.get('competitor_owned', 0):
        return 'competitive_counter_positioning'
    if source_mix.get('aggregator_marketplace', 0):
        return 'structured_comparison_distribution'
    return 'publisher_education'


def _summary(journey: str, opp_type: str, top_types: list[str]) -> str:
    if opp_type == 'authority_source':
        return f'Partner with credible Japan-relevant authorities or infrastructure sources to publish validated explainers and datasets for {journey}.'
    if opp_type == 'comparison_narrative':
        return f'Develop neutral, data-backed comparison narratives with respected automotive or consumer publishers for {journey}.'
    if opp_type == 'community_trust':
        return f'Create official explainers and Q&A assets that address the community concerns currently being answered by social/forum sources for {journey}.'
    if opp_type == 'competitive_counter_positioning':
        return f'Create third-party supported proof and comparison content to reduce competitor-led answer construction for {journey}.'
    if opp_type == 'structured_comparison_distribution':
        return f'Work with comparison and marketplace-style partners to distribute structured, validated Nissan facts for {journey}.'
    return f'Build publisher education assets and source packs for {journey}.'


def main() -> None:
    cfg = get_config()
    src = read_json('outputs/source_landscape/source_classification.json', default={'sources': []})
    gap = read_json('outputs/benchmark/owned_vs_external_gap_analysis.json', default={'per_query': []})
    by_journey = defaultdict(Counter)
    domains = defaultdict(Counter)
    for s in src.get('sources', []):
        j = s.get('brand_topic_category') or 'Uncategorised'
        by_journey[j][s.get('source_category') or 'low_quality_unknown'] += 1
        domains[j][s.get('source_domain') or ''] += 1
    gap_by_journey = defaultdict(list)
    for q in gap.get('per_query', []):
        gap_by_journey[q.get('brand_topic_category') or 'Uncategorised'].append(q.get('source_preference_gap', 0))
    opportunities = []
    for journey, mix in by_journey.items():
        opp = _opportunity_type(mix)
        avg_gap = sum(gap_by_journey.get(journey, [0])) / max(1, len(gap_by_journey.get(journey, [])))
        priority = 'P1' if avg_gap >= 10 or mix.get('competitor_owned', 0) else 'P2'
        top_types = [k for k, _ in mix.most_common(5)]
        opportunities.append({
            'brand_topic_category': journey,
            'opportunity_type': opp,
            'priority': priority,
            'summary': _summary(journey, opp, top_types),
            'dominant_source_types': top_types,
            'top_domains': [d for d, _ in domains[journey].most_common(10) if d],
            'recommended_pr_action': _summary(journey, opp, top_types),
            'target_source_types': top_types[:4],
            'why_it_matters': 'Observed AI citations show that external sources are shaping buyer answers where owned target pages are absent or under-cited.',
        })
    agg = src.get('aggregate', {})
    out = {
        'schema_version': 'pr_publisher_opportunity_plan_v1',
        'brand': cfg.get('brand'),
        'market': cfg.get('market'),
        'publisher_dependency_summary': {
            'overall_dependency_level': 'high' if agg.get('owned_domain_citations', 0) < max(1, agg.get('total_cited_sources', 1)) * 0.2 else 'medium',
            'summary': 'AI Mode citation evidence is materially dependent on external publishers, authorities, forums, partners, aggregators or competitor-owned sources.',
            'dominant_source_types': [k for k, _ in Counter(agg.get('source_type_mix', {})).most_common(8)],
            'brand_topic_categories_most_affected': [o['brand_topic_category'] for o in sorted(opportunities, key=lambda x: x['priority'])[:5]],
        },
        'per_brand_topic_opportunities_compact': sorted(opportunities, key=lambda x: (x['priority'], x['brand_topic_category'])),
        'recommended_pr_actions_compact': [
            {
                'action': o['recommended_pr_action'],
                'target_brand_topic_category': o['brand_topic_category'],
                'impact': 'high' if o['priority'] == 'P1' else 'medium',
                'effort': 'medium',
                'priority': o['priority'],
            } for o in opportunities[:10]
        ],
    }
    write_json('outputs/pr_publisher_opportunities/pr_opportunity_plan.json', out)
    print('Wrote outputs/pr_publisher_opportunities/pr_opportunity_plan.json')


if __name__ == '__main__':
    main()
