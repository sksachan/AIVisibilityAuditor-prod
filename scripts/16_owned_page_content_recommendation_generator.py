from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from lib import get_config, read_json, write_json, normalize_url, safe_slug

MODULES = {
    'answer_first_summary': {'html_element': 'section', 'schema': None},
    'key_facts_panel': {'html_element': 'aside', 'schema': None},
    'comparison_table': {'html_element': 'table', 'schema': None},
    'faq_block': {'html_element': 'section', 'schema': 'FAQPage'},
    'proof_panel': {'html_element': 'aside', 'schema': None},
    'freshness_notice': {'html_element': 'time', 'schema': None},
    'internal_link_cluster': {'html_element': 'nav', 'schema': 'BreadcrumbList'},
    'schema_patch': {'html_element': "script[type='application/ld+json']", 'schema': 'FAQPage/Product/Offer/WebPage'},
    'cost_explainer': {'html_element': 'section', 'schema': None},
}


def _dimension_gaps(page: Dict[str, Any]) -> List[str]:
    gaps = []
    for d, obj in (page.get('dimension_scores') or {}).items():
        score = obj.get('score') if isinstance(obj, dict) else None
        if isinstance(score, int) and score <= 15:
            gaps.append(d)
    return gaps


def _module_for_gap(gap: str, query: str, source_types: List[str]) -> str:
    q = query.lower()
    if gap == 'faq_readiness': return 'faq_block'
    if gap == 'structured_data': return 'schema_patch'
    if gap == 'eeat_signals': return 'proof_panel'
    if gap == 'freshness_index': return 'freshness_notice'
    if 'cost' in q or 'finance' in q or 'monthly' in q or '5 years' in q: return 'cost_explainer'
    if gap == 'semantic_depth' and ('compare' in q or 'vs' in q or 'which' in q): return 'comparison_table'
    if gap == 'content_clarity': return 'answer_first_summary'
    if 'publisher_review' in source_types or 'aggregator_marketplace' in source_types: return 'comparison_table'
    return 'key_facts_panel'


def _heading(module: str, query: str, journey: str) -> str:
    if module == 'answer_first_summary': return query.rstrip('?')
    if module == 'faq_block': return 'Frequently asked questions'
    if module == 'comparison_table': return 'Key comparison points to consider'
    if module == 'proof_panel': return 'Official proof points and source information'
    if module == 'freshness_notice': return 'Last reviewed and validity information'
    if module == 'schema_patch': return 'Structured data update'
    if module == 'cost_explainer': return 'Cost factors and assumptions to compare'
    return f'Key facts for {journey}'


def _brief(module: str, query: str, journey: str, patterns: List[str]) -> str:
    base = f'Generate Japan-market content that directly supports the query: "{query}". Keep claims factual, cite official Nissan or authoritative sources, and avoid unsupported comparative or savings claims.'
    if module == 'answer_first_summary':
        return base + ' Produce an 80-120 word answer-first section suitable for placement below the hero and above product-led content.'
    if module == 'faq_block':
        return base + ' Produce 4-6 natural-language Q&A pairs that address likely AI-search follow-up questions.'
    if module == 'comparison_table':
        return base + ' Produce a neutral comparison table with buyer decision criteria, trade-offs, assumptions and links to official specs or terms.'
    if module == 'proof_panel':
        return base + ' Produce a proof panel with validated warranty, safety, finance, charging, service or specification evidence.'
    if module == 'freshness_notice':
        return base + ' Produce visible update/validity copy, including fields for last reviewed date and content owner.'
    if module == 'schema_patch':
        return base + ' Produce a schema brief for FAQPage, Product, Offer, WebPage or BreadcrumbList, using only validated fields.'
    if module == 'cost_explainer':
        return base + ' Produce a cost-explainer module with assumptions, variables and caveats, but no invented savings figures.'
    return base + ' Produce a key-facts module with extractable facts, assumptions and source labels.'


def _html_stub(module: str, heading: str) -> str:
    if module == 'comparison_table':
        return f'<section class="geo-comparison" data-geo-module="comparison_table"><h2>{heading}</h2><table><thead><tr><th>Decision factor</th><th>Nissan-owned answer</th><th>What the customer should check</th></tr></thead><tbody><tr><td>To be completed</td><td>Use validated Nissan facts only</td><td>Link to official source</td></tr></tbody></table></section>'
    if module == 'faq_block':
        return f'<section class="geo-faq" data-geo-module="faq_block"><h2>{heading}</h2><div class="faq-item"><h3>Question to be generated</h3><p>Answer to be generated from validated evidence.</p></div></section>'
    if module == 'proof_panel':
        return f'<aside class="geo-proof-panel" data-geo-module="proof_panel"><h2>{heading}</h2><ul><li>Validated proof point and source label to be added.</li></ul></aside>'
    if module == 'schema_patch':
        return '<script type="application/ld+json">{ "@context": "https://schema.org", "@type": "WebPage" }</script>'
    if module == 'freshness_notice':
        return f'<p class="geo-freshness" data-geo-module="freshness_notice"><strong>{heading}:</strong> Last reviewed: YYYY-MM-DD. Validate before publishing.</p>'
    return f'<section class="geo-answer-module" data-geo-module="{module}"><h2>{heading}</h2><p>Draft content to be generated by Bodhi using the supplied brief and validation requirements.</p></section>'


def main() -> None:
    cfg = get_config()
    owned = read_json(cfg['paths']['owned_readiness'], default={'page_analysis': []})
    gap = read_json('outputs/benchmark/owned_vs_external_gap_analysis.json', default={'per_query': []})
    ai = read_json('outputs/visibility/ai_visibility_scores.json', default={'queries': []})
    page_rows = owned.get('page_analysis', [])
    page_index = {normalize_url(p.get('url', ''), strip_query=True): p for p in page_rows}
    ai_by_query = {r.get('query'): r for r in ai.get('queries', [])}
    page_queries: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for q in gap.get('per_query', []):
        for p in q.get('owned_pages', []):
            url = normalize_url(p.get('url', ''), strip_query=True)
            if url:
                page_queries[url].append(q)
    pages = []
    module_mix = Counter()
    priority_mix = Counter()
    total = 0
    for url_norm, qrows in page_queries.items():
        page = page_index.get(url_norm, {})
        if not page:
            continue
        d_gaps = _dimension_gaps(page)
        recs = []
        # Prioritise severe/material gaps, then add dimension-specific gaps.
        sorted_q = sorted(qrows, key=lambda x: x.get('source_preference_gap', 0), reverse=True)[:5]
        for q in sorted_q:
            query = q.get('query', '')
            source_types = q.get('winning_external_source_types', [])
            patterns = []
            for ext in q.get('external_sources', []):
                patterns.extend(ext.get('winning_patterns', []) or [])
            seed_gaps = d_gaps or ['content_clarity', 'semantic_depth', 'faq_readiness']
            # Keep at most two modules per query to avoid bloated output.
            modules = []
            for g in seed_gaps:
                m = _module_for_gap(g, query, source_types)
                if m not in modules:
                    modules.append(m)
                if len(modules) >= 2:
                    break
            if q.get('source_preference_gap', 0) >= 10 and 'answer_first_summary' not in modules:
                modules.insert(0, 'answer_first_summary')
            for m in modules[:2]:
                total += 1
                priority = 'P1' if q.get('gap_severity') in {'severe', 'material'} else 'P2'
                heading = _heading(m, query, q.get('brand_topic_category', ''))
                module_mix[m] += 1
                priority_mix[priority] += 1
                recs.append({
                    'recommendation_id': f'{safe_slug(url_norm, 36)}_{total:04d}',
                    'priority': priority,
                    'target_query': query,
                    'gap_severity': q.get('gap_severity'),
                    'source_preference_gap': q.get('source_preference_gap'),
                    'html_element': MODULES[m]['html_element'],
                    'cms_module_type': m,
                    'placement': 'Below hero / above existing product-led body content' if m in {'answer_first_summary', 'key_facts_panel', 'comparison_table', 'cost_explainer'} else 'Near relevant section or before footer',
                    'proposed_heading': heading,
                    'proposed_html': _html_stub(m, heading),
                    'brief_for_bodhi': _brief(m, query, q.get('brand_topic_category', ''), patterns),
                    'content_requirements': [
                        'Use Japan-market facts and caveats.',
                        'Do not invent numeric claims, savings, rankings or citations.',
                        'Link to official Nissan source pages or validated external authority where required.',
                        'Keep copy neutral and answer-led rather than purely promotional.'
                    ],
                    'schema_recommendation': {'type': MODULES[m]['schema'], 'required': bool(MODULES[m]['schema'])},
                    'validation_required': ['Product/content owner', 'Legal/compliance if claims include cost, warranty, safety or comparison'],
                    'expected_gap_closed': q.get('gap_reasons', [])[:4],
                })
        ai_context = ai_by_query.get(sorted_q[0].get('query') if sorted_q else '', {})
        pages.append({
            'page_url': page.get('url') or url_norm,
            'page_type': page.get('page_type', ''),
            'brand_topic_category': page.get('brand_topic_category', ''),
            'mapped_queries': page.get('mapped_queries', []),
            'owned_geo_readiness': {
                'score_120': page.get('geo_score_120'),
                'readiness_score': page.get('readiness_score'),
                'dimension_gaps': d_gaps,
            },
            'ai_visibility_context': {
                'ai_visibility_score': ai_context.get('ai_visibility_score'),
                'visibility_status': ai_context.get('visibility_status'),
                'owned_target_page_cited': ai_context.get('owned_target_page_cited'),
                'winning_source_types': list(dict.fromkeys([st for q in qrows for st in q.get('winning_external_source_types', [])])),
                'competitor_cited': any(ai_by_query.get(q.get('query'), {}).get('competitor_cited') for q in qrows),
            },
            'benchmark_gaps': [{
                'query': q.get('query'),
                'gap_severity': q.get('gap_severity'),
                'source_preference_gap': q.get('source_preference_gap'),
                'gap_reasons': q.get('gap_reasons', []),
                'winning_external_source_types': q.get('winning_external_source_types', []),
            } for q in sorted_q],
            'recommended_content_changes': recs[:10],
        })
    out = {
        'schema_version': 'owned_page_content_recommendations_v1',
        'brand': cfg.get('brand'),
        'market': cfg.get('market'),
        'method': {
            'owned_scoring': 'strict_geo_readiness_6x20',
            'benchmarking': 'query_level_owned_vs_winning_external_sources',
            'recommendation_basis': 'GEO readiness gaps plus observed Google AI Mode source-preference gaps',
        },
        'summary': {
            'pages_with_recommendations': len(pages),
            'total_recommendations': total,
            'module_type_mix': dict(module_mix),
            'priority_mix': dict(priority_mix),
        },
        'pages': sorted(pages, key=lambda p: (p['owned_geo_readiness'].get('score_120') or 999, -len(p['recommended_content_changes']))),
    }
    write_json('outputs/recommendations/owned_page_content_recommendations.json', out)
    write_json('outputs/recommendations/cms_content_generation_briefs.json', out)
    print('Wrote outputs/recommendations/owned_page_content_recommendations.json')


if __name__ == '__main__':
    main()
