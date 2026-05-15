from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlparse
from typing import Any, Dict, List

from lib import get_config, read_json, write_json, classify_source, is_owned_url, normalize_url, domain_of


def _load_google(cfg: Dict[str, Any]) -> Dict[str, Any]:
    path = cfg.get('paths', {}).get('google_ai_mode_output', 'outputs/google_ai_mode/google_ai_mode_output.json')
    return read_json(path, default={'per_query': []})


def _load_audit(cfg: Dict[str, Any]) -> Dict[str, Any]:
    paths = cfg.get('paths', {})
    return read_json(paths.get('audit_context_output', 'outputs/audit_context/audit_context.json'), default=read_json(paths.get('audit_context_input', 'inputs/audit_context.json'), default={'queries': []}))


def _entity_from_domain(host: str, title: str = '', source_name: str = '') -> str:
    if source_name:
        return source_name.strip()
    host = (host or '').lower().replace('www.', '')
    if not host:
        return title[:80] or 'unknown'
    root = host.split('.')[0]
    return root.replace('-', ' ').replace('_', ' ').title()


def _normalise_type(meta_type: str, url: str, cfg: Dict[str, Any], mapped_pages: List[str]) -> str:
    host = domain_of(url)
    norm = normalize_url(url, strip_query=True)
    mapped_norm = {normalize_url(u, strip_query=True) for u in mapped_pages or []}
    if norm in mapped_norm:
        return 'owned_target_page'
    if is_owned_url(url, cfg.get('owned_domains', [])):
        return 'owned_same_domain'
    mapping = {
        'owned_brand': 'owned_same_domain',
        'owned_ecosystem': 'nissan_ecosystem_off_market',
        'off_market_owned': 'nissan_ecosystem_off_market',
        'competitor_owned': 'competitor_owned',
        'publisher_review': 'publisher_review',
        'news_media': 'publisher_review',
        'marketplace_listing': 'aggregator_marketplace',
        'authority_body': 'authority_body',
        'partner_infrastructure': 'partner_infrastructure',
        'finance_lender': 'finance_or_insurance',
        'forum_community': 'forum_social_video',
        'video_social': 'forum_social_video',
        'dealer_retailer': 'dealer_retailer',
        'other': 'low_quality_unknown',
    }
    return mapping.get(meta_type or 'other', 'low_quality_unknown')


def _source_flags(source_type: str) -> Dict[str, bool]:
    return {
        'is_owned_target_page': source_type == 'owned_target_page',
        'is_owned_domain': source_type in {'owned_target_page', 'owned_same_domain'},
        'is_nissan_ecosystem': source_type == 'nissan_ecosystem_off_market',
        'is_competitor': source_type == 'competitor_owned',
        'is_publisher': source_type == 'publisher_review',
        'is_aggregator': source_type == 'aggregator_marketplace',
        'is_authority': source_type == 'authority_body',
        'is_forum_or_social': source_type == 'forum_social_video',
        'is_partner_infrastructure': source_type == 'partner_infrastructure',
        'is_finance_or_insurance': source_type == 'finance_or_insurance',
    }


def main() -> None:
    cfg = get_config()
    audit = _load_audit(cfg)
    google = _load_google(cfg)
    audit_by_query = {q.get('query'): q for q in audit.get('queries', [])}

    records: List[Dict[str, Any]] = []
    by_query: List[Dict[str, Any]] = []

    for idx, item in enumerate(google.get('per_query', []), start=1):
        query = item.get('query', '')
        q = audit_by_query.get(query, {})
        mapped_pages = q.get('mapped_pages') or ([q.get('mapped_url')] if q.get('mapped_url') else [])
        query_id = q.get('query_id') or item.get('query_id') or f'q{idx:03d}'
        citations = item.get('top_cited_sources') or item.get('citations') or []
        q_counts = Counter()
        q_domains = Counter()
        q_records = []
        for pos, src in enumerate(citations, start=1):
            url = src.get('url') or src.get('source_url') or ''
            if not url:
                continue
            host = domain_of(url)
            base_meta = classify_source(url, src.get('source_name', ''), src.get('title', ''), cfg)
            stype = _normalise_type(base_meta.get('source_type', 'other'), url, cfg, mapped_pages)
            flags = _source_flags(stype)
            entity = _entity_from_domain(host, src.get('title', ''), src.get('source_name', ''))
            rec = {
                'query_id': query_id,
                'query': query,
                'query_type': q.get('query_type') or item.get('query_type', ''),
                'brand_topic_category': q.get('brand_topic_category') or item.get('brand_topic_category', ''),
                'citation_position': int(src.get('first_cited_position') or src.get('citation_position') or pos),
                'citation_count': int(src.get('citation_count') or 1),
                'title': src.get('title', ''),
                'source_url': url,
                'source_domain': host,
                'source_entity': entity,
                'source_category': stype,
                'source_role': 'winning_citation',
                'market_relevance': 'japan_or_unknown' if stype not in {'nissan_ecosystem_off_market'} else 'off_market_or_global',
                'authority_level': base_meta.get('source_quality', 'low'),
                'commercial_bias': 'unknown',
                'snippet': src.get('snippet', ''),
                **flags,
                'raw_source_type': base_meta.get('source_type'),
                'source_quality_notes': base_meta.get('source_quality_notes', []),
            }
            records.append(rec)
            q_records.append(rec)
            q_counts[stype] += 1
            q_domains[host] += 1
        by_query.append({
            'query_id': query_id,
            'query': query,
            'query_type': q.get('query_type') or item.get('query_type', ''),
            'brand_topic_category': q.get('brand_topic_category') or item.get('brand_topic_category', ''),
            'citation_count': len(q_records),
            'citation_mix': dict(q_counts),
            'top_cited_domains': q_domains.most_common(10),
            'owned_target_page_cited': any(r['is_owned_target_page'] for r in q_records),
            'owned_domain_cited': any(r['is_owned_domain'] for r in q_records),
            'competitor_cited': any(r['is_competitor'] for r in q_records),
            'publisher_cited': any(r['is_publisher'] for r in q_records),
            'aggregator_cited': any(r['is_aggregator'] for r in q_records),
            'authority_body_cited': any(r['is_authority'] for r in q_records),
            'top_cited_source_type': q_records[0]['source_category'] if q_records else 'none',
            'top_cited_domain': q_records[0]['source_domain'] if q_records else '',
        })

    type_counts = Counter(r['source_category'] for r in records)
    domain_counts = Counter(r['source_domain'] for r in records)
    journey_type = defaultdict(Counter)
    for r in records:
        journey_type[r.get('brand_topic_category') or 'Uncategorised'][r['source_category']] += 1

    aggregate = {
        'total_cited_sources': len(records),
        'owned_target_page_citations': type_counts.get('owned_target_page', 0),
        'owned_domain_citations': type_counts.get('owned_target_page', 0) + type_counts.get('owned_same_domain', 0),
        'competitor_owned_citations': type_counts.get('competitor_owned', 0),
        'publisher_review_citations': type_counts.get('publisher_review', 0),
        'aggregator_marketplace_citations': type_counts.get('aggregator_marketplace', 0),
        'authority_body_citations': type_counts.get('authority_body', 0),
        'forum_social_video_citations': type_counts.get('forum_social_video', 0),
        'off_market_nissan_ecosystem_citations': type_counts.get('nissan_ecosystem_off_market', 0),
        'low_quality_unknown_citations': type_counts.get('low_quality_unknown', 0),
        'source_type_mix': dict(type_counts),
        'top_domains_by_citation_count': domain_counts.most_common(25),
        'top_source_types_by_journey': {j: c.most_common(10) for j, c in journey_type.items()},
    }
    total = max(1, len(records))
    landscape = {
        'schema_version': 'source_landscape_v1',
        'brand': cfg.get('brand'),
        'market': cfg.get('market'),
        'aggregate': aggregate,
        'kpis': {
            'competitor_citation_rate': round(aggregate['competitor_owned_citations'] / total, 3),
            'publisher_dependency_rate': round(aggregate['publisher_review_citations'] / total, 3),
            'aggregator_dependency_rate': round(aggregate['aggregator_marketplace_citations'] / total, 3),
            'authority_source_rate': round(aggregate['authority_body_citations'] / total, 3),
            'forum_social_rate': round(aggregate['forum_social_video_citations'] / total, 3),
            'owned_source_control_rate': round(aggregate['owned_domain_citations'] / total, 3),
        },
        'dominant_source_pattern': type_counts.most_common(1)[0][0] if records else 'not_validated',
        'strategic_risk': 'AI answers are shaped by external cited sources where owned target pages are absent or under-represented.'
    }

    write_json('outputs/source_landscape/source_classification.json', {
        'schema_version': 'source_classification_v1',
        'brand': cfg.get('brand'),
        'market': cfg.get('market'),
        'queries': by_query,
        'sources': records,
        'aggregate': aggregate,
    })
    write_json('outputs/source_landscape/competitor_publisher_landscape.json', landscape)
    print('Wrote outputs/source_landscape/source_classification.json')
    print('Wrote outputs/source_landscape/competitor_publisher_landscape.json')


if __name__ == '__main__':
    main()
