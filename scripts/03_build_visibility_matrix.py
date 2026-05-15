from __future__ import annotations

from collections import Counter
from lib import get_config, read_json, write_json, is_owned_url, classify_source, confidence_from_source_quality


def main() -> None:
    cfg = get_config()
    audit = read_json(cfg['paths']['audit_context_output'], default=read_json(cfg['paths']['audit_context_input']))
    gam = read_json(cfg['paths']['google_ai_mode_output'])
    by_query = {q.get('query'): q for q in audit.get('queries', [])}
    max_refs = int(cfg.get('max_external_pages_per_query', 3))
    rows = []
    source_type_counter = Counter()
    source_quality_counter = Counter()
    for item in gam.get('per_query', []):
        q = by_query.get(item.get('query'), {})
        sources = item.get('top_cited_sources', [])[:max_refs]
        external = []
        for s in sources:
            url = s.get('url') or ''
            meta = classify_source(url, s.get('source_name',''), s.get('title',''), cfg) if url else {}
            if url and not is_owned_url(url, cfg.get('owned_domains', [])):
                merged = {**s, **meta}
                external.append(merged)
                source_type_counter[meta.get('source_type', 'other')] += 1
                source_quality_counter[meta.get('source_quality', 'low')] += 1
        cited = bool(sources)
        source_quality = external[0].get('source_quality') if external else None
        mapped_pages = q.get('mapped_pages') or item.get('target_pages') or ([item.get('target_page','')] if item.get('target_page') else [])
        rows.append({
            'query': item.get('query',''),
            'query_type': q.get('query_type') or item.get('query_type',''),
            'brand_topic_category': q.get('brand_topic_category') or item.get('brand_topic_category',''),
            'mapped_owned_page': mapped_pages[0] if mapped_pages else '',
            'mapped_owned_pages': mapped_pages,
            'brand_present': item.get('brand_present', False),
            'owned_domain_cited': item.get('target_domain_cited', False),
            'owned_page_cited': item.get('target_page_cited', False),
            'first_external_source': external[0] if external else None,
            'external_sources': external[:max_refs],
            'has_external_source': bool(external),
            'external_source_count': len(external),
            'visibility_level': 'high' if item.get('target_page_cited') else 'medium' if item.get('target_domain_cited') else 'low' if cited else 'not_validated',
            'answer_summary': item.get('answer_summary','')[:500],
            'confidence': confidence_from_source_quality(source_quality or 'medium', has_crawl=True) if external else item.get('confidence','medium'),
            'evidence_notes': ([] if external else ['No non-owned cited URL available for this query.'])
        })
    out = {
        'visibility_matrix_status': 'success' if rows else 'failed',
        'brand': audit.get('brand'),
        'market': audit.get('market'),
        'max_external_references_per_query': max_refs,
        'rows': rows,
        'aggregate': {
            'queries': len(rows),
            'owned_page_cited_count': sum(1 for r in rows if r['owned_page_cited']),
            'owned_domain_cited_count': sum(1 for r in rows if r['owned_domain_cited']),
            'external_source_count': sum(1 for r in rows if r['has_external_source']),
            'total_external_references': sum(r['external_source_count'] for r in rows),
            'queries_with_3_external_sources': sum(1 for r in rows if r['external_source_count'] >= 3),
            'top_external_source_types': source_type_counter.most_common(12),
            'source_quality_mix': dict(source_quality_counter)
        }
    }
    write_json(cfg['paths']['visibility_matrix'], out)
    print(f"Wrote {cfg['paths']['visibility_matrix']}")


if __name__ == '__main__':
    main()
