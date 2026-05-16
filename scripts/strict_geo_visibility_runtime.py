#!/usr/bin/env python3
"""Strict runtime scoring and action model for Bodhi AI visibility audit.

This script is intentionally dependency-free. It consumes Railway evidence files
already written under outputs/ and regenerates the derived audit artifacts with
stricter, evidence-first scoring.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

COMPETITOR_BRANDS = {
    "toyota": ["toyota", "トヨタ", "lexus", "レクサス"],
    "honda": ["honda", "ホンダ"],
    "mitsubishi": ["mitsubishi", "三菱"],
    "mazda": ["mazda", "マツダ"],
    "subaru": ["subaru", "スバル"],
    "suzuki": ["suzuki", "スズキ"],
    "daihatsu": ["daihatsu", "ダイハツ"],
}
NISSAN_TERMS = ["nissan", "日産", "ariya", "アリア", "leaf", "リーフ", "sakura", "サクラ", "serena", "セレナ", "x-trail", "xtrail", "エクストレイル", "note", "ノート", "e-power", "epower", "elgrand", "エルグランド", "roox", "ルークス", "clipper", "クリッパー"]
OWNED_DOMAIN_FRAGMENTS = ["nissan.co.jp", "nissan-global.com", "global.nissannews.com", "nissannews.com", "nissan-fs.co.jp"]
BOILERPLATE_TERMS = ["クルマを探す", "オーナーの方へ", "日産を知る", "mynissan", "サイトマップ", "プライバシーポリシー", "ご利用にあたって", "リコール情報", "faq/お問い合わせ", "セルフ見積り", "カタログ請求", "来店予約"]
QUESTION_MARKERS = ["?", "？", "faq", "よくある", "質問", "q:", "q.", "問", "answer", "回答"]
ANSWER_TERMS = ["range", "charging", "charge", "cost", "price", "warranty", "battery", "safety", "family", "seat", "isofix", "boot", "fuel", "hybrid", "lease", "finance", "航続", "充電", "価格", "費用", "保証", "バッテリー", "安全", "家族", "シート", "燃費", "ハイブリッド", "リース", "支払い", "補助金"]
PROOF_TERMS = ["warranty", "specification", "official", "safety", "test", "rating", "terms", "conditions", "保証", "諸元", "仕様", "公式", "安全", "試験", "評価", "条件", "注記", "国土交通省", "jncap", "nasva"]


def load_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def first_list(obj, keys):
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        return []
    for key in keys:
        val = obj.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            nested = first_list(val, keys)
            if nested:
                return nested
    return []


def to_text(value, limit=0):
    if value is None:
        s = ""
    elif isinstance(value, str):
        s = value
    elif isinstance(value, (int, float, bool)):
        s = str(value)
    elif isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if k.lower() in {"raw_html", "rendered_html", "html"}:
                continue
            tv = to_text(v)
            if tv:
                parts.append(tv)
        s = " ".join(parts)
    elif isinstance(value, (list, tuple, set)):
        s = " ".join(to_text(v) for v in value if v is not None)
    else:
        s = str(value)
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        return s[:limit]
    return s


def domain_of(url: str) -> str:
    try:
        d = urlparse(url or "").netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def is_owned_url(url: str) -> bool:
    d = domain_of(url)
    return any(frag in d for frag in OWNED_DOMAIN_FRAGMENTS)


def classify_source(url: str, raw: str = "") -> str:
    raw_l = (raw or "").lower()
    d = domain_of(url)
    if is_owned_url(url):
        return "owned_or_nissan_ecosystem"
    if any(x in d for x in ["toyota", "honda", "mitsubishi", "mazda", "subaru", "suzuki", "daihatsu", "lexus"]):
        return "competitor_owned"
    if any(x in d for x in ["reddit", "facebook", "youtube", "instagram", "tiktok", "x.com", "twitter"]):
        return "forum_social_video"
    if any(x in d for x in ["nasva", "mlit", "meti", "go.jp", "enecho"]):
        return "authority_body"
    if any(x in d for x in ["nikkei", "asahi", "recharged", "carwow", "parkers", "autonews", "greencarreports", "carsales", "daveyjapan", "szabo"]):
        return "publisher_review"
    if any(x in d for x in ["rakuten", "tc-v", "carmo", "mailmate", "gaijinpot", "brokerlink", "reform", "taiyoko"]):
        return "aggregator_marketplace" if "aggregator" in raw_l or "marketplace" in raw_l else "finance_or_insurance"
    if any(x in d for x in ["tepco", "evdays", "charging", "charge"]):
        return "partner_infrastructure"
    if "publisher" in raw_l or "news" in raw_l:
        return "publisher_review"
    if "forum" in raw_l or "social" in raw_l or "video" in raw_l:
        return "forum_social_video"
    if "competitor" in raw_l:
        return "competitor_owned"
    if "authority" in raw_l:
        return "authority_body"
    if "partner" in raw_l or "infrastructure" in raw_l:
        return "partner_infrastructure"
    return "other"


def competitor_mentions(text: str) -> dict:
    t = (text or "").lower()
    out = Counter()
    for brand, variants in COMPETITOR_BRANDS.items():
        if any(v.lower() in t for v in variants):
            out[brand] += 1
    return dict(out)


def nissan_mention(text: str) -> bool:
    t = (text or "").lower()
    return any(term.lower() in t for term in NISSAN_TERMS)


def query_type_of(qrow: dict, query: str) -> str:
    qt = (qrow.get("query_type") or qrow.get("type") or "").lower()
    if qt in {"branded", "non_branded", "non-branded"}:
        return "non_branded" if qt == "non-branded" else qt
    q = (query or "").lower()
    return "branded" if nissan_mention(q) else "non_branded"


def find_refs(row: dict) -> list:
    candidates = []
    for key in ["citations", "references", "sources", "structured_snippets", "cited_sources", "organic_results", "items"]:
        v = row.get(key) if isinstance(row, dict) else None
        if isinstance(v, list):
            candidates.extend(v)
    # Some compact rows keep citations under response/citation arrays.
    for key in ["answer", "response", "google_ai_mode", "metadata"]:
        v = row.get(key) if isinstance(row, dict) else None
        if isinstance(v, dict):
            candidates.extend(find_refs(v))
    cleaned = []
    for item in candidates:
        if isinstance(item, dict):
            url = item.get("url") or item.get("source_url") or item.get("link") or item.get("href")
            if url:
                cleaned.append(item)
    return cleaned


def query_id(row, idx):
    return str(row.get("query_id") or row.get("id") or f"q{idx+1:03d}")


def text_metrics(text: str) -> dict:
    t = text or ""
    lower = t.lower()
    # Japanese tokenisation without external libs: use latin word count plus CJK char count.
    latin_words = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9\-]{1,}", t)
    cjk_chars = re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", t)
    numeric_evidence = re.findall(r"(?:\d+[\d,\.]*\s?(?:km|kwh|kw|円|万円|年|％|%|l/100km|km/l|人|席|mm|kg|months?|years?))", lower)
    headings = len(re.findall(r"(?:^|\n)#{1,3}\s+", t))
    tables = len(re.findall(r"\|[^\n]+\|", t))
    links = len(re.findall(r"https?://|\[[^\]]+\]\(", t))
    boilerplate_hits = sum(lower.count(x.lower()) for x in BOILERPLATE_TERMS)
    question_hits = sum(lower.count(x.lower()) for x in QUESTION_MARKERS)
    answer_hits = sum(lower.count(x.lower()) for x in ANSWER_TERMS)
    proof_hits = sum(lower.count(x.lower()) for x in PROOF_TERMS)
    schema_types = re.findall(r"Schema types:\s*([^\n#]+)", t, flags=re.I)
    schema_text = " ".join(schema_types).lower()
    return {
        "latin_words": len(latin_words),
        "cjk_chars": len(cjk_chars),
        "substantive_units": len(latin_words) + len(cjk_chars) / 2.2,
        "numeric_evidence_count": len(numeric_evidence),
        "headings": headings,
        "tables": tables,
        "links": links,
        "boilerplate_hits": boilerplate_hits,
        "question_hits": question_hits,
        "answer_hits": answer_hits,
        "proof_hits": proof_hits,
        "schema_text": schema_text,
        "has_jsonld": "json-ld" in lower or "schema types:" in lower,
        "has_faq_schema": "faqpage" in schema_text,
        "has_product_schema": "product" in schema_text,
        "has_offer_schema": "offer" in schema_text or "offercatalog" in schema_text,
        "has_dates": bool(re.search(r"20[2-3][0-9]|令和\d+年|last updated|更新日|valid until|応募締切", lower)),
    }


def query_terms(query: str) -> list:
    q = (query or "").lower()
    terms = [w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", q) if w not in {"the", "and", "for", "with", "what", "how", "does", "are", "which", "japan", "japanese", "nissan"}]
    # Add Japanese category terms through English journey proxies.
    proxies = []
    if any(w in q for w in ["charge", "charging", "range", "battery", "ev"]):
        proxies += ["充電", "航続", "バッテリー", "電気"]
    if any(w in q for w in ["family", "seat", "isofix", "boot", "stroller"]):
        proxies += ["シート", "室内", "荷室", "家族", "チャイルド"]
    if any(w in q for w in ["finance", "lease", "cost", "payment", "subsidy", "insurance", "resale"]):
        proxies += ["支払い", "リース", "費用", "価格", "補助金", "保険"]
    if any(w in q for w in ["safety", "adas", "crash", "reliability", "warranty"]):
        proxies += ["安全", "保証", "衝突", "信頼"]
    if any(w in q for w in ["hybrid", "fuel", "e-power", "powertrain"]):
        proxies += ["ハイブリッド", "燃費", "e-power", "パワートレイン"]
    return list(dict.fromkeys(terms + proxies))[:20]


def strict_geo_score(page: dict, related_queries: list[dict]) -> tuple[int, dict, list, dict]:
    title = to_text(page.get("title"), 300)
    desc = to_text(page.get("description") or page.get("meta_description"), 600)
    text = "\n".join([
        title,
        desc,
        to_text(page.get("markdown") or page.get("text") or page.get("content") or page.get("markdown_excerpt"), 30000),
    ])
    lower = text.lower()
    m = text_metrics(text)
    queries_text = " ".join(to_text(q.get("query") or q) for q in related_queries if q)
    terms = query_terms(queries_text or to_text(page.get("related_queries_seed") or page.get("journey_category") or page.get("brand_topic_category")))
    overlap = sum(1 for term in terms if term and term.lower() in lower)
    first_1200 = lower[:1200]
    answer_first = any(term in first_1200 for term in ANSWER_TERMS) and overlap >= 1
    # Penalise pages that are mostly nav/legal boilerplate.
    boilerplate_penalty = 4 if m["boilerplate_hits"] >= 8 else (2 if m["boilerplate_hits"] >= 4 else 0)
    weak_content = m["substantive_units"] < 350 or (len(text) < 1500 and m["numeric_evidence_count"] < 2)

    # 1) Content Clarity: strict answer-first + readable buyer guidance.
    # No easy marks for long official/product catalogue pages: the page must visibly answer the mapped query early.
    clarity = 0
    if m["substantive_units"] >= 500:
        clarity += 3
    if m["substantive_units"] >= 1200:
        clarity += 2
    if answer_first:
        clarity += 6
    if overlap >= 3:
        clarity += 3
    if overlap >= 6:
        clarity += 2
    if m["headings"] >= 4:
        clarity += 2
    if m["answer_hits"] >= 6:
        clarity += 2
    if not answer_first:
        clarity = min(clarity, 8)
    clarity = max(0, min(20, clarity - boilerplate_penalty))

    # 2) Semantic Depth: stats/comparisons/details matched to query family.
    semantic = 0
    if overlap >= 2:
        semantic += 3
    if overlap >= 5:
        semantic += 3
    if overlap >= 8:
        semantic += 2
    semantic += min(4, m["numeric_evidence_count"])
    if m["tables"] >= 2:
        semantic += 3
    if any(x in lower for x in ["比較", "comparison", "versus", "vs", "グレード間", "対象", "条件"]):
        semantic += 2
    if m["proof_hits"] >= 5:
        semantic += 3
    if m["numeric_evidence_count"] < 2 and m["tables"] < 1:
        semantic = min(semantic, 9)
    semantic = min(20, semantic)

    # 3) Structured Data: schema must be detected and relevant. Tables do not substitute for schema.
    structured = 0
    if m["has_jsonld"]:
        structured += 3
    if m["has_product_schema"]:
        structured += 4
    if m["has_offer_schema"]:
        structured += 4
    if m["has_faq_schema"]:
        structured += 8
    if m["tables"] >= 2:
        structured += 1
    if not (m["has_product_schema"] or m["has_offer_schema"] or m["has_faq_schema"]):
        structured = min(structured, 6)
    structured = min(20, structured)

    # 4) EEAT: official brand is only a small base; require proof, terms, dates, sources.
    eeat = 1 if is_owned_url(page.get("url") or "") else 0
    if m["proof_hits"] >= 3:
        eeat += 3
    if m["proof_hits"] >= 6:
        eeat += 2
    if any(x in lower for x in ["保証", "warranty", "terms", "条件", "注記", "販売店", "dealer"]):
        eeat += 3
    if any(x in lower for x in ["国土交通省", "jncap", "nasva", "mlit", "meti", "審査値", "試験条件"]):
        eeat += 5
    if m["links"] >= 8:
        eeat += 1
    if m["has_dates"]:
        eeat += 2
    if m["proof_hits"] < 3:
        eeat = min(eeat, 7)
    eeat = min(20, eeat)

    # 5) Freshness & index: date/validity proof is required for finance, safety, warranty, subsidy and current-offer content.
    freshness = 0
    if "robots meta: index" in lower or "index,follow" in lower:
        freshness += 2
    if m["has_dates"]:
        freshness += 5
    if any(x in lower for x in ["2026", "2025", "応募締切", "valid until", "last updated", "更新"]):
        freshness += 4
    if "canonical url:" in lower:
        freshness += 1
    if "llms.txt" in lower:
        freshness += 2
    if not m["has_dates"]:
        freshness = min(freshness, 5)
    freshness = min(20, freshness)

    # 6) FAQ readiness: only real Q&A/FAQ markers count. Do not award inferred FAQ readiness.
    faq = 0
    if m["question_hits"] >= 2:
        faq += 4
    if m["question_hits"] >= 5:
        faq += 2
    if m["has_faq_schema"]:
        faq += 10
    if any(x in lower for x in ["よくある", "faq", "質問", "q&a"]):
        faq += 3
    if answer_first and m["question_hits"] >= 1:
        faq += 1
    if not m["has_faq_schema"]:
        faq = min(faq, 8)
    faq = min(20, faq)

    dims = {
        "content_clarity": int(clarity),
        "semantic_depth": int(semantic),
        "structured_data": int(structured),
        "eeat_signals": int(eeat),
        "freshness_index": int(freshness),
        "faq_readiness": int(faq),
    }
    # Hard caps, aligned to the strict 6x20 GEO framework used in the original Firecrawl audit.
    # A page cannot reach the upper bands by being a long official page alone. It must visibly answer
    # the mapped buyer query, provide evidence/proof, be extractable via FAQ/schema patterns and show
    # freshness/validity signals where claims, finance, safety, warranty or incentives are involved.
    score = sum(dims.values())

    related_query_types = {query_type_of(q, to_text(q.get("query") if isinstance(q, dict) else q)) for q in related_queries if q}
    has_branded_query = "branded" in related_query_types
    has_nonbranded_query = "non_branded" in related_query_types or not has_branded_query
    related_target_cited = any((q.get("owned_target_page_cited") is True) for q in related_queries if isinstance(q, dict))
    related_has_competitor = any((q.get("competitor_led") is True or (q.get("competitor_brands_detected") or {})) for q in related_queries if isinstance(q, dict))
    related_count = len([q for q in related_queries if q])
    url_path = urlparse(page.get("url") or "").path.lower().rstrip("/")
    broad_catalogue_page = bool(re.search(r"/vehicles/new/[^/]+(?:\.html)?$", url_path))
    trust_weak = dims["eeat_signals"] < 12 or m["proof_hits"] < 4
    schema_weak = dims["structured_data"] < 10
    faq_weak = dims["faq_readiness"] < 10
    freshness_weak = dims["freshness_index"] < 10
    answer_weak = (not answer_first) or overlap < 3
    proof_weak = m["numeric_evidence_count"] < 3 and m["proof_hits"] < 4
    citation_weak = not related_target_cited
    finance_or_legal_intent = any(x in lower for x in ["残価", "おまとめ", "サブスク", "金利", "保証", "補助金", "保険", "車検", "契約", "条件", "warranty", "finance", "lease", "insurance", "subsidy", "安全", "safety", "battery", "バッテリー", "充電", "range", "航続"])

    cap_reasons = []
    def apply_cap(value, reason):
        nonlocal score
        if score > value:
            cap_reasons.append(reason)
            score = value

    if weak_content:
        apply_cap(28, "weak substantive content / extraction payload too thin")
    if overlap == 0:
        apply_cap(36, "no mapped-query term overlap")
    if answer_weak:
        apply_cap(50, "missing answer-first buyer-query coverage")
    if has_branded_query and proof_weak:
        apply_cap(46, "branded query page lacks sufficient visible evidence/proof in the content")
    if has_nonbranded_query and trust_weak:
        apply_cap(44, "non-branded query requires strong trust/evidence before AI systems should cite it")
    if schema_weak:
        apply_cap(62, "weak structured data / machine readability")
    if faq_weak:
        apply_cap(58, "weak FAQ or Q&A extractability")
    if trust_weak:
        apply_cap(56, "weak proof / EEAT evidence")
    if citation_weak and schema_weak and faq_weak:
        apply_cap(54, "no owned target-page citation and weak schema/FAQ extractability")
    if citation_weak and broad_catalogue_page:
        apply_cap(60, "broad catalogue page is not yet proven as an AI-cited target page")
    if related_has_competitor and citation_weak:
        apply_cap(55, "competitor-led mapped queries require stronger owned-page proof before higher readiness")
    if finance_or_legal_intent and freshness_weak:
        apply_cap(50, "finance/safety/warranty/EV-incentive content lacks strong freshness or validity signals")
    if answer_weak and schema_weak and faq_weak:
        apply_cap(44, "combined answer-first, schema and FAQ gaps")
    if answer_weak and trust_weak and has_nonbranded_query:
        apply_cap(40, "non-branded query has both answer and trust gaps")
    if (not m["has_faq_schema"]) and (not m["has_product_schema"]) and citation_weak:
        apply_cap(52, "no FAQ/Product structured data and no observed target-page citation")

    # Dimension gaps are strict: 10/20 is not enough for final quality, only for minimum signal.
    gaps = [k for k, v in dims.items() if v < 12]
    diagnostics = {
        "substantive_units": round(m["substantive_units"], 1),
        "numeric_evidence_count": m["numeric_evidence_count"],
        "query_term_overlap": overlap,
        "answer_first_detected": bool(answer_first),
        "boilerplate_hits": m["boilerplate_hits"],
        "cap_reasons": cap_reasons,
        "related_query_types": sorted(related_query_types),
        "related_target_cited": bool(related_target_cited),
        "related_has_competitor": bool(related_has_competitor),
        "related_count": related_count,
        "broad_catalogue_page": bool(broad_catalogue_page),
        "answer_weak": bool(answer_weak),
        "trust_weak": bool(trust_weak),
        "schema_weak": bool(schema_weak),
        "faq_weak": bool(faq_weak),
        "freshness_weak": bool(freshness_weak),
        "strict_scoring_notes": [
            "Official brand ownership alone does not create high GEO readiness.",
            "Scores are capped where no answer-first mapped-query coverage is detected.",
            "Branded query pages are penalised when page content lacks visible evidence/proof.",
            "Non-branded queries require stronger trust and evidence because AI answers are unlikely to cite owned pages without proof.",
            "FAQ readiness requires visible FAQ/Q&A evidence, not inferred buyer questions.",
        ],
    }
    return int(score), dims, gaps, diagnostics


def strict_ai_visibility(row: dict, idx: int, target_urls: list[str]) -> tuple[int, dict]:
    q = to_text(row.get("query") or row.get("query_text") or row.get("prompt"), 1000)
    qt = query_type_of(row, q)
    refs = find_refs(row)
    answer_text = to_text({k: row.get(k) for k in ["answer", "response", "raw_response_text", "summary", "text", "content"]}, 12000)
    target_norm = {u.rstrip("/").lower() for u in target_urls if u}
    owned_target_citations = []
    owned_domain_citations = []
    competitor_citations = []
    publisher_citations = []
    citations = []
    comp_counts = Counter(competitor_mentions(answer_text))
    for pos, ref in enumerate(refs, 1):
        url = ref.get("url") or ref.get("source_url") or ref.get("link") or ref.get("href") or ""
        d = domain_of(url)
        st = classify_source(url, ref.get("source_type") or ref.get("raw_source_type") or "")
        exact_owned = url.rstrip("/").lower() in target_norm
        owned_domain = is_owned_url(url)
        cbrands = competitor_mentions(" ".join([d, url, to_text(ref.get("title")), to_text(ref.get("snippet") or ref.get("text"))]))
        for b, c in cbrands.items():
            comp_counts[b] += c
        c = {
            "citation_position": pos,
            "title": to_text(ref.get("title") or ref.get("source_name") or d, 300),
            "url": url,
            "domain": d,
            "snippet": to_text(ref.get("snippet") or ref.get("text") or ref.get("description"), 600),
            "source_type": st,
            "is_owned_domain": bool(owned_domain),
            "is_owned_target_page": bool(exact_owned),
            "is_competitor": bool(cbrands or st == "competitor_owned"),
        }
        citations.append(c)
        if exact_owned:
            owned_target_citations.append(c)
        elif owned_domain:
            owned_domain_citations.append(c)
        if c["is_competitor"]:
            competitor_citations.append(c)
        if st in {"publisher_review", "authority_body", "partner_infrastructure", "aggregator_marketplace", "forum_social_video", "other"}:
            publisher_citations.append(c)

    brand_mentioned = nissan_mention(answer_text) or any(nissan_mention(to_text(c)) for c in citations)
    top_target_pos = min([c["citation_position"] for c in owned_target_citations], default=None)
    top_owned_pos = min([c["citation_position"] for c in owned_domain_citations], default=None)
    top_comp_pos = min([c["citation_position"] for c in competitor_citations], default=None)

    # Evidence-first score: exact owned target citation is the primary signal.
    score = 0
    if top_target_pos is not None:
        score += 42 if top_target_pos <= 3 else (32 if top_target_pos <= 8 else 22)
        score += min(12, len(owned_target_citations) * 4)
    if owned_domain_citations:
        score += 8 if qt == "branded" else 3
        if top_owned_pos and top_owned_pos <= 5:
            score += 3 if qt == "branded" else 1
    if brand_mentioned:
        score += 10 if qt == "branded" else 4
    if not owned_target_citations and not owned_domain_citations and brand_mentioned:
        score = min(score, 12 if qt == "branded" else 6)
    if not owned_target_citations and not brand_mentioned:
        score = min(score, 5)
    # Competitor displacement: heavy penalty for non-branded queries.
    comp_penalty = 0
    if competitor_citations or comp_counts:
        comp_penalty += min(22, len(competitor_citations) * 5 + sum(comp_counts.values()) * 3)
        if top_comp_pos and top_comp_pos <= 3:
            comp_penalty += 8
        if qt == "non_branded":
            comp_penalty += 6
    score = max(0, min(100, score - comp_penalty))

    if owned_target_citations:
        status = "owned_target_cited"
    elif competitor_citations and not owned_domain_citations:
        status = "competitor_led"
    elif owned_domain_citations:
        status = "owned_domain_cited"
    elif brand_mentioned:
        status = "brand_or_model_mentioned_only"
    else:
        status = "external_led"

    details = {
        "query_id": query_id(row, idx),
        "query": q,
        "query_type": qt,
        "brand_topic_category": row.get("brand_topic_category") or row.get("journey_category") or row.get("category"),
        "ai_visibility_score": int(score),
        "visibility_status": status,
        "owned_target_page_cited": bool(owned_target_citations),
        "owned_target_page_citations": len(owned_target_citations),
        "owned_domain_citations": len(owned_domain_citations),
        "brand_or_model_mentioned": bool(brand_mentioned),
        "competitor_mentions_count": sum(comp_counts.values()),
        "competitor_citation_count": len(competitor_citations),
        "competitor_brands_detected": dict(comp_counts),
        "competitor_led": bool(status == "competitor_led" or (competitor_citations and not owned_target_citations)),
        "citations": citations,
        "score_components": {
            "owned_target_citation_primary": bool(owned_target_citations),
            "owned_domain_partial_credit": len(owned_domain_citations),
            "brand_model_mention_only_credit": bool(brand_mentioned and not owned_target_citations),
            "competitor_displacement_penalty": comp_penalty,
        },
    }
    return int(score), details



def clean_env_value(value, default=""):
    if value is None:
        return default
    v = str(value).strip()
    for _ in range(4):
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1].strip()
        else:
            break
    return v if v != "" else default


def env_int(*names, default=0):
    for name in names:
        raw = os.environ.get(name)
        cleaned = clean_env_value(raw, None)
        if cleaned is not None:
            return int(float(cleaned))
    return int(default)

def main():
    project = Path(clean_env_value(os.environ.get("PROJECT_DIR"), ".")).resolve()
    brand = clean_env_value(os.environ.get("BRAND"), "Nissan")
    market = clean_env_value(os.environ.get("MARKET"), "Japan")
    domain = clean_env_value(os.environ.get("DOMAIN"), "https://www.nissan.co.jp")
    max_external_per_query = env_int("MAX_EXTERNAL_SOURCES_PER_QUERY", "MAX_EXTERNAL_PER_QUERY", default=5)

    audit = load_json(project / "outputs/audit_context/audit_context.json", {}) or load_json(project / "inputs/audit_context.json", {}) or {}
    evidence = load_json(project / "outputs/evidence_scope/evidence_scope.json", {}) or {}
    google = load_json(project / "outputs/google_ai_mode/google_ai_mode_compact.json", {}) or {}
    owned_full = load_json(project / "outputs/content_intelligence/owned_pages_full.json", {}) or {}
    external_full = load_json(project / "outputs/external_pages/external_pages_full.json", {}) or {}
    source_class = load_json(project / "outputs/source_landscape/source_classification.json", {}) or {}

    query_rows = first_list(audit, ["queries", "query_portfolio"]) or first_list(evidence, ["queries"]) or first_list(google, ["rows", "queries", "items"])
    google_rows = first_list(google, ["rows", "queries", "items"]) or query_rows
    owned_pages = first_list(owned_full, ["pages", "owned_pages", "items"])
    external_pages = first_list(external_full, ["external_pages", "pages", "items", "sources"])
    audit_pages = first_list(audit, ["pages", "owned_urls", "candidate_owned_pages"])
    target_urls = [p.get("url") for p in audit_pages if isinstance(p, dict) and p.get("url")]
    if not target_urls:
        target_urls = [p.get("url") for p in owned_pages if isinstance(p, dict) and p.get("url")]

    # Normalise query rows by id and query text.
    q_by_text = {to_text(q.get("query") or q.get("query_text") or q.get("prompt")).lower(): q for q in query_rows if isinstance(q, dict)}
    query_matrix = []
    score_rows = []
    source_rows = []
    source_counts = Counter()
    competitor_query_rows = []
    nissan_led = competitor_led = external_led = brand_only = owned_domain_only = owned_target = 0

    for idx, row in enumerate(google_rows):
        if not isinstance(row, dict):
            continue
        qtext = to_text(row.get("query") or row.get("query_text") or row.get("prompt"), 1000)
        merged = dict(q_by_text.get(qtext.lower(), {}))
        merged.update(row)
        score, details = strict_ai_visibility(merged, idx, target_urls)
        details["citations"] = details["citations"][:max_external_per_query]
        query_matrix.append(details)
        score_rows.append({
            "query_id": details["query_id"],
            "query": details["query"],
            "query_type": details["query_type"],
            "brand_topic_category": details.get("brand_topic_category"),
            "ai_visibility_score": score,
            "visibility_status": details["visibility_status"],
            "owned_target_page_citation": 45 if details["owned_target_page_cited"] else 0,
            "owned_domain_partial_credit": min(12, details["owned_domain_citations"] * 4),
            "brand_or_model_mention_credit": 8 if details["brand_or_model_mentioned"] else 0,
            "competitor_displacement_penalty": details["score_components"]["competitor_displacement_penalty"],
            "competitor_citation_count": details["competitor_citation_count"],
            "competitor_brands_detected": details["competitor_brands_detected"],
        })
        if details["owned_target_page_cited"]:
            owned_target += 1
        elif details["visibility_status"] == "owned_domain_cited":
            owned_domain_only += 1
        elif details["visibility_status"] == "brand_or_model_mentioned_only":
            brand_only += 1
        elif details["competitor_led"]:
            competitor_led += 1
        else:
            external_led += 1
        if details["owned_target_page_cited"] or details["owned_domain_citations"]:
            nissan_led += 1
        if details["competitor_citation_count"] or details["competitor_mentions_count"]:
            competitor_query_rows.append(details)
        for c in details["citations"]:
            source_counts[c["source_type"]] += 1
            source_rows.append({
                "query_id": details["query_id"],
                "query": details["query"],
                "source_url": c["url"],
                "source_domain": c["domain"],
                "source_type": c["source_type"],
                "source_category": c["source_type"],
                "citation_position": c["citation_position"],
                "title": c["title"],
                "snippet": c["snippet"],
                "is_owned_domain": c["is_owned_domain"],
                "is_owned_target_page": c["is_owned_target_page"],
                "is_competitor": c["is_competitor"],
            })

    # If source_class already has richer source rows, retain counts as secondary context.
    existing_sources = first_list(source_class, ["sources"])
    if existing_sources:
        for s in existing_sources:
            if isinstance(s, dict):
                st = s.get("source_category") or s.get("source_type") or classify_source(s.get("source_url") or s.get("url") or "", s.get("raw_source_type") or "")
                source_counts[st] += 0

    # Build related-query map from evidence_scope where available.
    evidence_queries = first_list(evidence, ["queries"])
    page_to_queries = defaultdict(list)
    for qidx, q in enumerate(evidence_queries):
        if not isinstance(q, dict):
            continue
        qtext = q.get("query") or q.get("query_text")
        qid = q.get("query_id") or q.get("id") or f"q{qidx+1:03d}"
        # Backfill ids into the in-memory evidence row so downstream payload builders
        # can join by query_id even when Railway compact evidence omitted it.
        q["query_id"] = qid
        linked = first_list(q, ["owned_pages", "mapped_owned_pages", "owned_page_links", "target_pages", "pages"])
        for item in linked:
            if isinstance(item, dict):
                u = item.get("url") or item.get("page_url") or item.get("target_url")
            else:
                u = str(item)
            if u:
                q_vis = next((m for m in query_matrix if m.get("query_id") == qid or (qtext and m.get("query") == qtext)), {})
                page_to_queries[u.rstrip("/")].append({
                    "query_id": qid,
                    "query": qtext,
                    "brand_topic_category": q.get("brand_topic_category") or q.get("journey_category"),
                    "query_type": q_vis.get("query_type") or q.get("query_type"),
                    "visibility_status": q_vis.get("visibility_status"),
                    "owned_target_page_cited": q_vis.get("owned_target_page_cited"),
                    "competitor_led": q_vis.get("competitor_led"),
                    "competitor_brands_detected": q_vis.get("competitor_brands_detected", {}),
                })
    # Fallback: use category matching from audit queries.
    queries_by_cat = defaultdict(list)
    for q in query_rows:
        if isinstance(q, dict):
            queries_by_cat[q.get("brand_topic_category") or q.get("journey_category") or ""].append(q)

    owned_scores = []
    for p in owned_pages:
        if not isinstance(p, dict):
            continue
        url = p.get("url") or p.get("page_url") or ""
        cat = p.get("brand_topic_category") or p.get("journey_category") or ""
        related = page_to_queries.get(url.rstrip("/")) or queries_by_cat.get(cat, [])[:3]
        score, dims, gaps, diagnostics = strict_geo_score(p, related)
        confidence = "high" if diagnostics["substantive_units"] >= 350 and url else "low"
        owned_scores.append({
            "url": url,
            "journey_category": cat,
            "geo_readiness_score": score,
            "score_120": score,
            "score_band": "critical" if score <= 30 else ("low" if score <= 55 else ("moderate" if score <= 75 else ("good" if score <= 95 else "strong"))),
            "dimensions": dims,
            "dimension_gaps": gaps,
            "strict_diagnostics": diagnostics,
            "crawl_status": p.get("crawl_status") or p.get("status"),
            "extraction_status": p.get("extraction_status"),
            "markdown_chars": p.get("markdown_chars") or len(to_text(p.get("markdown") or p.get("text") or p.get("content"))),
            "title": p.get("title") or p.get("page_title") or "",
            "recommendation_confidence": confidence,
            "related_queries": related[:5],
        })

    external_scores = []
    for p in external_pages:
        if not isinstance(p, dict):
            continue
        url = p.get("url") or p.get("source_url") or ""
        st = classify_source(url, p.get("source_type") or p.get("raw_source_type") or "")
        text = " ".join([to_text(p.get("title")), to_text(p.get("description")), to_text(p.get("snippet")), to_text(p.get("markdown"), 5000)])
        tm = text_metrics(text)
        # Keep external benchmark strict too: social is evidence, but lower authority.
        authority = {"authority_body": 18, "publisher_review": 15, "partner_infrastructure": 13, "competitor_owned": 10, "aggregator_marketplace": 10, "finance_or_insurance": 9, "owned_or_nissan_ecosystem": 12, "forum_social_video": 5, "other": 6}.get(st, 5)
        packaging = min(20, 4 + (5 if tm["answer_hits"] >= 2 else 0) + min(5, tm["numeric_evidence_count"]) + (4 if tm["tables"] else 0))
        proof = min(20, authority + min(5, tm["proof_hits"]))
        query_match = min(20, 4 + min(8, tm["answer_hits"]) + min(8, tm["numeric_evidence_count"]))
        external_score = min(100, query_match + packaging + proof + min(15, tm["substantive_units"] / 180) + (5 if tm["has_dates"] else 0))
        citation_influence = int(round(min(100, authority * 2 + min(30, tm["answer_hits"] * 3 + tm["numeric_evidence_count"] * 2) + (10 if tm["has_dates"] else 0))))
        external_scores.append({
            "url": url,
            "title": p.get("title", ""),
            "source_domain": p.get("source_domain") or domain_of(url),
            "source_type": st,
            "external_benchmark_score": int(round(external_score)),
            "external_citation_influence_score": citation_influence,
            "winning_content_pattern_score": int(round(external_score)),
            "query_answer_match": int(query_match),
            "answer_packaging": int(packaging),
            "evidence_and_proof": int(proof),
            "comparison_utility": 8 if "compare" in text.lower() or "比較" in text else 3,
            "conversational_coverage": 8 if st == "forum_social_video" else 5,
            "machine_readability": 8 if tm["tables"] or tm["headings"] else 4,
            "freshness_and_market_relevance": 5 if tm["has_dates"] else 2,
            "brand_topic_category": p.get("brand_topic_category") or p.get("journey_category"),
        })

    avg_owned = round(sum(x["score_120"] for x in owned_scores) / max(1, len(owned_scores)), 1)
    avg_external = round(sum(x["external_benchmark_score"] for x in external_scores) / max(1, len(external_scores)), 1)
    avg_external_influence = round(sum(x.get("external_citation_influence_score", 0) for x in external_scores) / max(1, len(external_scores)), 1)
    avg_visibility = round(sum(x["ai_visibility_score"] for x in score_rows) / max(1, len(score_rows)), 1)

    write_json(project / "outputs/visibility/visibility_matrix.json", {"brand": brand, "market": market, "queries": query_matrix, "rows": query_matrix})
    write_json(project / "outputs/visibility/ai_visibility_scores.json", {"brand": brand, "market": market, "scores": score_rows, "rows": score_rows, "average_ai_visibility_score": avg_visibility})
    write_json(project / "outputs/source_landscape/source_classification.json", {"brand": brand, "market": market, "sources": source_rows, "source_type_counts": dict(source_counts)})
    write_json(project / "outputs/source_landscape/competitor_publisher_landscape.json", {
        "brand": brand,
        "market": market,
        "source_mix": dict(source_counts),
        "competitor_presence": {
            "competitor_led_query_count": competitor_led,
            "queries_with_competitor_presence": len(competitor_query_rows),
            "competitor_brands": dict(sum((Counter(r.get("competitor_brands_detected", {})) for r in competitor_query_rows), Counter())),
        },
        "summary": "Strict scoring: competitor-led visibility is separated from Nissan owned-domain and owned-target visibility.",
    })
    write_json(project / "outputs/page_scores/owned_page_scores.json", {"brand": brand, "market": market, "pages": owned_scores, "owned_pages": owned_scores, "scoring_framework": "strict_geo_6x20_v3_no_easy_marks"})
    write_json(project / "outputs/page_scores/external_page_scores.json", {"brand": brand, "market": market, "pages": external_scores, "external_pages": external_scores})

    winning = [{"source_type": st, "citation_count": c, "winning_pattern": "External source is observed in AI citations; use its answer format, proof pattern and extractability as benchmark input for owned-page CMS changes."} for st, c in source_counts.most_common()]
    write_json(project / "outputs/benchmark/winning_source_patterns.json", {"brand": brand, "market": market, "patterns": winning})

    owned_by_cat = defaultdict(list)
    for o in owned_scores:
        owned_by_cat[o.get("journey_category") or ""].append(o)
    external_by_cat = defaultdict(list)
    for e in external_scores:
        external_by_cat[e.get("brand_topic_category") or ""].append(e)
    bench = []
    for m in query_matrix:
        cat = m.get("brand_topic_category") or ""
        oscores = owned_by_cat.get(cat) or owned_scores
        escores = external_by_cat.get(cat) or external_scores
        oavg = round(sum(x["score_120"] for x in oscores) / max(1, len(oscores)), 1)
        eavg = round(sum(x["external_benchmark_score"] for x in escores) / max(1, len(escores)), 1)
        gap = max(0, round(eavg - oavg, 1))
        bench.append({
            "query_id": m.get("query_id"),
            "query": m.get("query"),
            "query_type": m.get("query_type"),
            "visibility_status": m.get("visibility_status"),
            "owned_target_page_cited": m.get("owned_target_page_cited"),
            "brand_or_model_mentioned": m.get("brand_or_model_mentioned"),
            "competitor_led": m.get("competitor_led"),
            "competitor_brands_detected": m.get("competitor_brands_detected"),
            "winning_external_source_types": list({x.get("source_type") for x in escores if x.get("source_type")})[:5],
            "owned_geo_score_120": oavg,
            "external_benchmark_score": eavg,
            "external_citation_influence_score": eavg,
            "source_preference_gap": gap,
            "gap_severity": "material" if gap >= 15 else ("moderate" if gap >= 7 else "low"),
            "gap_reasons": [
                "Owned target page is not cited in AI answer" if not m.get("owned_target_page_cited") else "Owned target page cited but extractability can improve",
                "Non-branded queries receive little or no owned-credit unless Nissan target pages are cited",
                "Competitor and third-party sources are separated from Nissan-owned visibility",
            ],
        })
    write_json(project / "outputs/benchmark/source_preference_benchmark.json", {"brand": brand, "market": market, "queries": bench, "rows": bench, "average_owned_geo_score": avg_owned, "average_external_benchmark_score": avg_external, "average_external_citation_influence_score": avg_external_influence, "metric_note": "External benchmark is not a GEO score for third-party pages. It captures observed citation influence and winning content patterns to inform owned-page CMS remediation."})
    write_json(project / "outputs/benchmark/owned_vs_external_gap_analysis.json", {"brand": brand, "market": market, "gaps": bench, "rows": bench})

    recs = []
    for o in owned_scores:
        if o.get("recommendation_confidence") == "low":
            continue
        gaps = o.get("dimension_gaps") or []
        recs.append({
            "page_url": o.get("url"),
            "journey_category": o.get("journey_category"),
            "recommendation_confidence": "high" if gaps else "medium",
            "owned_geo_readiness": {"score_120": o.get("score_120"), "score_band": o.get("score_band"), "dimensions": o.get("dimensions"), "dimension_gaps": gaps},
            "related_queries": o.get("related_queries", [])[:5],
            "ai_visibility_context": {"visibility_status": "external_led_or_brand_only_until_target_page_is_cited"},
            "benchmark_gap": {"primary_gap": "Owned page must answer mapped buyer queries directly and visibly before it can be treated as GEO-ready.", "external_winning_pattern": "External winners are cited because they provide extractable answers, numeric evidence, comparison framing or third-party authority."},
            "recommended_html_changes": [{
                "recommendation_id": "geo_answer_summary",
                "priority": "P1" if o.get("score_120", 0) < 55 else "P2",
                "html_element": "section",
                "cms_module_type": "answer_first_summary_faq",
                "placement": "below hero / above detailed copy",
                "proposed_heading": "Answer the main buyer question directly",
                "brief_for_bodhi": "Create a page-specific, evidence-safe answer-first module using the owned page extract, mapped queries and visible facts only.",
                "content_requirements": ["Do not invent claims", "Use Japan-market caveats", "Include one concise Q&A only when answerable from the page", "Make the answer extractable for AI citations"],
                "schema_recommendation": {"type": "FAQPage", "required": "if Q&A is published"},
                "validation_required": ["Product", "Legal"],
                "expected_gap_closed": ["content_clarity", "query_answer_match", "faq_readiness"],
            }],
        })
    write_json(project / "outputs/recommendations/owned_page_content_recommendations.json", {"brand": brand, "market": market, "recommendations": recs, "pages": recs})
    write_json(project / "outputs/recommendations/cms_content_generation_briefs.json", {"brand": brand, "market": market, "briefs": recs, "brief_count": len(recs)})

    pr = []
    for st, count in source_counts.most_common(10):
        pr.append({
            "journey_category": "cross-journey",
            "source_gap": f"AI answers currently rely on {st} sources.",
            "opportunity_type": "source_landscape",
            "recommended_pr_action": "Create validated, third-party-referenceable proof assets and publisher explainers; do not rely on community seeding as a primary tactic.",
            "target_source_types": [st],
            "priority": "P1" if count >= 5 else "P2",
            "why_it_matters": "External authority and publisher sources are shaping AI answers; Nissan-owned target pages need corroborating citations and cleaner extractable answers.",
        })
    write_json(project / "outputs/pr_publisher_opportunities/pr_opportunity_plan.json", {"brand": brand, "market": market, "opportunities": pr})

    kpis = {
        "query_count": len(query_matrix),
        "owned_page_count": len(owned_scores),
        "external_source_count": len(external_scores),
        "average_ai_visibility_score": avg_visibility,
        "ai_visibility_score": avg_visibility,
        "average_owned_geo_score_120": avg_owned,
        "average_external_benchmark_score": avg_external,
        "average_external_citation_influence_score": avg_external_influence,
        "external_benchmark_metric_note": "This is not a third-party GEO quality score. It reflects external citation influence and content patterns observed in AI answers for use in owned-page remediation.",
        "owned_target_page_citations": sum(1 for m in query_matrix if m.get("owned_target_page_cited")),
        "owned_domain_citations": sum(m.get("owned_domain_citations", 0) for m in query_matrix),
        "brand_or_model_mention_only_query_count": brand_only,
        "owned_domain_only_query_count": owned_domain_only,
        "competitor_led_query_count": competitor_led,
        "queries_with_competitor_presence": len(competitor_query_rows),
        "external_led_query_count": external_led,
        "nissan_vs_aggregate_competitor": {
            "nissan_target_cited_queries": owned_target,
            "nissan_domain_only_queries": owned_domain_only,
            "nissan_brand_model_mention_only_queries": brand_only,
            "aggregate_competitor_led_queries": competitor_led,
            "external_led_no_nissan_target_queries": external_led,
        },
    }
    dashboard = {
        "brand": brand,
        "market": market,
        "executive_kpis": kpis,
        "source_landscape": {"source_type_counts": dict(source_counts), "competitor_presence": kpis["nissan_vs_aggregate_competitor"]},
        "owned_readiness": owned_scores,
        "external_benchmark_patterns": winning,
        "query_evidence": query_matrix,
        "owned_page_recommendations": recs,
        "pr_opportunities": pr,
        "methodology": "Strict GEO scoring uses the 6x20 framework with no easy marks. Scores are capped when pages lack answer-first mapped-query coverage, visible proof, FAQ/Product structured data, freshness/validity signals, or observed target-page citation evidence. External benchmark signals capture why external sources win in AI answers; they are not full GEO audits of third-party pages. AI visibility is observed-evidence-first and heavily weighted to exact owned target-page citations.",
    }
    write_json(project / "outputs/dashboard/ai_visibility_dashboard_dataset.json", dashboard)
    bundle = {
        "metadata": {"brand": brand, "market": market, "domain": domain, "mode": "strict_railway_bodhi_compact_runtime"},
        "executive_kpis": kpis,
        "dashboard_summary": dashboard,
        "recommendations": recs,
        "pr_opportunities": pr,
        "methodology_and_caveats": [
            "Owned GEO scores are strict and query-specific; official ownership, long markdown, or catalogue depth alone is not sufficient.",
            "Branded query pages are penalised when evidence is not visible in page content; non-branded queries require stronger trust/proof to become AI-citable.",
            "External benchmark signals capture citation influence and winning content patterns, not a full GEO quality score for third-party pages.",
            "AI visibility score gives strong credit only for exact owned target-page citations; brand/model mentions are low-credit signals.",
            "Competitor-led visibility is reported separately from generic external-led visibility.",
        ],
    }
    write_json(project / "outputs/bodhi/bodhi_input_bundle.json", bundle)
    write_json(project / "outputs/bodhi/bodhi_input_bundle_compact.json", {"metadata": bundle["metadata"], "executive_kpis": kpis, "top_recommendations": recs[:15], "pr_opportunities": pr[:10]})
    required = [
        "outputs/google_ai_mode/google_ai_mode_compact.json",
        "outputs/content_intelligence/owned_pages_full.json",
        "outputs/external_pages/external_pages_full.json",
        "outputs/page_scores/owned_page_scores.json",
        "outputs/page_scores/external_page_scores.json",
        "outputs/benchmark/source_preference_benchmark.json",
        "outputs/dashboard/ai_visibility_dashboard_dataset.json",
        "outputs/bodhi/bodhi_input_bundle.json",
    ]
    missing = [p for p in required if not (project / p).exists()]
    validation = {"status": "passed" if not missing else "failed", "missing_files": missing, "mode": "strict_railway_bodhi_compact_runtime", "required_files": required, "project_source_dir": str(project), "generated_files_count": len(required)}
    write_json(project / "outputs/validation/validation_report.json", validation)
    print(json.dumps({"status": "ready", "mode": "strict_railway_bodhi_compact_runtime", "project_dir": str(project), "counts": kpis, "validation": validation}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
