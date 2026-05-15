from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

from lib import get_config, write_json, resolve_path, compact_whitespace


def _candidate_bases(domain: str) -> list[str]:
    domain = (domain or '').rstrip('/') + '/'
    parsed = urlparse(domain)
    bases = [domain]
    host = parsed.netloc
    scheme = parsed.scheme or 'https'
    if host and not host.startswith('www.'):
        bases.append(f'{scheme}://www.{host}/')
    if host.startswith('www.'):
        bases.append(f'{scheme}://{host[4:]}/')
    # Nissan Japan often serves content on www2/www3, but robots and llms should be checked at main domain as well.
    if host in {'nissan.co.jp', 'www.nissan.co.jp'}:
        bases.extend(['https://www2.nissan.co.jp/', 'https://www3.nissan.co.jp/'])
    out = []
    seen = set()
    for b in bases:
        if b not in seen:
            seen.add(b); out.append(b)
    return out


def _fetch(url: str, timeout: int = 20) -> dict:
    try:
        r = requests.get(url, timeout=timeout, headers={'User-Agent': 'AIVisibilityAudit/1.0 (+https://openai.com)'}, allow_redirects=True)
        text = r.text or ''
        return {
            'url': url,
            'resolved_url': str(r.url),
            'status': 'available' if 200 <= r.status_code < 300 and text.strip() else 'not_available',
            'http_status_code': r.status_code,
            'content_type': r.headers.get('content-type', ''),
            'chars': len(text),
            'sample': compact_whitespace(text[:1600]),
        }
    except Exception as e:
        return {'url': url, 'resolved_url': '', 'status': 'error', 'http_status_code': None, 'content_type': '', 'chars': 0, 'sample': '', 'error': str(e)[:300]}


def _first_available(results: list[dict]) -> dict:
    return next((r for r in results if r.get('status') == 'available'), results[0] if results else {})


def main() -> None:
    cfg = get_config()
    out_path = cfg['paths'].get('site_standards', 'outputs/site_standards/site_standards.json')
    if cfg.get('reuse_existing_outputs', True) and not cfg.get('force_refetch_site_standards', False) and resolve_path(out_path).exists():
        print(f"Reusing {out_path}")
        return
    if not cfg.get('check_site_standards', True):
        write_json(out_path, {'site_standards_status': 'skipped', 'notes': 'check_site_standards=false'})
        return
    bases = _candidate_bases(cfg.get('domain', ''))
    robots_attempts = [_fetch(urljoin(base, 'robots.txt')) for base in bases]
    llms_attempts = [_fetch(urljoin(base, 'llms.txt')) for base in bases]
    robots = _first_available(robots_attempts)
    llms = _first_available(llms_attempts)
    robots_sample = robots.get('sample', '').lower()
    out = {
        'site_standards_status': 'success',
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'domain': cfg.get('domain'),
        'candidate_bases_checked': bases,
        'robots_txt': robots,
        'llms_txt': llms,
        'robots_attempts': robots_attempts,
        'llms_txt_attempts': llms_attempts,
        'signals': {
            'robots_available': robots.get('status') == 'available',
            'llms_txt_available': llms.get('status') == 'available',
            'robots_mentions_sitemap': 'sitemap:' in robots_sample,
            'robots_blocks_common_ai_agents': any(x in robots_sample for x in ['gptbot', 'chatgpt-user', 'google-extended', 'ccbot', 'perplexitybot', 'claudebot', 'anthropic-ai']),
        },
        'notes': 'robots.txt and llms.txt are domain-level standards checks. Page-level JSON-LD is scored from page markdown where observable.'
    }
    write_json(out_path, out)
    print(f"Wrote {out_path}")


if __name__ == '__main__':
    main()
