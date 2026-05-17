#!/usr/bin/env python3
"""Build the canonical query-led AI Search Visibility report bundle.

Locked orchestration strategy:
query -> top 3 owned URLs -> top 3 external citations -> winning patterns -> CMS/PR actions -> rerun deltas.

The script is dependency-light and intentionally deterministic. It consumes the existing
AIVisibilityAuditor output files and produces a single frontend/Bodhi-safe bundle:
  outputs/frontend_report_bundle.json
  outputs/bodhi/preview_node_bundle.json
  outputs/query_workbench/query_workbench.json
"""
from __future__ import annotations
import argparse, json, re, time, math
from pathlib import Path
from urllib.parse import urlparse
from collections import Counter, defaultdict
from typing import Any

OWNED_HINTS = ["nissan.co.jp", "nissan-global.com", "nissannews.com", "nissan-fs.co.jp"]
COMPETITORS = {
    "Toyota": ["toyota", "トヨタ", "lexus", "レクサス"],
    "Honda": ["honda", "ホンダ"],
    "Mitsubishi": ["mitsubishi", "三菱"],
    "Mazda": ["mazda", "マツダ"],
    "Subaru": ["subaru", "スバル"],
    "Suzuki": ["suzuki", "スズキ"],
    "Daihatsu": ["daihatsu", "ダイハツ"],
}
PREFERENCE_RULES = [
    "Start with a direct answer that can be quoted without page context.",
    "Use specific, verifiable evidence such as specifications, cost bands, dates, ranges, warranty terms, safety ratings or named examples.",
    "Use a neutral, informational tone and avoid promotional-only phrasing.",
    "Structure content with headings, lists, tables or FAQ blocks so answer engines can extract passages cleanly.",
    "Explain practical caveats and decision criteria, not only product features.",
    "Cite or link to authoritative internal or third-party evidence where claims need corroboration.",
    "Keep the content self-contained and focused on the buyer question.",
]


def load_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default
    return default


def write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def as_list(obj: Any, keys=()):
    if isinstance(obj, list): return obj
    if not isinstance(obj, dict): return []
    for k in keys:
        v=obj.get(k)
        if isinstance(v, list): return v
        if isinstance(v, dict):
            nested=as_list(v, keys)
            if nested: return nested
    return []


def text(v: Any, limit: int = 0) -> str:
    if v is None: s=''
    elif isinstance(v, str): s=v
    elif isinstance(v, (int,float,bool)): s=str(v)
    elif isinstance(v, list): s=' '.join(text(x) for x in v)
    elif isinstance(v, dict): s=' '.join(text(x) for k,x in v.items() if str(k).lower() not in {'html','raw_html','rendered_html'})
    else: s=str(v)
    s=re.sub(r'\s+',' ',s).strip()
    return s[:limit] if limit and len(s)>limit else s


def domain(url: str) -> str:
    try:
        d=urlparse(url or '').netloc.lower()
        return d[4:] if d.startswith('www.') else d
    except Exception:
        return ''


def is_owned(url: str) -> bool:
    d=domain(url)
    return any(h in d for h in OWNED_HINTS)


def source_type(url: str, raw='') -> str:
    d=domain(url); r=(raw or '').lower()
    if is_owned(url): return 'owned_or_brand_ecosystem'
    if any(x in d for x in ['toyota','honda','mitsubishi','mazda','subaru','suzuki','daihatsu','lexus']): return 'competitor_owned'
    if any(x in d for x in ['reddit','youtube','facebook','instagram','x.com','twitter','tiktok']): return 'forum_social_video'
    if any(x in d for x in ['go.jp','mlit','meti','nasva','enecho']): return 'authority_body'
    if any(x in d for x in ['tepco','charging','charge','evdays']): return 'partner_infrastructure'
    if any(x in d for x in ['price','carmo','rakuten','broker','mailmate','gaijinpot','tc-v']): return 'aggregator_marketplace'
    if 'review' in r or 'publisher' in r or any(x in d for x in ['nikkei','asahi','recharged','autonews','carwow','parkers','greencarreports']): return 'publisher_review'
    return r or 'other_external'


def query_id(row: dict, i: int) -> str:
    return str(row.get('query_id') or row.get('id') or row.get('qid') or f'q{i+1:03d}')


def normalise_query(row: dict) -> str:
    return text(row.get('query') or row.get('search_query') or row.get('question') or row.get('user_query'))


def refs_from(row: dict) -> list[dict]:
    out=[]
    if not isinstance(row, dict): return out
    for k in ['citations','references','top_citations','top_cited_sources','sources','organic_results','answer_supporting_references']:
        v=row.get(k)
        if isinstance(v, list): out += [x for x in v if isinstance(x, dict)]
    for k in ['answer','response','google_ai_mode','metadata']:
        if isinstance(row.get(k), dict): out += refs_from(row[k])
    seen=set(); clean=[]
    for r in out:
        u=text(r.get('url') or r.get('source_url') or r.get('link') or r.get('href'))
        if u and u not in seen:
            seen.add(u); clean.append(r)
    return clean


def detect_competitors(blob: str, citations: list[dict]) -> list[str]:
    all_text=(blob+' '+' '.join(text(c) for c in citations)).lower()
    found=[]
    for name, variants in COMPETITORS.items():
        if any(v.lower() in all_text for v in variants): found.append(name)
    return found


def score_owned_page(page: dict, query: str='') -> tuple[int, dict, list[str]]:
    blob=text(page)
    low=blob.lower(); q=normalise_query({'query':query}).lower()
    q_terms=[w for w in re.findall(r'[a-z0-9]+', q) if len(w)>3]
    overlap=len({w for w in q_terms if w in low})
    numeric=len(re.findall(r'\d+[\d,.]*\s?(km|kwh|kw|円|万円|年|%|％|mm|kg|人|席)', low))
    headings=len(re.findall(r'(^|\n)#{1,4}\s+', blob))
    questions=sum(low.count(x) for x in ['?', '？','faq','よくある','question','質問'])
    proof=sum(low.count(x) for x in ['official','warranty','safety','rating','test','保証','安全','評価','公式','仕様','諸元'])
    dates=1 if re.search(r'20[2-3][0-9]|更新日|last updated', low) else 0
    length=min(20, int(len(blob)/900))
    dims={
        'answer_clarity': min(20, 5+overlap*3 + (4 if len(blob)>500 else 0)),
        'semantic_depth': min(20, 4+length + min(6, numeric)),
        'structured_extractability': min(20, 5+headings*3 + min(6, questions)),
        'evidence_and_proof': min(20, 4+proof*2 + min(8, numeric)),
        'freshness': min(20, 8+dates*8),
        'faq_readiness': min(20, 4+questions*3),
    }
    score=sum(dims.values())
    gaps=[k for k,v in dims.items() if v<12]
    return score,dims,gaps


def map_owned_urls(query: str, owned_pages: list[dict], max_n=3) -> list[dict]:
    q_terms=[w for w in re.findall(r'[a-z0-9]+', query.lower()) if len(w)>2]
    ranked=[]
    for p in owned_pages:
        u=text(p.get('url') or p.get('resolved_url'))
        if not u: continue
        blob=(text(p.get('title'))+' '+text(p.get('description'))+' '+text(p.get('journey_category'))+' '+text(p.get('brand_topic_category'))+' '+text(p.get('mapped_queries'))+' '+text(p.get('related_queries_seed'))+' '+text(p.get('evidence_markdown'), 2000)).lower()
        overlap=len({w for w in q_terms if w in blob})
        score,dims,gaps=score_owned_page(p, query)
        mapping_score=min(100, overlap*14 + score/3 + (10 if is_owned(u) else 0))
        ranked.append((mapping_score, p, score, dims, gaps))
    ranked.sort(key=lambda x:x[0], reverse=True)
    out=[]
    for rank,(ms,p,score,dims,gaps) in enumerate(ranked[:max_n], start=1):
        out.append({
            'rank': rank,
            'url': text(p.get('url') or p.get('resolved_url')),
            'title': text(p.get('title') or p.get('page_title')),
            'mapping_score': round(ms,1),
            'mapping_reason': 'Best available owned page based on query-term, page-title, journey and evidence overlap.',
            'current_geo_score_120': score,
            'geo_dimensions': dims,
            'geo_gaps': gaps,
            'recommended_update_focus': gaps[:4] or ['evidence_and_proof'],
        })
    return out


def external_top3(row: dict) -> list[dict]:
    citations=[]
    for pos,r in enumerate(refs_from(row), start=1):
        u=text(r.get('url') or r.get('source_url') or r.get('link') or r.get('href'))
        if not u or is_owned(u): continue
        citations.append({
            'rank': len(citations)+1,
            'title': text(r.get('title') or r.get('source_name') or domain(u)),
            'url': u,
            'domain': domain(u),
            'source_type': source_type(u, text(r.get('source_type'))),
            'snippet': text(r.get('snippet') or r.get('text') or r.get('summary'), 500),
            'observed_citation_position': pos,
        })
        if len(citations)>=3: break
    return citations


def winning_patterns(query: str, citations: list[dict]) -> list[dict]:
    out=[]
    for c in citations:
        st=c['source_type']; sn=c.get('snippet','')
        patterns=[]
        if re.search(r'\d', sn): patterns.append('uses numeric evidence')
        if st in {'authority_body','partner_infrastructure'}: patterns.append('borrows authority from specialist or official source')
        if st in {'publisher_review','aggregator_marketplace'}: patterns.append('packages comparison or buyer guidance')
        if st=='forum_social_video': patterns.append('captures lived-experience language and objections')
        if not patterns: patterns.append('uses extractable answer wording')
        out.append({
            'source_url': c['url'], 'source_domain': c['domain'], 'source_type': st,
            'pattern_type': '; '.join(patterns),
            'owned_content_implication': 'Replicate the useful structure on mapped owned pages using verified brand facts only.',
            'pr_implication': 'Create corroborating third-party proof where owned pages cannot credibly self-validate the claim.',
            'evidence_basis': sn or f'{c["domain"]} appeared as a top external citation for this query.'
        })
    return out


def cms_recs(query: str, mapped: list[dict], patterns: list[dict]) -> list[dict]:
    recs=[]
    pat='; '.join(sorted({p['pattern_type'] for p in patterns})) or 'answer-first extractable evidence'
    for m in mapped:
        title=m['title'] or m['url'].split('/')[-1] or 'owned page'
        focus=', '.join(m.get('geo_gaps') or ['answer_clarity'])
        recs.append({
            'recommendation_id': f"cms_{abs(hash(query+m['url'])) % 10**10}",
            'query': query,
            'target_url': m['url'],
            'title': f'Add query-specific answer module to {title[:80]}',
            'owner': 'AEM/CMS + Product',
            'priority': 'High' if m.get('current_geo_score_120',0)<60 else 'Medium',
            'module_type': 'answer_first_summary_plus_faq',
            'placement': 'Above detailed product copy / below hero',
            'recommendation': f'Create a concise answer-first section for: {query}',
            'winning_pattern_to_copy': pat,
            'content_requirements': [
                'Use only verified product, pricing, warranty, charging, safety or ownership facts already approved for the market.',
                'State the direct answer in the first 120-180 words.',
                'Add a small comparison, caveat or decision checklist when the query is evaluative.',
                'Add FAQ schema only where the page already supports the answer.'
            ],
            'geo_gaps_addressed': m.get('geo_gaps') or [],
            'validation_required': ['Product', 'Legal/Compliance']
        })
    return recs


def pr_recs(query: str, citations: list[dict], patterns: list[dict]) -> list[dict]:
    if not citations: return []
    types=sorted({c['source_type'] for c in citations})
    return [{
        'recommendation_id': f"pr_{abs(hash(query+','.join(types))) % 10**10}",
        'query': query,
        'title': f'Build external proof for: {query[:90]}',
        'owner': 'PR / Communications',
        'priority': 'High' if any(t in {'publisher_review','authority_body','partner_infrastructure'} for t in types) else 'Medium',
        'target_source_types': types,
        'recommendation': 'Secure or create credible third-party-referenceable evidence that can corroborate the owned-page answer.',
        'why_it_matters': 'The current AI answer relies on external citations; owned content needs independent corroboration to change the answer source mix.',
        'evidence_basis': '; '.join(p['evidence_basis'] for p in patterns[:2]),
    }]


def visibility_score(status: str, owned_target: bool, owned_domain: bool, competitors: list[str], external_count: int) -> int:
    score=0
    if owned_target: score+=55
    elif owned_domain: score+=30
    if not competitors: score+=15
    else: score+=max(0, 12-len(competitors)*4)
    score+=min(20, external_count*4)
    if 'competitor' in status: score-=15
    if 'external' in status: score-=8
    return max(0,min(100,score))


def classify_visibility(row: dict, citations: list[dict], competitors: list[str]) -> str:
    owned_target=any(c.get('is_owned_target_page') or is_owned(c.get('url','')) for c in citations)
    owned_domain=any(is_owned(c.get('url','')) for c in citations)
    raw=text(row.get('visibility_status') or row.get('status')).lower()
    if owned_target: return 'owned_target_cited'
    if owned_domain: return 'owned_domain_cited'
    if competitors or 'competitor' in raw: return 'competitor_led'
    if citations: return 'external_led'
    return 'not_observed'



def write_compact_files_from_payload(root: Path, payload: Any) -> bool:
    """Accept Railway compact/bodhi-compact payloads and write their file objects into outputs/."""
    if not isinstance(payload, dict):
        return False
    # direct canonical handled elsewhere
    candidates=[]
    for key in ['files','bodhi_compact','compact_bundle','bundle','data','run','evidence','outputs']:
        v=payload.get(key)
        if isinstance(v, dict):
            candidates.append(v)
    if isinstance(payload.get('files'), dict):
        candidates.insert(0, payload['files'])
    candidates.append(payload)
    mapping={
        'audit_context':['audit_context','audit_context.json','outputs/audit_context/audit_context.json'],
        'evidence_scope':['evidence_scope','evidence_scope.json','outputs/evidence_scope/evidence_scope.json'],
        'google_ai_mode_compact':['google_ai_mode_compact','google_ai_mode_compact.json','outputs/google_ai_mode/google_ai_mode_compact.json'],
        'owned_pages_full':['owned_pages_full','owned_pages_full.json','outputs/content_intelligence/owned_pages_full.json'],
        'external_pages_full':['external_pages_full','external_pages_full.json','outputs/external_pages/external_pages_full.json'],
        'visibility_matrix':['visibility_matrix','visibility_matrix.json','outputs/visibility/visibility_matrix.json'],
        'source_classification':['source_classification','source_classification.json','outputs/source_landscape/source_classification.json'],
    }
    paths={
        'audit_context':'outputs/audit_context/audit_context.json',
        'evidence_scope':'outputs/evidence_scope/evidence_scope.json',
        'google_ai_mode_compact':'outputs/google_ai_mode/google_ai_mode_compact.json',
        'owned_pages_full':'outputs/content_intelligence/owned_pages_full.json',
        'external_pages_full':'outputs/external_pages/external_pages_full.json',
        'visibility_matrix':'outputs/visibility/visibility_matrix.json',
        'source_classification':'outputs/source_landscape/source_classification.json',
    }
    wrote=False
    for canonical, names in mapping.items():
        value=None
        for obj in candidates:
            for name in names:
                if name in obj:
                    value=obj[name]
                    break
            if value is not None:
                break
        if isinstance(value, dict) and 'content' in value:
            value=value['content']
        if isinstance(value, dict) and 'data' in value and len(value)==1:
            value=value['data']
        if isinstance(value, str):
            st=value.strip()
            if st.startswith('{') or st.startswith('['):
                try: value=json.loads(st)
                except Exception: pass
        if value is not None:
            write_json(root/paths[canonical], value)
            wrote=True
    return wrote


def find_canonical_payload(obj: Any) -> Any:
    if isinstance(obj, dict):
        if isinstance(obj.get('query_workbench'), list):
            return obj
        if isinstance(obj.get('frontend_report_bundle'), dict):
            return find_canonical_payload(obj['frontend_report_bundle'])
        # Bodhi Preview Node tile pattern
        data=obj.get('data')
        if isinstance(data, dict):
            got=find_canonical_payload(data)
            if got: return got
        layout=obj.get('layout')
        if isinstance(layout, dict):
            for tile in layout.get('tiles') or []:
                got=find_canonical_payload(tile)
                if got: return got
        default=obj.get('default')
        if isinstance(default, str):
            try:
                got=find_canonical_payload(json.loads(default))
                if got: return got
            except Exception:
                pass
        for v in obj.values():
            got=find_canonical_payload(v)
            if got: return got
    elif isinstance(obj, list):
        for v in obj:
            got=find_canonical_payload(v)
            if got: return got
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--project-root', default='.')
    ap.add_argument('--input-json', default='')
    ap.add_argument('--brand', default='Nissan')
    ap.add_argument('--market', default='Japan')
    ap.add_argument('--domain', default='https://www.nissan.co.jp')
    ap.add_argument('--run-id', default='')
    ap.add_argument('--max-owned', type=int, default=3)
    args=ap.parse_args()
    root=Path(args.project_root).resolve()
    raw_input=load_json(Path(args.input_json), {}) if args.input_json else {}

    audit=load_json(root/'outputs/audit_context/audit_context.json', {}) or load_json(root/'inputs/audit_context.json', {}) or {}
    evidence=load_json(root/'outputs/evidence_scope/evidence_scope.json', {}) or {}
    visibility=load_json(root/'outputs/visibility/visibility_matrix.json', {}) or {}
    ai_scores=load_json(root/'outputs/visibility/ai_visibility_scores.json', {}) or {}
    owned_full=load_json(root/'outputs/content_intelligence/owned_pages_full.json', {}) or {}
    external_full=load_json(root/'outputs/external_pages/external_pages_full.json', {}) or {}
    owned_recs_existing=load_json(root/'outputs/recommendations/owned_page_content_recommendations.json', {}) or {}
    pr_existing=load_json(root/'outputs/pr_publisher_opportunities/pr_opportunity_plan.json', {}) or {}
    action_existing=load_json(root/'outputs/actions/action_checklist.json', {}) or {}

    # Bodhi/Railway input support: canonical preview bundle or compact file payload.
    if isinstance(raw_input, dict):
        canonical = find_canonical_payload(raw_input)
        if isinstance(canonical, dict) and isinstance(canonical.get('query_workbench'), list):
            bundle=canonical
            write_json(root/'outputs/frontend_report_bundle.json', bundle)
            write_json(root/'outputs/bodhi/preview_node_bundle.json', bundle)
            write_json(root/'outputs/query_workbench/query_workbench.json', {'query_workbench': bundle.get('query_workbench',[])})
            print(json.dumps({'status':'copied_existing_canonical_bundle','query_count':len(bundle.get('query_workbench',[]))}, indent=2))
            return
        write_compact_files_from_payload(root, raw_input)

    query_rows = as_list(visibility, ['queries','rows']) or as_list(audit, ['queries','query_portfolio']) or as_list(evidence, ['queries'])
    owned_pages = as_list(owned_full, ['pages','owned_pages','items']) or as_list(audit, ['pages','owned_urls','candidate_owned_pages']) or as_list(evidence, ['owned_pages'])
    score_rows = as_list(ai_scores, ['scores','rows'])
    score_by_q={str(x.get('query_id') or x.get('id')): x for x in score_rows if isinstance(x, dict)}

    qwork=[]; all_citations=[]; all_cms=[]; all_pr=[]; source_counts=Counter(); competitor_counts=Counter()
    for i,row in enumerate(query_rows):
        if not isinstance(row, dict): continue
        qid=query_id(row,i); q=normalise_query(row)
        if not q: continue
        citations=[]
        # Use embedded citations first, fallback to external top3.
        embedded=refs_from(row)
        for pos,r in enumerate(embedded, start=1):
            u=text(r.get('url') or r.get('source_url') or r.get('link') or r.get('href'))
            if not u: continue
            c={'rank':pos,'title':text(r.get('title') or r.get('source_name') or domain(u)), 'url':u, 'domain':domain(u), 'source_type':source_type(u, text(r.get('source_type'))), 'snippet':text(r.get('snippet') or r.get('text') or r.get('summary'), 500), 'is_owned':is_owned(u)}
            citations.append(c); all_citations.append({**c,'query_id':qid,'query':q})
            source_counts[c['source_type']]+=1
        top3=[c for c in citations if not c['is_owned']][:3] or external_top3(row)
        for c in top3: source_counts[c['source_type']]+=0
        competitors=detect_competitors(text(row), citations)
        for comp in competitors: competitor_counts[comp]+=1
        status=classify_visibility(row, citations, competitors)
        mapped=map_owned_urls(q, owned_pages, args.max_owned)
        patterns=winning_patterns(q, top3)
        cms=cms_recs(q, mapped, patterns); pr=pr_recs(q, top3, patterns)
        all_cms.extend(cms); all_pr.extend(pr)
        sc=score_by_q.get(qid, {})
        owned_target=any(c.get('is_owned') for c in citations)
        owned_domain=owned_target
        ai_score=int(sc.get('ai_visibility_score') or visibility_score(status, owned_target, owned_domain, competitors, len(top3)))
        qwork.append({
            'query_id': qid,
            'query': q,
            'query_type': row.get('query_type') or ('branded' if 'nissan' in q.lower() or '日産' in q else 'non_branded'),
            'journey_category': text(row.get('brand_topic_category') or row.get('journey_category') or row.get('category') or 'Unclassified'),
            'current_ai_visibility': {
                'score': ai_score,
                'status': status,
                'owned_target_cited': owned_target,
                'owned_domain_cited': owned_domain,
                'competitors': competitors,
                'competitor_citation_count': len(competitors),
                'top_citations': citations[:8]
            },
            'mapped_owned_urls': mapped,
            'external_top3_benchmark': top3,
            'winning_patterns': patterns,
            'cms_recommendations': cms,
            'pr_recommendations': pr,
            'action_items': [],
            'previous_run_delta': None,
            'loop_state': 'baseline_ready' if not owned_target else 'monitor_and_refresh'
        })

    for item in qwork:
        actions=[]
        for c in item['cms_recommendations'][:3]:
            actions.append({'action':c['title'],'owner':c['owner'],'priority':c['priority'],'effort':'M','status':'Not started','target':c['target_url'],'workstream':'CMS remediation','source_query_id':item['query_id']})
        for p in item['pr_recommendations'][:1]:
            actions.append({'action':p['title'],'owner':p['owner'],'priority':p['priority'],'effort':'M','status':'Not started','target':', '.join(p.get('target_source_types',[])),'workstream':'PR / external proof','source_query_id':item['query_id']})
        item['action_items']=actions

    qcount=len(qwork); owned_count=len(owned_pages)
    avg_ai=round(sum(x['current_ai_visibility']['score'] for x in qwork)/max(1,qcount),1)
    target_cites=sum(1 for x in qwork if x['current_ai_visibility']['owned_target_cited'])
    domain_cites=sum(1 for x in qwork if x['current_ai_visibility']['owned_domain_cited'])
    competitor_led=sum(1 for x in qwork if x['current_ai_visibility']['status']=='competitor_led')
    external_led=sum(1 for x in qwork if x['current_ai_visibility']['status']=='external_led')
    owned_summary=[]
    seen=set()
    for x in qwork:
        for m in x['mapped_owned_urls']:
            if m['url'] in seen: continue
            seen.add(m['url'])
            owned_summary.append({**m,'related_queries':[{'id':x['query_id'],'query':x['query'],'visibility_status':x['current_ai_visibility']['status']}], 'journey_category':x['journey_category']})
    # merge duplicate related queries
    byurl={}
    for x in qwork:
        for m in x['mapped_owned_urls']:
            o=byurl.setdefault(m['url'], {**m,'related_queries':[], 'journey_category':x['journey_category']})
            o['related_queries'].append({'id':x['query_id'],'query':x['query'],'visibility_status':x['current_ai_visibility']['status']})
    owned_summary=list(byurl.values())
    actions=[a for q in qwork for a in q['action_items']]
    run_id=args.run_id or f"{args.brand}_{args.market}_{time.strftime('%Y%m%d_%H%M%S')}_baseline".replace(' ','_')
    bundle={
        'schema_version':'query_workbench.v1',
        'run_id':run_id,
        'brand':args.brand,
        'market':args.market,
        'domain':args.domain,
        'generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'locked_orchestration_strategy':'query -> top_3_owned_urls -> top_3_external_citations -> winning_patterns -> CMS_PR_recommendations -> rerun_delta -> refreshed_recommendations',
        'executive':{
            'summary': f'{args.brand} has {avg_ai}/100 average AI visibility across {qcount} audited queries. The optimisation loop is now query-led: each query is mapped to up to three owned URLs and benchmarked against the top external citations.',
            'what_is_happening':['AI answers are compressing discovery into a small citation set.','Owned pages must compete at query level, not only domain level.','External sources reveal the answer structure and evidence patterns that models prefer.'],
            'why_now':['Generative engines cite passages, not only rank pages.','Visibility should be managed as a recurring evidence and content loop.','New citations can appear after refresh, so recommendations must be regenerated from observed top sources.'],
            'priority_actions':['Implement top query-level CMS modules for mapped owned URLs.','Create PR proof assets where external sources currently dominate.','Rerun the same query portfolio after updates and compare deltas.'],
            'headline_metrics':{
                'ai_visibility_score':avg_ai,'query_count':qcount,'owned_page_count':len(owned_summary),'owned_target_page_citations':target_cites,'owned_domain_citations':domain_cites,'competitor_led_query_count':competitor_led,'external_led_query_count':external_led,'external_source_count':sum(source_counts.values()),'average_owned_geo_score_120':round(sum(o.get('current_geo_score_120',0) for o in owned_summary)/max(1,len(owned_summary)),1)
            }
        },
        'query_workbench':qwork,
        'owned_url_readiness':owned_summary,
        'cms_recommendations':all_cms,
        'pr_opportunities':all_pr,
        'action_checklist':actions,
        'source_landscape':{'source_type_counts':[{'source_type':k,'count':v} for k,v in source_counts.most_common()], 'competitors':[{'name':k,'count':v} for k,v in competitor_counts.most_common()]},
        'run_history':[],
        'methodology':{
            'visibility_principles':['Position/citation prominence, owned citation status, competitor displacement and source control are tracked at query level.'],
            'geo_preference_rules':PREFERENCE_RULES,
            'refresh_policy':'On rerun, preserve query ids, refresh top citations, recompute winning patterns and regenerate recommendations only where evidence changed.'
        }
    }
    write_json(root/'outputs/query_workbench/query_workbench.json', {'query_workbench':qwork})
    write_json(root/'outputs/frontend_report_bundle.json', bundle)
    write_json(root/'outputs/bodhi/preview_node_bundle.json', bundle)
    write_json(root/'outputs/dashboard/ai_visibility_dashboard_dataset.json', bundle)
    write_json(root/'outputs/actions/action_checklist.json', {'actions':actions})
    print(json.dumps({'status':'ready','run_id':run_id,'query_count':qcount,'owned_urls':len(owned_summary),'cms_recommendations':len(all_cms),'pr_opportunities':len(all_pr),'actions':len(actions),'output':'outputs/frontend_report_bundle.json'}, ensure_ascii=False, indent=2))

if __name__=='__main__': main()
