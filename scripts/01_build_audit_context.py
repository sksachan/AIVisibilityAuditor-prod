from __future__ import annotations

from typing import Any, Dict, List, Tuple

from lib import (
    get_config, read_json, write_json, is_valid_url, is_owned_url, keyword_tokens, resolve_path,
    dedupe_queries, infer_page_type, infer_journey_from_queries, infer_priority_from_queries, query_type_mix,
    mapping_quality_from_score
)

CATEGORY_EXPECTED_PAGE_TYPES = {
    'EV range, charging and battery confidence': {'ev_range_charging', 'comparison_specs', 'model_overview'},
    'Hybrid / e-POWER running costs and powertrain choice': {'powertrain', 'comparison_specs', 'model_overview'},
    'Family practicality, space and comfort': {'family_practicality', 'comparison_specs', 'model_overview'},
    'Safety, reliability and trust': {'safety_trust', 'ownership_aftersales', 'comparison_specs'},
    'Value, offers, finance and total cost of ownership': {'finance_value', 'comparison_specs'},
    'Urban mobility and compact car fit': {'urban_mobility', 'family_practicality', 'model_overview', 'comparison_specs'},
    'Ownership, service and aftersales confidence': {'ownership_aftersales', 'safety_trust'},
}

CATEGORY_HINTS = {
    'EV range, charging and battery confidence': ['ev','electric','charge','charging','battery','ariya','sakura','leaf','cruising-distance','v2h','subsidy'],
    'Hybrid / e-POWER running costs and powertrain choice': ['hybrid','e-power','epower','powertrain','fuel','note','kicks','aura','x-trail','e-4orce'],
    'Family practicality, space and comfort': ['serena','elgrand','interior','seat','luggage','storage','comfort','family','minivan','x-trail','roox','nv200','caravan'],
    'Safety, reliability and trust': ['safety','propilot','360_safety','warranty','trust','adas','icc','nim','jncap'],
    'Value, offers, finance and total cost of ownership': ['finance','credit','offer','cost','tco','tax','subsidy','subscription','bvc','campaign','price','comparison'],
    'Urban mobility and compact car fit': ['sakura','kei','compact','parking','city','urban','roox','dayz','ease_of_driving','kicks'],
    'Ownership, service and aftersales confidence': ['service','maintenance','warranty','owner','dealer','support','connect','maintepro','faq','roadside'],
}

MODEL_TERMS = ['ariya','leaf','sakura','note','serena','x-trail','kicks','roox','dayz','elgrand','nv200','caravan','clipper']


def _load_queries(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    qp_path = cfg['paths'].get('query_portfolio_input')
    portfolio = read_json(qp_path, default={}) if qp_path else {}
    queries = portfolio.get('queries') or portfolio.get('query_portfolio') or portfolio.get('recommended_audit_shortlist') or []
    if not queries:
        existing = read_json(cfg['paths']['audit_context_input'], default={})
        queries = existing.get('queries', [])
    out = []
    seen = set()
    for q in queries:
        if isinstance(q, str):
            q = {'query': q}
        if not isinstance(q, dict) or not q.get('query'):
            continue
        key = q['query'].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(q))
    return out[: int(cfg.get('max_queries', 70))]


def _load_pages(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    inv_path = cfg['paths'].get('owned_url_inventory_input')
    inventory = read_json(inv_path) if inv_path and resolve_path(inv_path).exists() else None
    pages = []
    if isinstance(inventory, list):
        pages = inventory
    elif isinstance(inventory, dict):
        pages = inventory.get('pages') or inventory.get('urls') or inventory.get('owned_urls') or []
    if not pages:
        existing = read_json(cfg['paths']['audit_context_input'], default={})
        pages = existing.get('pages', [])
    normalized = []
    seen = set()
    for item in pages:
        obj = {'url': item} if isinstance(item, str) else dict(item or {})
        url = obj.get('url') or obj.get('resolved_url') or obj.get('loc')
        if not url or not is_valid_url(url):
            continue
        if not is_owned_url(url, cfg.get('owned_domains', [])):
            continue
        if url.lower().split('?')[0].endswith('.pdf'):
            continue
        if url in seen:
            continue
        seen.add(url)
        obj['url'] = url
        obj.setdefault('title', '')
        obj.setdefault('description', '')
        obj['page_type'] = infer_page_type(url, obj.get('title',''), obj.get('description',''))
        obj.setdefault('brand_topic_category', '')
        normalized.append(obj)
    return normalized


def _score_page_for_query(page: Dict[str, Any], query: Dict[str, Any]) -> Tuple[float, List[str]]:
    reasons: List[str] = []
    qtext = ' '.join([query.get('query',''), query.get('brand_topic_category',''), query.get('intent_type',''), query.get('answer_type','')])
    ptext = ' '.join([page.get('url',''), page.get('title',''), page.get('description',''), page.get('brand_topic_category',''), page.get('page_type','')])
    q_tokens = set(keyword_tokens(qtext))
    p_tokens = set(keyword_tokens(ptext))
    overlap = q_tokens & p_tokens
    score = len(overlap) * 1.75
    if overlap:
        reasons.append(f'token_overlap:{len(overlap)}')
    cat = query.get('brand_topic_category') or ''
    url = page.get('url','').lower()
    pt = page.get('page_type','')
    expected = CATEGORY_EXPECTED_PAGE_TYPES.get(cat, set())
    if page.get('brand_topic_category') and page.get('brand_topic_category') == cat:
        score += 14; reasons.append('existing_category_match')
    if pt in expected:
        score += 16; reasons.append(f'expected_page_type:{pt}')
    elif pt in {'model_overview','comparison_specs'} and any(x in cat.lower() for x in ['family','urban','value']):
        score += 6; reasons.append(f'acceptable_generic_page_type:{pt}')
    elif pt and pt != 'other':
        score -= 5; reasons.append(f'page_type_mismatch:{pt}')
    for h in CATEGORY_HINTS.get(cat, []):
        if h in url:
            score += 3
    query_text = query.get('query','').lower()
    for model in MODEL_TERMS:
        if model in query_text and model in url:
            score += 22; reasons.append(f'model_match:{model}')
        elif query.get('query_type') == 'branded' and model in query_text and model not in url:
            score -= 3
    # Avoid treating support/connect pages as catch-all finance/service pages when better category pages exist.
    if pt == 'ownership_aftersales' and cat == 'Value, offers, finance and total cost of ownership':
        score -= 16; reasons.append('ownership_page_for_value_query_penalty')
    if pt == 'finance_value' and cat == 'Ownership, service and aftersales confidence':
        score -= 10; reasons.append('finance_page_for_ownership_query_penalty')
    if 'faq' in url and 'faq' in (query.get('answer_type','') or '').lower():
        score += 5; reasons.append('faq_answer_type_match')
    # If previous curated mapping points to this URL, keep it as a mild preference, not a hard override.
    if page.get('url') in (query.get('mapped_pages') or []) or page.get('url') == query.get('mapped_url'):
        score += 4; reasons.append('previous_mapping_hint')
    return score, reasons


def main() -> None:
    cfg = get_config()
    existing = read_json(cfg['paths']['audit_context_input'], default={})
    queries = _load_queries(cfg)
    pages = _load_pages(cfg)
    per_query = int(cfg.get('max_owned_pages_per_query', cfg.get('scope_multiplier', 1)))

    mapped_queries = []
    for q0 in queries:
        q = dict(q0)
        scored = []
        for p in pages:
            score, reasons = _score_page_for_query(p, q)
            scored.append((score, reasons, p))
        ranked = sorted(scored, key=lambda x: x[0], reverse=True)
        selected = [p['url'] for score, _, p in ranked[:per_query] if score > 0]
        if not selected and ranked:
            selected = [ranked[0][2]['url']]
        best_score, best_reasons, best_page = ranked[0] if ranked else (0, [], {})
        q['mapped_pages'] = selected
        q['mapped_url'] = selected[0] if selected else ''
        q['mapping_score'] = round(float(best_score), 1)
        q['mapping_quality'] = mapping_quality_from_score(best_score, (best_page or {}).get('page_type',''), CATEGORY_EXPECTED_PAGE_TYPES.get(q.get('brand_topic_category',''), set()))
        q['mapping_reason'] = best_reasons[:8]
        mapped_queries.append(q)

    mapped_by_url: Dict[str, List[Dict[str, Any]]] = {}
    for q in mapped_queries:
        for url in q.get('mapped_pages', []):
            mapped_by_url.setdefault(url, []).append(q)

    enriched_pages = []
    for p in pages:
        obj = dict(p)
        rel_qs = dedupe_queries(mapped_by_url.get(p['url'], []))
        obj['mapped_queries'] = [q.get('query','') for q in rel_qs]
        obj['related_queries'] = [{'query': q.get('query',''), 'brand_topic_category': q.get('brand_topic_category',''), 'query_type': q.get('query_type',''), 'priority': q.get('priority',''), 'mapping_quality': q.get('mapping_quality','')} for q in rel_qs]
        obj['brand_topic_category'] = obj.get('brand_topic_category') or infer_journey_from_queries(rel_qs)
        obj['priority'] = obj.get('priority') or infer_priority_from_queries(rel_qs)
        obj['query_type_mix'] = query_type_mix(rel_qs)
        obj['page_type'] = infer_page_type(obj.get('url',''), obj.get('title',''), obj.get('description',''))
        obj['page_inventory_role'] = 'query_mapped' if rel_qs else 'inventory_only'
        if rel_qs:
            qualities = [q.get('mapping_quality','weak') for q in rel_qs]
            obj['mapping_quality_mix'] = dict(__import__('collections').Counter(qualities))
        enriched_pages.append(obj)

    audit_context = {
        'brand': cfg.get('brand') or existing.get('brand'),
        'market': cfg.get('market') or existing.get('market'),
        'domain': cfg.get('domain') or existing.get('domain'),
        'vertical': cfg.get('vertical'),
        'query_portfolio_id': cfg.get('query_portfolio_id'),
        'scope_multiplier': cfg.get('scope_multiplier', 1),
        'queries': mapped_queries,
        'pages': enriched_pages,
        'summary': {
            'query_count': len(mapped_queries),
            'owned_url_count': len(enriched_pages),
            'mapped_query_count': sum(1 for q in mapped_queries if q.get('mapped_pages')),
            'max_owned_pages_per_query': per_query,
            'query_mapped_page_count': sum(1 for p in enriched_pages if p.get('page_inventory_role') == 'query_mapped'),
            'mapping_quality_mix': dict(__import__('collections').Counter(q.get('mapping_quality','weak') for q in mapped_queries)),
        }
    }
    write_json(cfg['paths']['audit_context_output'], audit_context)
    print(f"Wrote {cfg['paths']['audit_context_output']} with {len(mapped_queries)} queries and {len(enriched_pages)} owned URLs")


if __name__ == '__main__':
    main()
