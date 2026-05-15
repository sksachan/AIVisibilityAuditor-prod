from __future__ import annotations

from lib import get_config, read_json, write_json, resolve_path
from local_hybrid_scraper import scrape_items_sync


def _selected_owned_pages(scope: dict) -> list[dict]:
    by_url: dict[str, dict] = {}
    for r in scope.get('queries', []):
        for p in r.get('owned_pages', []):
            url = p.get('url')
            if not url or url in by_url:
                continue
            by_url[url] = {
                **p,
                'url': url,
                'brand_topic_category': p.get('brand_topic_category') or r.get('brand_topic_category', ''),
                'related_queries_seed': [{
                    'query': r.get('query', ''),
                    'brand_topic_category': r.get('brand_topic_category', ''),
                    'query_type': r.get('query_type', ''),
                    'priority': r.get('priority', ''),
                }],
            }
        # append additional query seeds for URLs already seen
        for p in r.get('owned_pages', []):
            url = p.get('url')
            if url in by_url:
                by_url[url].setdefault('related_queries_seed', []).append({
                    'query': r.get('query', ''),
                    'brand_topic_category': r.get('brand_topic_category', ''),
                    'query_type': r.get('query_type', ''),
                    'priority': r.get('priority', ''),
                })
    return list(by_url.values())


def _is_reusable(page: dict) -> bool:
    return (
        page.get('scrape_method') in {'free_hybrid_local', 'local_full_page_playwright'}
        and page.get('markdown_file')
        and page.get('markdown_chars', 0) > 0
        and page.get('crawl_status') in {'success', 'weak', 'blocked'}
    )


def main() -> None:
    cfg = get_config()
    out_path = cfg['paths']['owned_pages_full']
    scope = read_json(cfg['paths']['evidence_scope'])
    selected = _selected_owned_pages(scope)
    selected_by_url = {p['url']: p for p in selected}

    force = bool(cfg.get('force_refetch_owned_pages') or cfg.get('force_refetch_local_owned'))
    existing = {'pages': [], 'failed_pages': []}
    if resolve_path(out_path).exists() and cfg.get('reuse_existing_outputs', True) and not force:
        existing = read_json(out_path, default=existing)

    existing_by_url = {p.get('url'): p for p in existing.get('pages', []) if p.get('url') and _is_reusable(p)}
    missing = [p for p in selected if p['url'] not in existing_by_url]

    if not missing and cfg.get('reuse_existing_outputs', True) and not force:
        print(f'Reusing existing {out_path}; all selected owned URLs already collected by local full-page scraper')
        return

    scrape_cfg = (cfg.get('scraping') or {})
    scraped = scrape_items_sync(missing if not force else selected, 'outputs/free_hybrid/owned_pages', 'owned', scrape_cfg)
    scraped_pages = {p.get('url'): p for p in scraped.get('pages', []) if p.get('url')}

    pages_by_url = {} if force else dict(existing_by_url)
    pages_by_url.update(scraped_pages)
    pages = [pages_by_url[u] for u in selected_by_url if u in pages_by_url]
    failed = list(existing.get('failed_pages', [])) + scraped.get('failed', [])

    out = {
        'collector': 'local_full_page_owned_pages',
        'status': 'success' if pages else 'failed',
        'paid_api_used': False,
        'firecrawl_used': False,
        'pages_requested': len(selected),
        'pages_collected': sum(1 for p in pages if p.get('crawl_status') == 'success'),
        'pages_weak': sum(1 for p in pages if p.get('crawl_status') == 'weak'),
        'pages_failed': sum(1 for p in pages if p.get('crawl_status') in {'failed', 'blocked'}),
        'pages': pages,
        'failed_pages': failed,
    }
    write_json(out_path, out)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
