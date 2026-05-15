from __future__ import annotations

from lib import get_config, read_json, write_json, is_owned_url, dedupe_list


def main() -> None:
    cfg = get_config()
    audit = read_json(cfg['paths']['audit_context_output'], default=read_json(cfg['paths']['audit_context_input']))
    visibility = read_json(cfg['paths']['visibility_matrix'])
    owned_per = int(cfg.get('max_owned_pages_per_query', cfg.get('scope_multiplier', 3)))
    external_per = int(cfg.get('max_external_pages_per_query', cfg.get('scope_multiplier', 3)))
    rows = []
    for q in audit.get('queries', [])[: int(cfg.get('max_queries', 70))]:
        match = next((r for r in visibility.get('rows', []) if r.get('query') == q.get('query')), {})
        owned = []
        for rank, u in enumerate((q.get('mapped_pages') or [])[:owned_per], start=1):
            owned.append({
                'url': u,
                'rank': rank,
                'selection_reason': 'mapped_owned_page_top_3',
                'mapping_quality': q.get('mapping_quality', 'not_validated'),
                'mapping_score': q.get('mapping_score', 0),
                'mapping_reason': q.get('mapping_reason', [])
            })
        external = []
        for src in (match.get('external_sources') or [])[:external_per]:
            if src and src.get('url') and not is_owned_url(src.get('url',''), cfg.get('owned_domains', [])):
                external.append({**src, 'selection_reason': 'google_ai_mode_top_3_external_citation'})
        # Fallback for older visibility outputs.
        if not external and match.get('first_external_source'):
            src = match.get('first_external_source')
            if src.get('url') and not is_owned_url(src.get('url',''), cfg.get('owned_domains', [])):
                external.append({**src, 'selection_reason': 'first_google_ai_mode_external_citation'})
        selected_external = dedupe_list(external, key=lambda x: x.get('url',''))[:external_per]
        rows.append({
            'query': q.get('query',''),
            'query_type': q.get('query_type',''),
            'brand_topic_category': q.get('brand_topic_category',''),
            'owned_pages': owned[:owned_per],
            'external_pages': selected_external,
            'external_sources': selected_external,
            'mapping_quality': q.get('mapping_quality', 'not_validated'),
            'comparison_scope': f"{owned_per} owned x {external_per} external",
            'scope_notes': 'Expanded scope: up to three mapped owned pages and three AI-cited external reference URLs per query.'
        })
    out = {
        'evidence_scope_status': 'success',
        'scope_multiplier': cfg.get('scope_multiplier', 3),
        'max_owned_pages_per_query': owned_per,
        'max_external_pages_per_query': external_per,
        'queries': rows,
        'aggregate': {
            'query_count': len(rows),
            'owned_page_links': sum(len(r['owned_pages']) for r in rows),
            'external_page_links': sum(len(r['external_pages']) for r in rows),
            'queries_with_3_owned_pages': sum(1 for r in rows if len(r['owned_pages']) >= 3),
            'queries_with_3_external_pages': sum(1 for r in rows if len(r['external_pages']) >= 3),
            'unique_owned_urls': len({p['url'] for r in rows for p in r['owned_pages']}),
            'unique_external_urls': len({p['url'] for r in rows for p in r['external_pages']}),
            'mapping_quality_mix': {k: sum(1 for r in rows if r.get('mapping_quality') == k) for k in ['strong','acceptable','weak','not_validated']}
        }
    }
    write_json(cfg['paths']['evidence_scope'], out)
    print(f"Wrote {cfg['paths']['evidence_scope']}")


if __name__ == '__main__':
    main()
