from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from lib import (
    get_config, get_weights, read_json, write_json, read_text, score_text_features,
    dedupe_queries, infer_page_type, infer_journey_from_queries, infer_priority_from_queries, query_type_mix,
    classify_source, confidence_from_source_quality
)

DIMENSION_TO_ACTION = {
    'content_clarity': ('Content Clarity', 'Add an answer-first summary, clearer headings and a concise plain-language explanation of the buyer question.'),
    'semantic_depth': ('Semantic Depth', 'Add substantive topic coverage, validated facts, quantified evidence and comparison-ready buyer guidance.'),
    'structured_data': ('Structured Data', 'Add structured data such as WebPage, FAQPage, Product or Offer only where visible content supports it.'),
    'eeat_signals': ('E-E-A-T Signals', 'Add validated source references, warranty/safety/finance proof and authority signals.'),
    'freshness_index': ('Freshness & Index', 'Add visible update dates, offer/specification validity and technical accessibility signals.'),
    'faq_readiness': ('FAQ Readiness', 'Add concise Q&A blocks that answer natural-language buyer questions.'),
}


def _load_extraction_manifest(page: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(page.get('extraction_manifest'), dict):
        return page['extraction_manifest']
    path = page.get('extraction_manifest_file') or page.get('manifest_file')
    if path:
        try:
            return read_json(path, default={})
        except Exception:
            return {}
    return {}


def _is_excluded_from_content_score(page: Dict[str, Any], manifest: Dict[str, Any]) -> bool:
    policy = page.get('content_score_policy') or manifest.get('content_score_policy')
    status = page.get('crawl_status') or manifest.get('crawl_status')
    return policy == 'exclude_from_content_score' or status in {'blocked', 'failed'}


def _avg_numeric(rows: List[Dict[str, Any]], key: str) -> float:
    vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
    return round(sum(vals) / len(vals), 1) if vals else 0


def _min_numeric(rows: List[Dict[str, Any]], key: str) -> float:
    vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
    return min(vals) if vals else 0


def _max_numeric(rows: List[Dict[str, Any]], key: str) -> float:
    vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
    return max(vals) if vals else 0


def _score_page_collection(collection: List[Dict[str, Any]], query_lookup: Dict[str, List[Dict[str, Any]]], out_kind: str, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    weights = get_weights()
    scored = []
    for page in collection:
        url = page.get('url','') or page.get('resolved_url','')
        related_queries = dedupe_queries(query_lookup.get(url, []) or page.get('related_queries', []) or [])
        mapped_queries = dedupe_queries(page.get('mapped_queries', []))
        if not related_queries and mapped_queries:
            related_queries = [{'query': q} if isinstance(q, str) else q for q in mapped_queries]
        query_text = ' '.join(q.get('query','') for q in related_queries[:8] if isinstance(q, dict))
        md = read_text(page.get('markdown_file','')) if page.get('markdown_file') else page.get('markdown','')
        ptype = page.get('page_type') or infer_page_type(url, page.get('title',''), page.get('description',''))
        manifest = _load_extraction_manifest(page)
        rel_objs = [{'query': q.get('query',''), 'brand_topic_category': q.get('brand_topic_category',''), 'query_type': q.get('query_type',''), 'priority': q.get('priority','')} for q in related_queries if isinstance(q, dict)]
        source_meta = classify_source(url, page.get('source_name',''), page.get('title',''), cfg) if out_kind == 'external' else {}

        if _is_excluded_from_content_score(page, manifest):
            obj = {**{k:v for k,v in page.items() if k != 'markdown'}}
            obj['url'] = url
            obj['page_type'] = ptype
            obj['related_queries'] = rel_objs
            obj['mapped_queries'] = [q['query'] for q in rel_objs] or [q if isinstance(q, str) else q.get('query','') for q in mapped_queries]
            obj['brand_topic_category'] = page.get('brand_topic_category') or infer_journey_from_queries(rel_objs)
            obj['priority'] = page.get('priority') or infer_priority_from_queries(rel_objs)
            obj['query_type_mix'] = query_type_mix(rel_objs)
            obj['readiness_score'] = None
            obj['geo_score_120'] = None
            obj['max_geo_score'] = 120
            obj['citation_likelihood'] = 'not scored - inaccessible'
            obj['feature_scores'] = {}
            obj['dimension_scores'] = {}
            obj['penalties'] = {}
            obj['word_count'] = 0
            obj['cleaned_text_chars'] = 0
            obj['headings'] = []
            obj['questions'] = []
            obj['numeric_mentions_sample'] = []
            obj['links_sample'] = []
            obj['schema_types'] = []
            obj['standards_signals'] = (manifest.get('geo_signals') or {}) if isinstance(manifest, dict) else {}
            obj['extraction_manifest'] = manifest
            obj['content_score_policy'] = 'exclude_from_content_score'
            obj['page_level_recommendations'] = []
            obj['critical_issues'] = [{'dimension': 'Crawl accessibility', 'issue': 'Page was blocked, failed or only partially extracted by the local full-page crawler, so content quality was not scored.', 'severity': 'medium'}]
            if out_kind == 'external':
                obj.update(source_meta)
            obj['confidence'] = 'low'
            scored.append(obj)
            continue

        result = score_text_features(md, query_text, weights, page_url=url, page_type=ptype, extraction_manifest=manifest)
        score = result['score']
        geo_score_120 = result['geo_score_120']
        # Cap questionable external sources so they are not over-treated as winners.
        if out_kind == 'external':
            thresholds = weights.get('thresholds', {})
            cap = None
            if source_meta.get('source_quality') == 'low':
                cap = int(thresholds.get('low_quality_source_score_cap', 58))
            if source_meta.get('is_off_market'):
                cap = min(cap or 100, int(thresholds.get('off_market_source_score_cap', 62)))
            if source_meta.get('is_social_or_forum'):
                cap = min(cap or 100, int(thresholds.get('social_forum_source_score_cap', 60)))
            if cap is not None:
                score = min(score, cap)
                geo_score_120 = min(geo_score_120, int(round(cap * 1.2)))

        recommendations = []
        critical_issues = []
        for dim, dim_obj in result.get('dimension_scores', {}).items():
            dim_score = dim_obj.get('score', 0)
            label, action = DIMENSION_TO_ACTION.get(dim, (dim, 'Improve this dimension with evidence-backed content.'))
            if dim_score <= 10:
                recommendations.append({
                    'dimension': label,
                    'score': dim_score,
                    'action': action,
                    'effort': 'medium' if dim in {'semantic_depth','structured_data','eeat_signals'} else 'low',
                    'validation_requirement': 'Validate exact figures, claims and source references before publishing.' if dim in {'semantic_depth','eeat_signals','freshness_index'} else '',
                })
            if dim_score <= 5:
                critical_issues.append({
                    'dimension': label,
                    'issue': f'{label} is weak or not observed in collected page evidence.',
                    'severity': 'high' if dim in {'semantic_depth','structured_data','eeat_signals','faq_readiness'} else 'medium',
                })

        obj = {**{k:v for k,v in page.items() if k != 'markdown'}}
        obj['url'] = url
        obj['page_type'] = ptype
        obj['related_queries'] = rel_objs
        obj['mapped_queries'] = [q['query'] for q in rel_objs] or [q if isinstance(q, str) else q.get('query','') for q in mapped_queries]
        obj['brand_topic_category'] = page.get('brand_topic_category') or infer_journey_from_queries(rel_objs)
        obj['priority'] = page.get('priority') or infer_priority_from_queries(rel_objs)
        obj['query_type_mix'] = query_type_mix(rel_objs)
        obj['readiness_score'] = score
        obj['geo_score_120'] = geo_score_120
        obj['max_geo_score'] = 120
        obj['citation_likelihood'] = result.get('citation_likelihood')
        obj['raw_readiness_score_before_quality_cap'] = result['score'] if out_kind == 'external' else score
        obj['raw_geo_score_120_before_quality_cap'] = result['geo_score_120'] if out_kind == 'external' else geo_score_120
        obj['feature_scores'] = result['features']
        obj['dimension_scores'] = result['dimension_scores']
        obj['penalties'] = result['penalties']
        obj['word_count'] = result['word_count']
        obj['cleaned_text_chars'] = result.get('cleaned_text_chars', 0)
        obj['headings'] = result['headings']
        obj['questions'] = result['questions']
        obj['numeric_mentions_sample'] = result['numeric_mentions_sample']
        obj['links_sample'] = result['links_sample']
        obj['schema_types'] = result.get('schema_types', [])
        obj['standards_signals'] = result.get('standards_signals', {})
        obj['extraction_manifest'] = manifest
        obj['extraction_manifest_signals'] = result.get('extraction_manifest_signals', {})
        obj['extraction_manifest_metrics'] = result.get('extraction_manifest_metrics', {})
        obj['content_score_policy'] = page.get('content_score_policy') or manifest.get('content_score_policy') or 'score'
        obj['page_level_recommendations'] = recommendations[:8]
        obj['critical_issues'] = critical_issues[:8]
        if out_kind == 'external':
            obj.update(source_meta)
        obj['confidence'] = confidence_from_source_quality(obj.get('source_quality','high' if out_kind == 'owned' else 'medium'), result['word_count'] >= 250)
        scored.append(obj)
    return scored


def _summarise_by_journey(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by = defaultdict(list)
    for item in items:
        cat = item.get('brand_topic_category') or 'Uncategorised'
        by[cat].append(item)
    out = []
    for cat, rows in by.items():
        out.append({
            'brand_topic_category': cat,
            'pages': len(rows),
            'avg_readiness_score': _avg_numeric(rows, 'readiness_score'),
            'avg_geo_score_120': _avg_numeric(rows, 'geo_score_120'),
            'lowest_score': _min_numeric(rows, 'readiness_score'),
            'highest_score': _max_numeric(rows, 'readiness_score'),
        })
    return sorted(out, key=lambda x: x['avg_readiness_score'])


def main() -> None:
    cfg = get_config()
    scope = read_json(cfg['paths']['evidence_scope'])
    owned = read_json(cfg['paths']['owned_pages_full'])
    external = read_json(cfg['paths']['external_pages_full'])

    owned_lookup: Dict[str, List[Dict[str, Any]]] = {}
    external_lookup: Dict[str, List[Dict[str, Any]]] = {}
    for q in scope.get('queries', []):
        for p in q.get('owned_pages', []):
            owned_lookup.setdefault(p.get('url'), []).append(q)
        for p in q.get('external_pages', []):
            external_lookup.setdefault(p.get('url'), []).append(q)

    owned_scored = _score_page_collection(owned.get('pages', []), owned_lookup, 'owned', cfg)
    external_scored = _score_page_collection(external.get('external_pages', []), external_lookup, 'external', cfg)

    low_quality_count = sum(1 for s in external_scored if s.get('source_quality') == 'low')
    off_market_count = sum(1 for s in external_scored if s.get('is_off_market'))
    social_forum_count = sum(1 for s in external_scored if s.get('is_social_or_forum'))

    owned_out = {
        'owned_readiness_status': 'success' if owned_scored else 'failed',
        'scoring_framework': 'GEO / AI Source Readiness Framework, six dimensions x 20 = 120',
        'pages_received': len(owned.get('pages', [])),
        'pages_scored': sum(1 for p in owned_scored if isinstance(p.get('readiness_score'), (int, float))),
        'pages_not_scored': sum(1 for p in owned_scored if not isinstance(p.get('readiness_score'), (int, float))),
        'page_analysis': owned_scored,
        'aggregate': {
            'avg_readiness_score': _avg_numeric(owned_scored, 'readiness_score'),
            'avg_geo_score_120': _avg_numeric(owned_scored, 'geo_score_120'),
            'highest_score': _max_numeric(owned_scored, 'readiness_score'),
            'lowest_score': _min_numeric(owned_scored, 'readiness_score'),
            'brand_topic_summary': _summarise_by_journey([p for p in owned_scored if p.get('brand_topic_category')]),
            'lowest_scoring_pages': sorted([{'url': p.get('url'), 'score': p.get('readiness_score'), 'geo_score_120': p.get('geo_score_120'), 'brand_topic_category': p.get('brand_topic_category'), 'page_type': p.get('page_type'), 'critical_issues': p.get('critical_issues', [])[:3]} for p in owned_scored if isinstance(p.get('readiness_score'), (int, float))], key=lambda x: x['score'])[:10]
        }
    }
    source_types = Counter(s.get('source_type','other') for s in external_scored)
    external_out = {
        'external_readiness_status': 'success' if external_scored else 'failed',
        'scoring_framework': 'GEO / AI Source Readiness Framework, six dimensions x 20 = 120',
        'sources_received': len(external.get('external_pages', [])),
        'sources_scored': sum(1 for p in external_scored if isinstance(p.get('readiness_score'), (int, float))),
        'sources_not_scored': sum(1 for p in external_scored if not isinstance(p.get('readiness_score'), (int, float))),
        'source_analysis': external_scored,
        'aggregate': {
            'avg_readiness_score': _avg_numeric(external_scored, 'readiness_score'),
            'avg_geo_score_120': _avg_numeric(external_scored, 'geo_score_120'),
            'highest_score': _max_numeric(external_scored, 'readiness_score'),
            'lowest_score': _min_numeric(external_scored, 'readiness_score'),
            'top_external_source_types': source_types.most_common(12),
            'low_quality_source_count': low_quality_count,
            'off_market_source_count': off_market_count,
            'social_or_forum_source_count': social_forum_count,
            'failed_or_unusable_sources': external.get('sources_failed', 0) or len(external.get('failed_sources', []))
        }
    }
    write_json(cfg['paths']['owned_readiness'], owned_out)
    write_json(cfg['paths']['external_readiness'], external_out)
    print(f"Wrote {cfg['paths']['owned_readiness']} and {cfg['paths']['external_readiness']}")


if __name__ == '__main__':
    main()
