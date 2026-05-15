from __future__ import annotations

from collections import defaultdict, Counter
from lib import get_config, read_json, write_json, dedupe_queries


def main() -> None:
    cfg = get_config()
    bench = read_json(cfg['paths']['source_preference_benchmark'])
    by_key = defaultdict(lambda: {'queries': [], 'count': 0, 'brand_topic_category': '', 'rule': '', 'rule_type': ''})
    cross = Counter()
    for row in bench.get('per_query', []):
        if row.get('evidence_strength') in {'weak', 'none'}:
            continue
        for rc in row.get('recommended_rule_candidates', []):
            rule = rc.get('rule') if isinstance(rc, dict) else str(rc)
            rtype = rc.get('rule_type', 'content_structure') if isinstance(rc, dict) else 'content_structure'
            key = (row.get('brand_topic_category','Uncategorised'), rtype, rule)
            by_key[key]['brand_topic_category'] = key[0]
            by_key[key]['rule_type'] = rtype
            by_key[key]['rule'] = rule
            by_key[key]['queries'].append({'query': row.get('query',''), 'query_type': row.get('query_type','')})
            by_key[key]['count'] += 1
            cross[(rtype, rule)] += 1
    by_cat = defaultdict(list)
    for item in by_key.values():
        by_cat[item['brand_topic_category']].append(item)
    rules_by_category = []
    for cat, items in by_cat.items():
        items = sorted(items, key=lambda x: x['count'], reverse=True)[:8]
        rules = []
        for item in items:
            qs = dedupe_queries(item['queries'])[:5]
            rules.append({
                'rule': item['rule'],
                'rule_type': item['rule_type'],
                'why_it_matters_for_ai_visibility': 'This pattern improves extractability, factual support or answer usefulness for AI-generated responses.',
                'evidence_basis': f"Observed in {item['count']} medium/high-confidence owned-vs-external comparisons.",
                'applies_to_queries': qs,
                'implementation_hint': item['rule'],
                'confidence': 'high' if item['count'] >= 3 else 'medium' if item['count'] >= 2 else 'low'
            })
        rules_by_category.append({'brand_topic_category': cat, 'rules': rules})
    cross_rules = []
    for (rtype, rule), count in cross.most_common(8):
        cross_rules.append({
            'rule': rule,
            'rule_type': rtype,
            'why_it_matters_for_ai_visibility': 'Recurring pattern across multiple query benchmarks.',
            'evidence_basis': f'Observed {count} times across medium/high-confidence comparisons.',
            'confidence': 'high' if count >= 5 else 'medium'
        })
    out = {
        'preference_rule_status': 'success' if rules_by_category else 'partial',
        'rules_by_brand_topic_category': rules_by_category,
        'cross_journey_rules': cross_rules,
        'rules_to_avoid': [
            {'anti_pattern': 'Keyword stuffing', 'why_to_avoid': 'Traditional SEO keyword stuffing is not a reliable GEO strategy and can reduce usefulness.', 'risk': 'high'},
            {'anti_pattern': 'Unsupported statistics', 'why_to_avoid': 'Unvalidated figures create factual, legal and trust risk.', 'risk': 'high'},
            {'anti_pattern': 'Fake authority or invented citations', 'why_to_avoid': 'Synthetic proof points damage trust and can create compliance risk.', 'risk': 'high'},
            {'anti_pattern': 'Hidden prompting or hidden text', 'why_to_avoid': 'Manipulative hidden content creates safety and transparency risk.', 'risk': 'high'},
            {'anti_pattern': 'Over-promotional copy', 'why_to_avoid': 'AI answer systems tend to prefer neutral, factual, source-backed passages.', 'risk': 'medium'}
        ],
        'aggregate': {
            'highest_value_rules': [r['rule'] for r in cross_rules[:6]],
            'recurring_rule_themes': list(dict.fromkeys([r['rule_type'] for r in cross_rules])),
            'summary': 'Preference rules were generated from medium/high-confidence owned-vs-external benchmark deltas, with weak source evidence filtered out.'
        }
    }
    write_json(cfg['paths']['preference_rules'], out)
    print(f"Wrote {cfg['paths']['preference_rules']}")


if __name__ == '__main__':
    main()
