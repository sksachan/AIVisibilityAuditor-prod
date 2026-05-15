from __future__ import annotations

from collections import defaultdict, Counter
from lib import get_config, read_json, write_json, dedupe_queries, dedupe_list

RULE_META = {
    'answer_first': ('answer_first_module', 'Content Clarity', 'AEM/CMS'),
    'content_structure': ('answer_first_module', 'Content Clarity', 'AEM/CMS'),
    'journey_coverage': ('journey_coverage_fix', 'Journey Coverage', 'SEO'),
    'evidence_quality': ('key_facts_module', 'E-E-A-T Signals', 'Product'),
    'quantified_facts': ('key_facts_module', 'E-E-A-T Signals', 'Product'),
    'comparison_readiness': ('comparison_table', 'Semantic Depth', 'Marketing'),
    'faq': ('faq_block', 'FAQ Readiness', 'AEM/CMS'),
    'schema': ('schema_fix', 'Structured Data', 'SEO'),
    'freshness': ('freshness_signal', 'Freshness & Index', 'AEM/CMS'),
    'neutral_tone': ('answer_first_module', 'Content Clarity', 'Marketing'),
    'authority_trust': ('proof_panel', 'Source Authority', 'PR'),
    'technical_accessibility': ('measurement_action', 'Measurement', 'SEO'),
}

ACTION_COPY = {
    'journey_coverage_fix': 'Map or create a more specific owned page for this journey intent before optimising the content.',
    'answer_first_module': 'Add an answer-first module that directly answers the buyer question in the first screen of content.',
    'key_facts_module': 'Add a validated key-facts module with Japan-market figures, assumptions and source labels.',
    'comparison_table': 'Add a comparison table or trade-off module aligned to the buyer decision.',
    'faq_block': 'Add concise FAQ blocks matching conversational AI-search questions.',
    'schema_fix': 'Add structured data only where the visible page content supports it.',
    'freshness_signal': 'Add visible freshness signals, validity dates or latest-specification references.',
    'proof_panel': 'Add a proof panel with validated warranty, safety, service, authority or expert evidence.',
    'source_validation': 'Validate source quality and replace weak external dependency with stronger owned or authority-backed evidence.',
    'publisher_pr_action': 'Address publisher-led visibility with PR, review, authority-source or partner proof activity.',
    'measurement_action': 'Track owned-page citation visibility and source-type dependency for this journey.'
}


JOURNEY_ACTION_PRIORITY = {
    'EV range, charging and battery confidence': {'key_facts_module': 120, 'faq_block': 110, 'proof_panel': 105, 'answer_first_module': 100, 'journey_coverage_fix': 90},
    'Hybrid / e-POWER running costs and powertrain choice': {'comparison_table': 120, 'key_facts_module': 112, 'answer_first_module': 104, 'faq_block': 98, 'journey_coverage_fix': 90},
    'Family practicality, space and comfort': {'key_facts_module': 116, 'faq_block': 110, 'comparison_table': 106, 'answer_first_module': 100, 'journey_coverage_fix': 90},
    'Safety, reliability and trust': {'proof_panel': 120, 'key_facts_module': 112, 'faq_block': 104, 'answer_first_module': 98, 'journey_coverage_fix': 90},
    'Value, offers, finance and total cost of ownership': {'key_facts_module': 118, 'comparison_table': 114, 'freshness_signal': 106, 'answer_first_module': 100, 'journey_coverage_fix': 90},
    'Urban mobility and compact car fit': {'key_facts_module': 114, 'comparison_table': 108, 'answer_first_module': 104, 'faq_block': 100, 'journey_coverage_fix': 90},
    'Ownership, service and aftersales confidence': {'faq_block': 118, 'proof_panel': 112, 'key_facts_module': 106, 'answer_first_module': 100, 'journey_coverage_fix': 90},
}

ACTION_PRIORITY = {
    'key_facts_module': 96,
    'proof_panel': 94,
    'answer_first_module': 90,
    'comparison_table': 88,
    'faq_block': 84,
    'journey_coverage_fix': 80,
    'schema_fix': 65,
    'freshness_signal': 62,
    'source_validation': 55,
    'publisher_pr_action': 50,
    'measurement_action': 20,
}


def _impact(delta: int, evidence_strength: str, action_type: str) -> str:
    if action_type == 'measurement_action':
        return 'medium'
    if evidence_strength == 'weak':
        return 'low'
    return 'high' if delta >= 15 else 'medium' if delta >= 6 else 'low'


def _effort(action_type: str) -> str:
    return 'low' if action_type in {'answer_first_module','faq_block','freshness_signal'} else 'medium' if action_type in {'key_facts_module','schema_fix','measurement_action','journey_coverage_fix'} else 'high'


def main() -> None:
    cfg = get_config()
    bench = read_json(cfg['paths']['source_preference_benchmark'])
    grouped = {}
    for row in bench.get('per_query', []):
        if row.get('evidence_strength') == 'none':
            continue
        delta = row.get('score_delta_external_minus_owned', 0)
        if delta <= 0 and not row.get('owned_gaps'):
            continue
        candidates = row.get('recommended_rule_candidates', [])[:5]
        if row.get('mapping_quality') == 'weak' and not any(c.get('rule_type') == 'journey_coverage' for c in candidates if isinstance(c, dict)):
            candidates.insert(0, {'rule': 'Improve query-to-page coverage by mapping or creating a more specific owned page for this intent.', 'rule_type': 'journey_coverage'})
        for rc in candidates:
            rule = rc.get('rule') if isinstance(rc, dict) else str(rc)
            rtype = rc.get('rule_type', 'content_structure') if isinstance(rc, dict) else 'content_structure'
            action_type, dimension, owner = RULE_META.get(rtype, ('answer_first_module', 'Content Clarity', 'AEM/CMS'))
            # Do not let accessibility/measurement crowd out implementation modules.
            if action_type == 'measurement_action' and row.get('evidence_strength') not in {'strong','moderate'}:
                continue
            key = (row.get('brand_topic_category',''), action_type)
            page_url = row.get('mapped_owned_page') or row.get('owned_page',{}).get('url','')
            item = grouped.setdefault(key, {
                'priority': 0,
                'brand_topic_category': key[0],
                'target_page': page_url,
                'target_pages': [],
                'action_type': action_type,
                'recommended_module': action_type,
                'recommended_action': f"For {key[0]}: {ACTION_COPY.get(action_type, rule)}",
                'dimension': dimension,
                'likely_owner': owner,
                'supporting_queries': [],
                'evidence_basis_parts': [],
                'max_delta': 0,
                'confidence_values': [],
                'external_source_types': Counter(),
                'depends_on': set(),
                'mapping_quality_values': [],
                'evidence_strength_values': []
            })
            item['supporting_queries'].append({'query': row.get('query',''), 'query_type': row.get('query_type','')})
            if page_url and page_url not in item['target_pages']:
                item['target_pages'].append(page_url)
            if not item.get('target_page') and page_url:
                item['target_page'] = page_url
            item['evidence_basis_parts'].append(f"{row.get('query','')}: external-minus-owned delta {delta}, evidence {row.get('evidence_strength','not_validated')}, mapping {row.get('mapping_quality','not_validated')}.")
            item['max_delta'] = max(item['max_delta'], delta)
            item['confidence_values'].append(row.get('confidence','medium'))
            item['mapping_quality_values'].append(row.get('mapping_quality','not_validated'))
            item['evidence_strength_values'].append(row.get('evidence_strength','not_validated'))
            st = row.get('external_source',{}).get('source_type')
            if st:
                item['external_source_types'][st] += 1
            if action_type in {'key_facts_module','proof_panel','comparison_table'}:
                item['depends_on'].add('Validate exact facts and source references before publishing')
            if action_type == 'journey_coverage_fix':
                item['depends_on'].add('Confirm whether a better existing Japan-market owned page exists before creating new content')
            if row.get('external_source',{}).get('source_quality') == 'low':
                item['depends_on'].add('Do not rely on low-quality external source as proof; validate with official or authority source')
    backlog = []
    severity = {'high': 3, 'medium': 2, 'low': 1}
    conf_rank = {'high': 3, 'medium': 2, 'low': 1}
    for item in grouped.values():
        conf = Counter(item['confidence_values']).most_common(1)[0][0] if item['confidence_values'] else 'medium'
        evidence_strength = Counter(item['evidence_strength_values']).most_common(1)[0][0] if item['evidence_strength_values'] else 'moderate'
        impact = _impact(item['max_delta'], evidence_strength, item['action_type'])
        effort = _effort(item['action_type'])
        if item['action_type'] == 'measurement_action' and len(item['supporting_queries']) < 3:
            continue
        backlog.append({
            'priority': 0,
            'brand_topic_category': item['brand_topic_category'],
            'target_query': (dedupe_queries(item['supporting_queries']) or [{'query':''}])[0]['query'],
            'target_page': item['target_page'],
            'recommended_action': item['recommended_action'],
            'action_type': item['action_type'],
            'recommended_module': item['recommended_module'],
            'dimension': item['dimension'],
            'impact': impact,
            'effort': effort,
            'confidence': conf,
            'likely_owner': item['likely_owner'],
            'supporting_queries': dedupe_queries(item['supporting_queries'])[:5],
            'target_pages': item.get('target_pages', [])[:5],
            'why_now': 'This journey shows a query-level owned-content or owned-coverage gap against AI-cited evidence.',
            'evidence_basis': ' '.join(item['evidence_basis_parts'][:3])[:900],
            'depends_on': sorted(item['depends_on']),
            'external_source_types': item['external_source_types'].most_common(5),
            'mapping_quality_mix': dict(Counter(item['mapping_quality_values'])),
            'expected_direction_of_improvement': 'Improve owned-page usefulness, extractability and citation readiness without promising citation uplift.'
        })
    def _rank(item):
        journey_boost = JOURNEY_ACTION_PRIORITY.get(item.get('brand_topic_category',''), {}).get(item.get('action_type'), ACTION_PRIORITY.get(item.get('action_type'), 0))
        return (journey_boost, severity.get(item['impact'],0), conf_rank.get(item['confidence'],0), {'low':3,'medium':2,'high':1}.get(item['effort'],0))
    backlog.sort(key=_rank, reverse=True)
    capped = []
    by_journey_count = Counter()
    for item in backlog:
        if by_journey_count[item['brand_topic_category']] >= 3:
            continue
        by_journey_count[item['brand_topic_category']] += 1
        item['priority'] = len(capped) + 1
        capped.append(item)
        if len(capped) >= 20:
            break
    by_journey = defaultdict(list)
    for item in capped:
        by_journey[item['brand_topic_category']].append(item)
    top_actions = dedupe_list([b['recommended_action'] for b in capped])[:5]
    quick_wins = dedupe_list([b['recommended_action'] for b in capped if b['effort']=='low'])[:6]
    strategic = dedupe_list([b['recommended_action'] for b in capped if b['effort']!='low' and b['action_type'] != 'measurement_action'])[:6]
    measurement = dedupe_list([b['recommended_action'] for b in capped if b['action_type'] == 'measurement_action'])[:3]
    out = {
        'prioritisation_status': 'success' if capped else 'partial',
        'priority_backlog': capped,
        'journey_level_priorities': [
            {'brand_topic_category': cat, 'current_visibility_gap': items[0]['evidence_basis'][:260], 'highest_priority_action': items[0]['recommended_action'], 'primary_owner': items[0]['likely_owner'], 'confidence': items[0]['confidence']}
            for cat, items in by_journey.items() if items
        ],
        'aggregate': {
            'top_5_actions': top_actions,
            'quick_wins': quick_wins,
            'strategic_builds': strategic,
            'measurement_actions': measurement,
            'summary': 'Backlog was aggregated by brand topic and action type, with implementation actions prioritised ahead of measurement-only actions.'
        }
    }
    write_json(cfg['paths']['improvement_backlog'], out)
    print(f"Wrote {cfg['paths']['improvement_backlog']}")


if __name__ == '__main__':
    main()
