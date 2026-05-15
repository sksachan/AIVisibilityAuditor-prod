from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any, Dict, List

from lib import get_config, read_json, write_json


def _avg(rows: List[Dict[str, Any]], key: str) -> float:
    vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
    return round(mean(vals), 1) if vals else 0


def main() -> None:
    cfg = get_config()
    ai = read_json('outputs/visibility/ai_visibility_scores.json', default={'queries': [], 'aggregate': {}})
    source = read_json('outputs/source_landscape/competitor_publisher_landscape.json', default={'aggregate': {}, 'kpis': {}})
    owned = read_json(cfg['paths']['owned_readiness'], default={'page_analysis': []})
    external = read_json(cfg['paths']['external_readiness'], default={'source_analysis': []})
    gap = read_json('outputs/benchmark/owned_vs_external_gap_analysis.json', default={'per_query': [], 'aggregate': {}})
    recs = read_json('outputs/recommendations/owned_page_content_recommendations.json', default={'pages': [], 'summary': {}})
    pr = read_json('outputs/pr_publisher_opportunities/pr_opportunity_plan.json', default={})

    owned_rows = owned.get('page_analysis', [])
    ext_rows = external.get('source_analysis', [])
    scored_ext = [r for r in ext_rows if r.get('readiness_score') is not None]
    ai_agg = ai.get('aggregate', {})
    gap_agg = gap.get('aggregate', {})
    source_agg = source.get('aggregate', {})
    executive_kpis = {
        'observed_queries': ai_agg.get('query_count', len(ai.get('queries', []))),
        'ai_visibility_score': ai_agg.get('avg_ai_visibility_score', 0),
        'owned_pages_scored': owned.get('pages_scored') or len(owned_rows),
        'external_pages_scored': external.get('sources_scored') or len(scored_ext),
        'owned_page_citations': source_agg.get('owned_target_page_citations', 0),
        'owned_domain_citations': source_agg.get('owned_domain_citations', 0),
        'external_dependency_rate': ai_agg.get('external_dependency_rate', 0),
        'competitor_citation_rate': ai_agg.get('competitor_citation_rate', 0),
        'publisher_dependency_rate': ai_agg.get('publisher_dependency_rate', 0),
        'aggregator_dependency_rate': ai_agg.get('aggregator_dependency_rate', 0),
        'owned_geo_readiness_avg_120': _avg(owned_rows, 'geo_score_120'),
        'external_readiness_avg': _avg(scored_ext, 'readiness_score'),
        'average_source_preference_gap': gap_agg.get('avg_source_preference_gap', 0),
        'page_level_recommendations': recs.get('summary', {}).get('total_recommendations', 0),
    }
    journeys = ai.get('brand_topic_summary', [])
    dataset = {
        'dataset_schema_version': 'ai_visibility_dashboard_dataset_v4',
        'brand': cfg.get('brand'),
        'market': cfg.get('market'),
        'domain': cfg.get('domain'),
        'executive_kpis': executive_kpis,
        'ai_visibility': ai,
        'source_landscape': source,
        'owned_readiness_summary': owned.get('aggregate') or {
            'pages_scored': executive_kpis['owned_pages_scored'],
            'avg_geo_score_120': executive_kpis['owned_geo_readiness_avg_120'],
        },
        'external_readiness_summary': external.get('aggregate') or {
            'sources_scored': executive_kpis['external_pages_scored'],
            'avg_readiness_score': executive_kpis['external_readiness_avg'],
        },
        'brand_topic_summary': journeys,
        'owned_vs_external_gap_analysis': gap,
        'owned_page_content_recommendations': recs,
        'publisher_opportunity_plan': pr,
        'recommended_next_steps': [
            {'step': 'Prioritise P1 owned-page modules where source-preference gap is severe or material.', 'owner': 'AEM/CMS', 'priority': 'P1'},
            {'step': 'Use Bodhi LLM workflow to draft CMS-ready modules from the generated recommendation briefs.', 'owner': 'Content', 'priority': 'P1'},
            {'step': 'Validate all claims, cost assumptions, warranty references and safety statements before publishing.', 'owner': 'Product/Legal', 'priority': 'P1'},
            {'step': 'Activate PR/publisher opportunities where external authority shapes AI answers.', 'owner': 'PR', 'priority': 'P2'},
            {'step': 'Re-run AI visibility measurement after publishing changes.', 'owner': 'Analytics', 'priority': 'P2'},
        ],
        'methodology': {
            'owned_geo_scoring': 'Strict six-dimension GEO readiness framework, 6 x 20 = 120.',
            'ai_visibility_scoring': 'Observed Google AI Mode evidence: citations, brand prominence, citation rank, sentiment, competitor displacement and source control.',
            'benchmarking': 'Mapped owned pages compared against observed winning external cited sources by query.',
            'recommendations': 'HTML-module-level CMS briefs generated from readiness gaps, source-preference gaps and winning external patterns.',
        },
        'reporting_caveats': [
            'AI visibility evidence is based on available Google AI Mode / SerpAPI extracts.',
            'Owned GEO readiness is strict page-readiness scoring and is separate from observed citation visibility.',
            'External sources are observed citation benchmarks; low-quality, social/forum and off-market sources are retained as signals but require validation before use as proof.',
            'Recommendations are briefs for CMS generation; final copy must be validated by product, legal and market teams.',
        ],
    }
    bundle = {
        'bundle_schema_version': 'ai_visibility_bodhi_bundle_v4',
        'metadata': {
            'brand': cfg.get('brand'), 'market': cfg.get('market'), 'domain': cfg.get('domain'),
            'scoring_framework': 'Strict GEO readiness + observed AI visibility + source-preference benchmark'
        },
        'executive_kpis': executive_kpis,
        'ai_visibility_summary': ai.get('aggregate', {}),
        'source_landscape_summary': source,
        'owned_readiness_summary': dataset['owned_readiness_summary'],
        'external_readiness_summary': dataset['external_readiness_summary'],
        'benchmark_summary': gap.get('aggregate', {}),
        'owned_page_content_recommendations': recs,
        'pr_publisher_opportunities': pr,
        'dashboard_dataset_path': cfg['paths'].get('dashboard_dataset'),
        'methodology': dataset['methodology'],
        'reporting_caveats': dataset['reporting_caveats'],
    }
    write_json(cfg['paths']['dashboard_dataset'], dataset)
    write_json(cfg['paths']['bodhi_bundle'], bundle)
    print(f"Wrote {cfg['paths']['dashboard_dataset']}")
    print(f"Wrote {cfg['paths']['bodhi_bundle']}")


if __name__ == '__main__':
    main()
