#!/usr/bin/env python3
"""Build canonical query-led AI Search Visibility report bundle.

Locked orchestration strategy:
query -> top 3 owned URLs -> top 3 external citations -> winning patterns -> CMS/PR actions -> rerun deltas.

This v5 builder is deliberately tolerant of three payload shapes:
1) canonical query_workbench.v1 bundles,
2) older Bodhi preview bundles with query_evidence / owned_readiness / source_landscape,
3) Railway Bodhi compact bundles with audit_context / evidence_scope / google_ai_mode / owned and external pages.
"""
from __future__ import annotations
import argparse, json, re, time, math, hashlib
from pathlib import Path
from urllib.parse import urlparse
from collections import Counter, defaultdict
from typing import Any
from ai_hygiene import attach_ai_discoverability_hygiene

# OWNED_HINTS is populated at runtime from --owned-domains CLI arg or brand config.
# No hardcoded brand domains.
OWNED_HINTS: list[str] = []
COMPETITORS = {
    "Toyota": ["toyota", "トヨタ", "lexus", "レクサス"],
    "Honda": ["honda", "ホンダ"],
    "Mitsubishi": ["mitsubishi", "三菱"],
    "Mazda": ["mazda", "マツダ"],
    "Subaru": ["subaru", "スバル"],
    "Suzuki": ["suzuki", "スズキ"],
    "Daihatsu": ["daihatsu", "ダイハツ"],
}
INTENT_RULES = {
    "charging": ["charge", "charging", "charger", "充電", "range", "battery", "ariya", "leaf", "sakura", "ev"],
    "warranty": ["warranty", "保証", "battery", "faq", "support", "service"],
    "range": ["range", "cruising", "battery", "charge", "ariya", "leaf", "sakura", "ev"],
    "epower": ["e-power", "powertrain", "hybrid", "fuel", "燃費", "note", "aura", "serena"],
    "safety": ["safety", "assist", "adas", "crash", "安全", "360"],
    "finance": ["finance", "loan", "lease", "subscription", "insurance", "price", "cost", "payment", "支払"],
    "family": ["family", "seat", "storage", "luggage", "serena", "x-trail", "elgrand", "interior"],
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
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(str(p or "") for p in parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{h}"


def text(v: Any, limit: int = 0) -> str:
    if v is None:
        s = ""
    elif isinstance(v, str):
        s = v
    elif isinstance(v, (int, float, bool)):
        s = str(v)
    elif isinstance(v, list):
        s = " ".join(text(x) for x in v)
    elif isinstance(v, dict):
        s = " ".join(text(x) for k, x in v.items() if str(k).lower() not in {"html", "raw_html", "rendered_html"})
    else:
        s = str(v)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if limit and len(s) > limit else s


def as_list(obj: Any, keys=()) -> list:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                nested = as_list(v, keys)
                if nested:
                    return nested
    return []


def record_dict(v: Any, default_key: str = "url") -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        return {default_key: v}
    if v is None:
        return {}
    return {"value": v}


def records_list(obj: Any, keys=(), default_key: str = "url") -> list[dict]:
    return [record_dict(x, default_key=default_key) for x in as_list(obj, keys)]


def domain(url: str) -> str:
    try:
        d = urlparse(url or "").netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def is_owned(url: str) -> bool:
    d = domain(url)
    return any(h in d for h in OWNED_HINTS)


def source_type(url: str, raw: str = "") -> str:
    d = domain(url); r = (raw or "").lower()
    if is_owned(url): return "owned_brand_ecosystem"
    if any(x in d for x in ["toyota", "honda", "mitsubishi", "mazda", "subaru", "suzuki", "daihatsu", "lexus"]): return "competitor_owned"
    if any(x in d for x in ["reddit", "youtube", "facebook", "instagram", "x.com", "twitter", "tiktok"]): return "forum_social_video"
    if any(x in d for x in ["go.jp", "mlit", "meti", "nasva", "enecho"]): return "authority_body"
    if any(x in d for x in ["tepco", "charging", "charge", "evdays"]): return "partner_infrastructure"
    if any(x in d for x in ["finance", "insurance", "loan", "credit", "fs."]): return "finance_or_insurance"
    if any(x in d for x in ["price", "carmo", "rakuten", "broker", "mailmate", "gaijinpot", "tc-v"]): return "aggregator_marketplace"
    if "review" in r or "publisher" in r or any(x in d for x in ["nikkei", "asahi", "recharged", "autonews", "carwow", "parkers", "greencarreports"]): return "publisher_review"
    return r or "other"


def query_id(row: dict, i: int) -> str:
    return str(row.get("query_id") or row.get("id") or row.get("qid") or f"q{i+1:03d}")


def normalise_query(row: dict) -> str:
    return text(row.get("query") or row.get("search_query") or row.get("question") or row.get("user_query"))



def build_query_metadata_index(*objs: Any) -> dict[str, dict]:
    """Collect query/topic metadata from portfolio, audit_context, evidence_scope and compact rows.

    Evidence-service compact bundles may expose Google AI Mode rows separately from
    the synthetic portfolio. Those rows often contain query_id/query but not
    journey_stage/topic metadata. This index lets the builder restore the
    portfolio taxonomy before constructing the report contract.
    """
    idx: dict[str, dict] = {}
    topic_idx: dict[str, dict] = {}

    def merge_meta(qid: str, meta: dict):
        if not qid:
            return
        cur = idx.setdefault(str(qid), {})
        for k, v in meta.items():
            if v is not None and v != "" and cur.get(k) in (None, "", [], {}):
                cur[k] = v

    def walk(obj: Any):
        if isinstance(obj, dict):
            for t in as_list(obj, ["topics", "brand_topics", "topic_portfolio"]):
                if isinstance(t, dict):
                    tid = text(t.get("topic_id") or t.get("id"))
                    if tid:
                        topic_idx.setdefault(tid, {}).update({
                            "topic_id": tid,
                            "topic": text(t.get("topic") or t.get("brand_topic") or t.get("name")),
                            "journey_stage": text(t.get("journey_stage") or t.get("journey_category") or t.get("category")),
                            "topic_priority": text(t.get("priority")),
                            "why_this_topic_matters": text(t.get("why_this_topic_matters")),
                            "recommended_page_types": t.get("recommended_page_types") if isinstance(t.get("recommended_page_types"), list) else [],
                            "market_notes": text(t.get("market_notes")),
                        })
            for q in as_list(obj, ["queries", "query_portfolio", "query_scope", "rows", "items", "results"]):
                if isinstance(q, dict):
                    qid = text(q.get("query_id") or q.get("id") or q.get("qid"))
                    query_text = normalise_query(q)
                    topic_id = text(q.get("topic_id"))
                    topic_meta = topic_idx.get(topic_id, {}) if topic_id else {}
                    journey = text(q.get("journey_stage") or q.get("journey_category") or q.get("category") or topic_meta.get("journey_stage"))
                    topic = text(q.get("topic") or q.get("brand_topic") or q.get("brand_topic_category") or topic_meta.get("topic"))
                    if qid or query_text:
                        meta = {
                            "query_id": qid,
                            "query": query_text,
                            "topic_id": topic_id or topic_meta.get("topic_id"),
                            "topic": topic,
                            "brand_topic": topic,
                            "brand_topic_category": topic or journey,
                            "journey_stage": journey,
                            "journey_category": journey,
                            "intent": text(q.get("intent")),
                            "priority": text(q.get("priority")),
                            "recommended_page_type": text(q.get("recommended_page_type")),
                            "brand_relevance": text(q.get("brand_relevance")),
                            "reason_selected": text(q.get("reason_selected")),
                            "expected_ai_answer_source_types": q.get("expected_ai_answer_source_types") if isinstance(q.get("expected_ai_answer_source_types"), list) else [],
                            "market_localisation_notes": text(q.get("market_localisation_notes")),
                            "topic_priority": topic_meta.get("topic_priority"),
                            "why_this_topic_matters": topic_meta.get("why_this_topic_matters"),
                            "recommended_page_types": topic_meta.get("recommended_page_types") or [],
                            "market_notes": topic_meta.get("market_notes"),
                        }
                        if qid:
                            merge_meta(qid, meta)
                        if query_text:
                            merge_meta(query_text.lower(), meta)
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                if isinstance(v, (dict, list)):
                    walk(v)

    for obj in objs:
        walk(obj)
    return idx


def enrich_query_row(row: dict, qid: str, query: str, meta_index: dict[str, dict]) -> dict:
    """Return row merged with portfolio metadata without overwriting observed evidence."""
    meta = meta_index.get(str(qid)) or meta_index.get((query or "").lower()) or {}
    if not meta:
        return row
    out = dict(row)
    for k, v in meta.items():
        if v is not None and v != "" and out.get(k) in (None, "", [], {}, "Unclassified"):
            out[k] = v
    # Canonical aliases used downstream.
    journey = text(out.get("journey_stage") or out.get("journey_category") or out.get("category"))
    if journey and (not out.get("journey_category") or out.get("journey_category") == "Unclassified"):
        out["journey_category"] = journey
    if journey and not out.get("journey_stage"):
        out["journey_stage"] = journey
    topic = text(out.get("topic") or out.get("brand_topic") or out.get("brand_topic_category"))
    if topic:
        out.setdefault("topic", topic)
        out.setdefault("brand_topic", topic)
        if out.get("brand_topic_category") in (None, "", "Unclassified"):
            out["brand_topic_category"] = topic
    return out


def query_taxonomy(row: dict) -> dict:
    journey = text(row.get("journey_stage") or row.get("journey_category") or row.get("category") or "Unclassified") or "Unclassified"
    topic = text(row.get("topic") or row.get("brand_topic") or row.get("brand_topic_category") or journey) or journey
    return {
        "topic_id": text(row.get("topic_id")),
        "topic": topic,
        "brand_topic": topic,
        "journey_stage": journey,
        "journey_category": journey,
        "intent": text(row.get("intent")),
        "priority": text(row.get("priority")),
        "recommended_page_type": text(row.get("recommended_page_type")),
        "brand_relevance": text(row.get("brand_relevance")),
        "reason_selected": text(row.get("reason_selected")),
        "expected_ai_answer_source_types": row.get("expected_ai_answer_source_types") if isinstance(row.get("expected_ai_answer_source_types"), list) else [],
        "market_localisation_notes": text(row.get("market_localisation_notes")),
    }

def normalise_citation(r: dict, pos: int = 1) -> dict:
    u = text(r.get("url") or r.get("source_url") or r.get("link") or r.get("href"))
    return {
        "rank": int(r.get("rank") or r.get("citation_position") or r.get("observed_citation_position") or pos),
        "citation_position": int(r.get("citation_position") or r.get("rank") or r.get("observed_citation_position") or pos),
        "title": text(r.get("title") or r.get("source_name") or domain(u)),
        "url": u,
        "source_url": u,
        "domain": text(r.get("domain") or r.get("source_domain") or domain(u)),
        "source_domain": text(r.get("source_domain") or r.get("domain") or domain(u)),
        "source_type": source_type(u, text(r.get("source_type") or r.get("source_category"))),
        "snippet": text(r.get("snippet") or r.get("citation_text") or r.get("text") or r.get("summary") or r.get("content_extract"), 700),
        "citation_text": text(r.get("citation_text") or r.get("snippet") or r.get("text") or r.get("summary") or r.get("content_extract"), 700),
        "query_id": text(r.get("query_id")),
        "query": text(r.get("query")),
        "is_owned_domain": bool(r.get("is_owned_domain") or r.get("is_owned") or is_owned(u)),
        "is_owned_target_page": bool(r.get("is_owned_target_page") or r.get("owned_target_page_cited") or False),
        "is_competitor": bool(r.get("is_competitor") or source_type(u) == "competitor_owned"),
    }


def refs_from(row: dict) -> list[dict]:
    out=[]
    if not isinstance(row, dict): return out
    for k in ["citations", "references", "top_citations", "top_cited_sources", "sources", "organic_results", "answer_supporting_references"]:
        v=row.get(k)
        if isinstance(v, list): out += [x for x in v if isinstance(x, dict)]
    for k in ["answer", "response", "google_ai_mode", "metadata"]:
        if isinstance(row.get(k), dict): out += refs_from(row[k])
    seen=set(); clean=[]
    for i,r in enumerate(out, start=1):
        c=normalise_citation(r, i)
        if c["url"] and c["url"] not in seen:
            seen.add(c["url"]); clean.append(c)
    return clean



def build_google_citations_by_q(google: dict) -> dict:
    """Return citations keyed by query_id from google_ai_mode_compact rows.

    Evidence Service v3.4.7 exposes top_citations/references on rows. Older rows
    may use queries/results. This adapter keeps the report populated even when the
    query portfolio is the primary query row source.
    """
    out = defaultdict(list)
    rows = []
    if isinstance(google, dict):
        rows = google.get("rows") or google.get("queries") or google.get("results") or []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        qid = text(row.get("query_id") or row.get("id"))
        if not qid:
            continue
        refs = refs_from(row)
        for c in refs:
            if c.get("url"):
                out[qid].append(c)
    return out


def build_evidence_citations_by_q(evidence: dict, source_class: dict) -> dict:
    """Return citations keyed by query_id from evidence_scope and source_classification.

    evidence_scope.ai_citations already carries query_id. source_classification often
    aggregates by source URL with a queries[] list; expand that back to query rows.
    """
    out = defaultdict(list)
    if isinstance(evidence, dict):
        for s in records_list(evidence, ["ai_citations", "citations", "external_sources", "sources", "external_citation_urls"], default_key="url"):
            if not isinstance(s, dict):
                continue
            qids = []
            if s.get("query_id"):
                qids = [text(s.get("query_id"))]
            elif isinstance(s.get("queries"), list):
                qids = [text(x) for x in s.get("queries") if text(x)]
            for qid in qids:
                c = normalise_citation({**s, "url": s.get("source_url") or s.get("url")}, len(out[qid]) + 1)
                if c.get("url"):
                    out[qid].append(c)
    if isinstance(source_class, dict):
        for s in records_list(source_class, ["sources", "rows"], default_key="url"):
            if not isinstance(s, dict):
                continue
            qids = []
            if s.get("query_id"):
                qids = [text(s.get("query_id"))]
            elif isinstance(s.get("queries"), list):
                qids = [text(x) for x in s.get("queries") if text(x)]
            for qid in qids:
                c = normalise_citation({**s, "url": s.get("source_url") or s.get("url")}, len(out[qid]) + 1)
                if c.get("url"):
                    out[qid].append(c)
    # de-dupe per query
    clean = defaultdict(list)
    for qid, cites in out.items():
        seen = set()
        for idx, c in enumerate(cites, start=1):
            u = c.get("url")
            if not u or u in seen:
                continue
            seen.add(u)
            c["rank"] = c.get("rank") or idx
            c["citation_position"] = c.get("citation_position") or idx
            clean[qid].append(c)
    return clean


def url_key(value: Any) -> str:
    return text(value).split("#", 1)[0].rstrip("/").lower()


def first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def page_url(page: dict) -> str:
    return text(first_value(page.get("url"), page.get("page_url"), page.get("target_url"), page.get("resolved_url"), page.get("canonical_url"), page.get("href"), page.get("link")))


def page_score(page: dict) -> Any:
    return first_value(page.get("current_geo_score_120"), page.get("score_120"), page.get("geo_readiness_score"), page.get("geo_score_120"), page.get("readiness_score"))


def page_geo_from_crawl(page: dict) -> tuple[int, dict[str, int], str, str]:
    """Deterministic page-intrinsic GEO/readiness score from crawl evidence.

    This score deliberately ignores query intent. Query matching is handled
    separately by map_owned_urls() so page readiness remains stable across runs
    when the page content and crawl evidence have not changed.
    """
    tech = page.get("technical_signals") if isinstance(page.get("technical_signals"), dict) else {}
    markdown = text(first_value(page.get("markdown"), page.get("text"), page.get("content_extract"), page.get("main_text"), tech.get("markdown"), tech.get("text"), ""), 12000)
    title = text(first_value(page.get("title"), page.get("page_title"), ""))
    description = text(first_value(page.get("meta_description"), page.get("description"), ""))
    combined = f"{title}\n{description}\n{markdown}"
    low = combined.lower()
    try:
        word_count = int(first_value(page.get("word_count"), tech.get("word_count"), tech.get("wordCount"), len(combined.split())) or 0)
    except Exception:
        word_count = len(combined.split())
    has_full_crawl_text = word_count >= 250 and len(markdown) >= 500
    headings = page.get("headings") if isinstance(page.get("headings"), list) else tech.get("headings") if isinstance(tech.get("headings"), list) else []
    schema_types = first_value(page.get("schema_types"), page.get("schema_types_detected"), tech.get("schema_types"), tech.get("schemaTypes"), [])
    schema_count = len(schema_types) if isinstance(schema_types, list) else 0
    json_ld_present = bool(first_value(page.get("json_ld_present"), page.get("jsonLdPresent"), tech.get("json_ld_present"), tech.get("jsonLdPresent"), False))
    try:
        json_ld_blocks = int(first_value(page.get("json_ld_block_count"), page.get("jsonLdBlockCount"), tech.get("json_ld_block_count"), tech.get("jsonLdBlockCount"), 0) or 0)
    except Exception:
        json_ld_blocks = 0
    numeric_count = len(re.findall(r"\d+[\d,.]*\s?(?:km|kwh|kw|円|万円|年|%|％|mm|kg|人|席)", combined, re.I))
    question_count = low.count("?") + low.count("？") + low.count("faq") + low.count("よくある")
    proof_count = sum(low.count(term) for term in ["保証", "安全", "仕様", "諸元", "条件", "公式", "warranty", "safety", "specification", "official"])
    freshness = bool(re.search(r"20[2-3][0-9]|更新日|掲載日|last updated|valid until", combined, re.I))
    canonical_url = first_value(page.get("canonical_url"), tech.get("canonical_url"), tech.get("canonicalUrl"), page.get("final_url"))
    if not has_full_crawl_text:
        dims = {
            "content_clarity": 4 if title else 0,
            "semantic_depth": 0,
            "structured_data": min(20, (12 if json_ld_present or json_ld_blocks > 0 else 0) + min(8, schema_count * 3)),
            "eeat_signals": 2,
            "freshness_index": 4 if canonical_url else 0,
            "faq_readiness": 0,
        }
        return sum(dims.values()), dims, "fallback_limited_v1", "Limited fallback: full markdown crawl text was not available, so only metadata and technical signals were scored."
    dims = {
        "content_clarity": min(20, (4 if title else 0) + (4 if description else 0) + (4 if word_count >= 300 else 0) + (4 if len(headings) >= 2 else 0)),
        "semantic_depth": min(20, (4 if word_count >= 600 else 0) + (4 if word_count >= 1200 else 0) + min(6, numeric_count) + min(4, len(headings))),
        "structured_data": min(20, (12 if json_ld_present or json_ld_blocks > 0 else 0) + min(8, schema_count * 3)),
        "eeat_signals": min(20, 2 + min(8, proof_count) + min(6, numeric_count) + (4 if freshness else 0)),
        "freshness_index": min(20, 4 + (8 if freshness else 0) + (4 if canonical_url else 0)),
        "faq_readiness": min(20, min(12, question_count * 3)),
    }
    if text(page.get("crawl_status")).lower() not in {"success", "partial_success_empty_text"} and word_count < 20:
        dims = {key: 0 for key in dims}
    return sum(dims.values()), dims, "crawl_evidence_v1", "Page-intrinsic GEO/readiness score computed from owned-page crawl text plus JSON-LD/schema, canonical and freshness signals."


def fallback_geo_from_crawl(page: dict) -> tuple[int, dict[str, int]]:
    score, dims, _method, _note = page_geo_from_crawl(page)
    return score, dims


def has_scored_owned_signal(page: dict) -> bool:
    if page_score(page) is not None or page.get("geo_analysis_ready") is True:
        return True
    try:
        word_count = int(page.get("word_count") or 0)
    except Exception:
        word_count = 0
    return text(page.get("crawl_status")).lower() == "success" and (word_count > 0 or bool(page.get("markdown") or page.get("text")))


def page_technical_signals(page: dict) -> dict:
    tech = page.get("technical_signals") if isinstance(page.get("technical_signals"), dict) else {}
    schema_types = first_value(tech.get("schema_types"), tech.get("schemaTypes"), page.get("schema_types"), page.get("schema_types_detected"), [])
    block_count = first_value(tech.get("json_ld_block_count"), tech.get("jsonLdBlockCount"), page.get("json_ld_block_count"))
    json_ld_present = first_value(tech.get("json_ld_present"), tech.get("jsonLdPresent"), page.get("json_ld_present"))
    out = {
        **tech,
        "json_ld_present": json_ld_present,
        "json_ld_block_count": block_count,
        "schema_types": schema_types if isinstance(schema_types, list) else [],
        "crawl_status": first_value(tech.get("crawl_status"), tech.get("crawlStatus"), page.get("crawl_status")),
        "canonical_url": first_value(tech.get("canonical_url"), tech.get("canonicalUrl"), page.get("canonical_url"), page.get("final_url")),
        "word_count": first_value(tech.get("word_count"), tech.get("wordCount"), page.get("word_count")),
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


def related_queries_from(value: Any) -> list[dict]:
    out = []
    for row in as_list(value):
        if not isinstance(row, dict):
            continue
        related = {
            "query_id": text(first_value(row.get("query_id"), row.get("id"))),
            "id": text(first_value(row.get("query_id"), row.get("id"))),
            "query": text(first_value(row.get("query"), row.get("text"))),
            "visibility_status": text(first_value(row.get("visibility_status"), row.get("status"))),
        }
        if related["query_id"] or related["query"]:
            out.append(related)
    return out


def canonical_owned_readiness_row(page: dict, *, query_mapped: bool = False, related_queries: list[dict] | None = None) -> dict | None:
    url = page_url(page)
    if not url:
        return None
    extract = page.get("owned_page_extract") if isinstance(page.get("owned_page_extract"), dict) else {}
    dims = first_value(page.get("geo_dimensions"), page.get("dimensions"), page.get("dimension_scores"), {})
    dims = _normalise_dimension_scores(dims) if isinstance(dims, dict) else {}
    tech = page_technical_signals(page)
    score = page_score(page)
    scoring_method = first_value(page.get("scoring_method"), page.get("scoringMethod"))
    scoring_notes = first_value(page.get("scoring_notes"), page.get("scoringNotes"))
    if score in (None, "", 0) and not dims:
        score, dims, scoring_method, scoring_notes = page_geo_from_crawl(page)
    elif not scoring_method:
        scoring_method = "explicit_page_geo_v1"
        scoring_notes = "Explicit page-level GEO/readiness score supplied by the Auditor or stored report bundle."
    row = {
        "url": url,
        "title": text(first_value(extract.get("title"), page.get("title"), page.get("page_title"))),
        "current_geo_score_120": score if score is not None else 0,
        "geo_dimensions": dims,
        "scoring_method": scoring_method,
        "scoring_notes": scoring_notes,
        "query_mapped": bool(page.get("query_mapped") is True or page.get("queryMapped") is True or query_mapped),
        "inventory_source": text(first_value(page.get("inventory_source"), page.get("inventorySource"), "query_mapped" if query_mapped else "sitemap_inventory")),
        "related_queries": related_queries if related_queries is not None else related_queries_from(first_value(page.get("related_queries"), page.get("related_query_evidence"), page.get("mapped_queries"))),
        "technical_signals": tech,
        "json_ld_present": tech.get("json_ld_present"),
        "json_ld_block_count": tech.get("json_ld_block_count"),
        "schema_types": tech.get("schema_types", []),
    }
    for key in ("score_band", "crawl_status", "extraction_status", "geo_analysis_ready"):
        if page.get(key) is not None:
            row[key] = page.get(key)
    return {k: v for k, v in row.items() if v is not None}


def collect_owned_pages_from_sources(*sources: Any) -> list[dict]:
    rows = []

    def walk(obj: Any):
        if isinstance(obj, dict):
            owned_full = obj.get("owned_pages_full") if isinstance(obj.get("owned_pages_full"), dict) else None
            if owned_full:
                for page in records_list(owned_full, ["pages", "owned_pages", "items"]):
                    if has_scored_owned_signal(page):
                        rows.append(page)
            for key in ("owned_url_readiness", "owned_readiness", "owned_pages", "owned_urls", "pages", "items", "rows"):
                for page in records_list(obj.get(key), default_key="url"):
                    if has_scored_owned_signal(page):
                        rows.append(page)
            for key in ("audit_context", "evidence_scope", "files", "data", "bundle"):
                if isinstance(obj.get(key), dict):
                    walk(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict) and has_scored_owned_signal(item):
                    rows.append(item)

    for source in sources:
        walk(source)
    return rows


def mapped_url_index(qwork: list[dict], bundle: dict) -> tuple[set[str], dict[str, list[dict]]]:
    mapped = set()
    related_by_url: dict[str, list[dict]] = defaultdict(list)
    for q in qwork:
        if not isinstance(q, dict):
            continue
        rel = {
            "query_id": text(q.get("query_id")),
            "id": text(q.get("query_id")),
            "query": text(q.get("query")),
            "topic_id": text(q.get("topic_id")),
            "topic": text(q.get("topic")),
            "journey_category": text(q.get("journey_category")),
            "journey_stage": text(q.get("journey_stage")),
            "intent": text(q.get("intent")),
            "visibility_status": text((q.get("current_ai_visibility") or {}).get("status") if isinstance(q.get("current_ai_visibility"), dict) else ""),
        }
        for page in q.get("mapped_owned_urls") or []:
            if not isinstance(page, dict):
                continue
            key = url_key(page_url(page))
            if not key:
                continue
            mapped.add(key)
            related_by_url[key].append({k: v for k, v in rel.items() if v})
    for rec_key in ("page_level_cms_recommendations", "cms_recommendations"):
        for rec in bundle.get(rec_key) or []:
            if not isinstance(rec, dict):
                continue
            key = url_key(first_value(rec.get("target_url"), rec.get("targetUrl"), rec.get("url")))
            if key:
                mapped.add(key)
    return mapped, related_by_url


def source_citation_rows(qwork: list[dict], *sources: Any) -> list[dict]:
    rows = []
    for q in qwork:
        if not isinstance(q, dict):
            continue
        qid = text(q.get("query_id"))
        query = text(q.get("query"))
        citations = []
        vis = q.get("current_ai_visibility") if isinstance(q.get("current_ai_visibility"), dict) else {}
        citations.extend([c for c in vis.get("top_citations") or [] if isinstance(c, dict)])
        citations.extend([c for c in q.get("external_top3_benchmark") or [] if isinstance(c, dict)])
        for i, c in enumerate(citations, start=1):
            item = normalise_citation({**c, "query_id": qid, "query": query}, i)
            if item.get("url"):
                rows.append(item)

    for source in sources:
        if not isinstance(source, dict):
            continue
        google = source.get("google_ai_mode_compact") if isinstance(source.get("google_ai_mode_compact"), dict) else source
        for row in as_list(google, ["rows", "queries", "results"]):
            if not isinstance(row, dict):
                continue
            qid = text(row.get("query_id") or row.get("id"))
            query = text(row.get("query"))
            for i, ref in enumerate(refs_from(row), start=1):
                item = normalise_citation({**ref, "query_id": qid, "query": query}, i)
                if item.get("url"):
                    rows.append(item)
        evidence = source.get("evidence_scope") if isinstance(source.get("evidence_scope"), dict) else source
        for ref in records_list(evidence, ["ai_citations", "citations", "external_sources", "sources"], default_key="url"):
            qids = [text(ref.get("query_id"))] if ref.get("query_id") else [text(x) for x in ref.get("queries", []) if text(x)] if isinstance(ref.get("queries"), list) else [""]
            for qid in qids:
                item = normalise_citation({**ref, "url": ref.get("source_url") or ref.get("url"), "query_id": qid, "query": ref.get("query")}, len(rows) + 1)
                if item.get("url"):
                    rows.append(item)

    deduped = {}
    for item in rows:
        key = (text(item.get("query_id")), url_key(item.get("url")), text(item.get("citation_position")))
        deduped.setdefault(key, item)
    return list(deduped.values())


def observed_domains_from_citations(citations: list[dict]) -> list[dict]:
    by_domain = {}
    for c in citations:
        if c.get("is_owned_domain"):
            continue
        d = text(c.get("domain") or c.get("source_domain") or domain(c.get("url")))
        if not d:
            continue
        row = by_domain.setdefault(d, {"domain": d, "source_domain": d, "source_type": c.get("source_type") or "other", "observed_count": 0, "count": 0, "example_url": c.get("url"), "example_query": c.get("query")})
        row["observed_count"] += 1
        row["count"] += 1
    return sorted(by_domain.values(), key=lambda x: x["observed_count"], reverse=True)


def finalise_frontend_contract(bundle: dict, *sources: Any) -> dict:
    qwork = bundle.get("query_workbench") if isinstance(bundle.get("query_workbench"), list) else []
    mapped, related_by_url = mapped_url_index(qwork, bundle)
    rows_by_url = {}
    for row in bundle.get("owned_url_readiness") or []:
        if not isinstance(row, dict):
            continue
        key = url_key(page_url(row))
        canonical = canonical_owned_readiness_row(row, query_mapped=key in mapped, related_queries=related_by_url.get(key) or related_queries_from(row.get("related_queries")))
        if key and canonical:
            rows_by_url[key] = canonical
    for page in collect_owned_pages_from_sources(*sources):
        key = url_key(page_url(page))
        if not key:
            continue
        canonical = canonical_owned_readiness_row(page, query_mapped=key in mapped, related_queries=related_by_url.get(key, []))
        if key in rows_by_url:
            if not canonical:
                continue
            existing = rows_by_url[key]
            existing["query_mapped"] = bool(existing.get("query_mapped") or canonical.get("query_mapped"))
            if not existing.get("current_geo_score_120") and canonical.get("current_geo_score_120"):
                existing["current_geo_score_120"] = canonical.get("current_geo_score_120")
            if not existing.get("geo_dimensions") and canonical.get("geo_dimensions"):
                existing["geo_dimensions"] = canonical.get("geo_dimensions")
            for field in ("title", "inventory_source", "json_ld_present", "json_ld_block_count", "schema_types", "scoring_method", "scoring_notes"):
                if existing.get(field) in (None, "", [], {}):
                    existing[field] = canonical.get(field)
            tech = existing.get("technical_signals") if isinstance(existing.get("technical_signals"), dict) else {}
            tech.update(canonical.get("technical_signals") if isinstance(canonical.get("technical_signals"), dict) else {})
            existing["technical_signals"] = tech
            if not existing.get("related_queries") and canonical.get("related_queries"):
                existing["related_queries"] = canonical.get("related_queries")
            continue
        if canonical:
            rows_by_url[key] = canonical
    owned = list(rows_by_url.values())
    bundle["owned_url_readiness"] = owned
    if isinstance(bundle.get("executive"), dict):
        headline = bundle["executive"].setdefault("headline_metrics", {})
        if isinstance(headline, dict):
            headline["owned_page_count"] = len(owned)
            headline["average_owned_geo_score_120"] = round(sum(float(o.get("current_geo_score_120") or 0) for o in owned) / max(1, len(owned)), 1)

    citations = source_citation_rows(qwork, *sources)
    landscape = bundle.setdefault("source_landscape", {})
    if isinstance(landscape, dict):
        landscape["source_citations"] = citations
        if not isinstance(landscape.get("observed_non_owned_domains"), list) or not landscape.get("observed_non_owned_domains"):
            landscape["observed_non_owned_domains"] = observed_domains_from_citations(citations)
    bundle.setdefault("parser_manifest", {})["owned_url_readiness_count"] = len(owned)
    bundle["parser_manifest"]["source_citation_count"] = len(citations)
    return bundle

def detect_competitors(blob: str, citations: list[dict]) -> list[str]:
    all_text=(blob+" "+" ".join(text(c) for c in citations)).lower()
    found=[]
    for name, variants in COMPETITORS.items():
        if any(v.lower() in all_text for v in variants): found.append(name)
    return found


def infer_intents(query: str) -> list[str]:
    q=query.lower()
    intents=[]
    if any(x in q for x in ["charge", "charger", "charging", "connector", "充電"]): intents.append("charging")
    if any(x in q for x in ["warranty", "保証"]): intents.append("warranty")
    if any(x in q for x in ["range", "battery", "energy", "ev", "electric"]): intents.append("range")
    if any(x in q for x in ["e-power", "hybrid", "powertrain", "fuel", "petrol", "燃費"]): intents.append("epower")
    if any(x in q for x in ["safety", "adas", "crash", "collision", "rating"]): intents.append("safety")
    if any(x in q for x in ["cost", "price", "finance", "loan", "lease", "insurance", "subscription", "resale"]): intents.append("finance")
    if any(x in q for x in ["family", "seat", "luggage", "storage", "comfort", "minivan"]): intents.append("family")
    return intents or ["general"]


def page_blob(page: dict) -> str:
    return (text(page.get("url") or page.get("resolved_url") or page.get("page_url")) + " " +
            text(page.get("title") or page.get("page_title")) + " " +
            text(page.get("description")) + " " +
            text(page.get("journey_category") or page.get("brand_topic_category")) + " " +
            text(page.get("related_queries") or page.get("mapped_queries") or page.get("related_queries_seed")) + " " +
            text(page.get("evidence_markdown") or page.get("markdown") or page.get("content_extract") or page.get("main_text"), 4000)).lower()


def _normalise_dimension_scores(raw: dict) -> dict:
    """Return dimension scores as {dimension: int}.

    Older pipeline files may store dimensions as plain numbers, while the
    original page scorer stores {dimension: {score, max_score, ...}}. The
    query-workbench mapper must preserve whichever strict upstream score is
    available rather than falling back to the loose heuristic.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, val in raw.items():
        if isinstance(val, dict):
            candidate = val.get("score") or val.get("value") or val.get("points")
        else:
            candidate = val
        try:
            out[str(key)] = max(0, min(20, int(round(float(candidate)))))
        except Exception:
            continue
    return out


def _first_numeric(page: dict, keys: list[str]) -> int | None:
    for key in keys:
        val = page.get(key)
        if val is None or val == "":
            continue
        try:
            return max(0, min(120, int(round(float(val)))))
        except Exception:
            continue
    return None


def score_owned_page_with_method(page: dict) -> tuple[int, dict, list[str], str, str]:
    page = record_dict(page)

    # Preserve strict scores produced by strict_geo_visibility_runtime.py or
    # score_owned_geo_readiness.py. This fixes the previous behaviour where
    # records carrying geo_score_120/readiness_score were ignored and then
    # rescored by a loose fallback, often awarding 20/20 for clarity.
    score = _first_numeric(page, [
        "score_120",
        "geo_score_120",
        "current_geo_score_120",
        "geo_readiness_score",
        "readiness_score",
    ])
    if score is not None:
        dims = (
            _normalise_dimension_scores(page.get("dimensions"))
            or _normalise_dimension_scores(page.get("dimension_scores"))
            or _normalise_dimension_scores(page.get("geo_dimensions"))
            or _normalise_dimension_scores(page.get("feature_scores"))
        )
        gaps = page.get("dimension_gaps") or page.get("geo_gaps") or []
        if not isinstance(gaps, list):
            gaps = []
        if dims and not gaps:
            gaps = [k for k, v in dims.items() if isinstance(v, (int, float)) and v < 12]
        return score, dims, gaps, text(first_value(page.get("scoring_method"), page.get("scoringMethod"), "explicit_page_geo_v1")), "Explicit page-level GEO/readiness score supplied by the Auditor or stored report bundle."

    score, dims, method, note = page_geo_from_crawl(page)
    gaps=[k for k,v in dims.items() if v<12]
    return score, dims, gaps, method, note


def score_owned_page(page: dict, query: str="") -> tuple[int, dict, list[str]]:
    score, dims, gaps, _method, _note = score_owned_page_with_method(page)
    return score, dims, gaps


def page_intent_bonus(query: str, page: dict) -> int:
    b=page_blob(page); bonus=0
    for intent in infer_intents(query):
        if intent == "general": continue
        words=INTENT_RULES.get(intent, [])
        hits=sum(1 for w in words if w.lower() in b)
        bonus += min(35, hits*7)
    # penalise obvious mismatch: safety assist page for non-safety cost/charging/warranty query
    u=text(page.get("url") or page.get("page_url") or page.get("resolved_url")).lower()
    if "360_safety_assist" in u and not any(x in query.lower() for x in ["safety", "adas", "crash", "collision", "assist"]):
        bonus -= 18
    if "e-power" in u and any(x in query.lower() for x in ["hybrid", "e-power", "powertrain", "fuel"]):
        bonus += 25
    if any(x in u for x in ["charge", "charging", "range"]) and any(x in query.lower() for x in ["charge", "range", "battery", "ev"]):
        bonus += 25
    if "faq" in u and any(x in query.lower() for x in ["warranty", "guidance", "tips", "how"]):
        bonus += 12
    return bonus


def related_query_match(qid: str, query: str, page: dict) -> int:
    rel=page.get("related_queries") or page.get("mapped_queries") or page.get("related_queries_seed") or []
    blob=text(rel).lower()
    score=0
    if qid and qid.lower() in blob: score += 80
    qterms={w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w)>3}
    score += min(60, len([w for w in qterms if w in blob])*10)
    return score


def map_owned_urls(query: str, owned_pages: list[dict], max_n=3, qid: str="", category: str="") -> list[dict]:
    q_terms=[w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w)>2]
    ranked=[]
    for raw_p in owned_pages:
        p=record_dict(raw_p)
        u=text(p.get("url") or p.get("resolved_url") or p.get("href") or p.get("link") or p.get("page_url") or p.get("value"))
        if not u: continue
        blob=page_blob(p)
        overlap=len({w for w in q_terms if w in blob})
        score,dims,gaps,scoring_method,scoring_notes=score_owned_page_with_method(p)
        category_bonus=18 if category and category.lower() in text(p.get("journey_category") or p.get("brand_topic_category")).lower() else 0
        mapping_score=overlap*12 + score/2 + page_intent_bonus(query,p) + related_query_match(qid,query,p) + category_bonus + (10 if is_owned(u) else 0)
        ranked.append((mapping_score, p, score, dims, gaps))
    ranked.sort(key=lambda x:x[0], reverse=True)
    out=[]; seen=set()
    for rank,(ms,p,score,dims,gaps) in enumerate([x for x in ranked if text(x[1].get("url") or x[1].get("page_url") or x[1].get("resolved_url")) not in seen][:max_n], start=1):
        u=text(p.get("url") or p.get("resolved_url") or p.get("page_url"))
        seen.add(u)
        out.append({
            "rank": rank,
            "url": u,
            "title": text(p.get("title") or p.get("page_title")),
            "mapping_score": round(ms,1),
            "mapping_reason": "Ranked by query/topic match, page-type suitability, existing related-query linkage and GEO readiness.",
            "current_geo_score_120": score,
            "geo_dimensions": dims,
            "scoring_method": scoring_method,
            "scoring_notes": scoring_notes,
            "geo_gaps": gaps,
            "recommended_update_focus": (gaps[:4] or ["evidence_and_proof"]),
        })
    return out


def classify_visibility(row: dict, citations: list[dict], competitors: list[str]) -> str:
    raw=text(row.get("visibility_status") or row.get("status")).lower()
    if row.get("owned_target_page_cited") or row.get("owned_target_page_citation") or any(c.get("is_owned_target_page") for c in citations): return "owned_target_cited"
    if row.get("owned_domain_citations") or any(c.get("is_owned_domain") for c in citations): return "owned_domain_cited"
    if competitors or row.get("competitor_led") or "competitor" in raw: return "competitor_led"
    if citations or "external" in raw: return "external_led"
    return raw or "not_observed"


def external_top3_from_citations(citations: list[dict], max_n: int = 3) -> list[dict]:
    return [c for c in citations if c.get("url") and not c.get("is_owned_domain")][:max_n]


def winning_patterns(query: str, citations: list[dict], pattern_lookup: list[dict] | None = None) -> list[dict]:
    out=[]; pattern_lookup=pattern_lookup or []
    by_type=defaultdict(list)
    for p in pattern_lookup:
        if isinstance(p, dict):
            by_type[text(p.get("source_type") or p.get("source_category") or p.get("type"))].append(p)
    for c in citations:
        st=c.get("source_type") or "other"; sn=c.get("snippet","")
        patterns=[]
        if re.search(r"\d", sn): patterns.append("uses numeric evidence or dated proof")
        if st in {"authority_body","partner_infrastructure"}: patterns.append("borrows authority from specialist or official source")
        if st in {"publisher_review","aggregator_marketplace","finance_or_insurance"}: patterns.append("packages comparison, cost or buyer guidance")
        if st=="competitor_owned": patterns.append("uses model-specific facts in a directly quotable format")
        if st=="forum_social_video": patterns.append("captures lived-experience language and objections")
        for bp in by_type.get(st, [])[:1]:
            extra=text(bp.get("pattern") or bp.get("winning_pattern") or bp.get("description") or bp.get("source_pattern"), 220)
            if extra: patterns.append(extra)
        if not patterns: patterns.append("uses extractable answer wording")
        out.append({
            "source_url": c["url"], "source_domain": c.get("domain") or domain(c["url"]), "source_type": st,
            "pattern_type": "; ".join(dict.fromkeys(patterns)),
            "owned_content_implication": "Replicate the useful answer structure on mapped owned pages using verified brand facts only.",
            "pr_implication": "Create corroborating third-party proof where owned pages cannot credibly self-validate the claim.",
            "evidence_basis": sn or f"{c.get('domain') or domain(c['url'])} appeared as a top external citation for this query.",
        })
    return out


def cms_recs(query: str, qid: str, mapped: list[dict], patterns: list[dict]) -> list[dict]:
    recs=[]
    pat="; ".join(sorted({p["pattern_type"] for p in patterns})) or "answer-first extractable evidence"
    for m in mapped:
        fname=(m["url"].rstrip("/").split("/")[-1] or "owned page")
        recs.append({
            "recommendation_id": stable_id("cms", qid, m["url"]),
            "query_id": qid,
            "query": query,
            "target_url": m["url"],
            "title": f"Add query-specific answer module to {fname}",
            "owner": "AEM/CMS + Product",
            "priority": "High" if m.get("current_geo_score_120",0)<70 else "Medium",
            "module_type": "answer_first_summary_plus_faq",
            "placement": "Above detailed product copy / below hero",
            "recommendation": f"Create a concise answer-first section for: {query}",
            "winning_pattern_to_copy": pat,
            "content_requirements": [
                "State the direct answer in the first 120-180 words.",
                "Use only verified product, pricing, warranty, charging, safety or ownership facts already approved for the market.",
                "Mirror the external winning structure without copying external wording.",
                "Add FAQ schema only where the page already supports the answer.",
                "Write recommendations and dashboard copy in English by default; include local Japanese terms only as evidence labels where useful.",
            ],
            "geo_gaps_addressed": m.get("geo_gaps") or [],
            "validation_required": ["Product", "Legal/Compliance"],
        })
    return recs


def pr_recs(query: str, qid: str, citations: list[dict], patterns: list[dict]) -> list[dict]:
    if not citations: return []
    types=sorted({c.get("source_type") for c in citations if c.get("source_type")})
    domains=sorted({c.get("domain") or domain(c.get("url")) for c in citations if c.get("url")})
    return [{
        "recommendation_id": stable_id("pr", qid, ",".join(types), ",".join(domains)),
        "query_id": qid,
        "query": query,
        "title": f"Build external proof for: {query[:90]}",
        "owner": "PR / Communications",
        "priority": "High" if any(t in {"publisher_review","authority_body","partner_infrastructure","competitor_owned"} for t in types) else "Medium",
        "target_source_types": types,
        "target_domains_observed": domains,
        "recommendation": "Secure or create credible third-party-referenceable evidence that can corroborate the owned-page answer.",
        "why_it_matters": "Current AI answers rely on external citations; owned content needs independent corroboration to shift the answer source mix.",
        "evidence_basis": "; ".join(p.get("evidence_basis","") for p in patterns[:2]),
    }]



def module_type_for_query(query: str, patterns: list[dict] | None = None) -> str:
    q=(query or '').lower()
    if any(x in q for x in ['cost','price','finance','lease','insurance','resale','running cost','total cost']):
        return 'cost_and_ownership_proof'
    if any(x in q for x in ['warranty','guarantee','保証']):
        return 'warranty_and_coverage_faq'
    if any(x in q for x in ['charging','charger','charge','range','battery','ev']):
        return 'charging_range_answer_block'
    if any(x in q for x in ['safety','adas','crash','collision','rating']):
        return 'safety_proof_block'
    if any(x in q for x in ['family','seat','luggage','storage','comfort','minivan']):
        return 'family_practicality_buyer_checklist'
    if any(x in q for x in ['hybrid','e-power','powertrain','fuel']):
        return 'powertrain_explainer'
    return 'answer_first_summary_plus_faq'


def module_label(module_type: str) -> str:
    labels={
        'cost_and_ownership_proof':'cost and ownership proof module',
        'warranty_and_coverage_faq':'warranty and coverage FAQ module',
        'charging_range_answer_block':'charging/range answer block',
        'safety_proof_block':'safety proof block',
        'family_practicality_buyer_checklist':'family practicality checklist',
        'powertrain_explainer':'powertrain explainer',
        'answer_first_summary_plus_faq':'answer-first summary and FAQ module',
    }
    return labels.get(module_type,module_type.replace('_',' '))


def pattern_value_weight(pattern: dict) -> int:
    st=pattern.get('source_type') or ''
    txt=text(pattern)
    w=1
    if st in {'authority_body','partner_infrastructure','publisher_review','finance_or_insurance'}: w += 3
    if st in {'competitor_owned','aggregator_marketplace'}: w += 2
    if re.search(r'\d', txt): w += 2
    if any(x in txt.lower() for x in ['statistics','numeric','warranty','cost','range','rating','official','third-party','authority']): w += 1
    if st == 'forum_social_video': w += 0
    return w


def action_verb(module_type: str) -> str:
    if module_type == 'cost_and_ownership_proof': return 'Add ownership-cost evidence block'
    if module_type == 'warranty_and_coverage_faq': return 'Add warranty and coverage FAQ'
    if module_type == 'charging_range_answer_block': return 'Add charging/range answer block'
    if module_type == 'safety_proof_block': return 'Add safety proof block'
    if module_type == 'family_practicality_buyer_checklist': return 'Add family practicality checklist'
    if module_type == 'powertrain_explainer': return 'Add e-POWER / powertrain explainer'
    return 'Add answer-first citation module'


def aggregate_page_level_cms(qwork: list[dict], max_changes_per_page: int = 3) -> tuple[list[dict], list[dict]]:
    """Aggregate all query-level patterns into page-level high-value CMS changes.

    The loop owner implements pages, not individual query rows. This function keeps
    query lineage but prioritises the smallest number of page changes that can move
    GEO readiness and AI visibility across many queries.
    """
    page_groups=defaultdict(lambda: {
        'url':'','title':'','journeys':Counter(),'queries':[], 'module_groups':defaultdict(lambda:{
            'module_type':'','queries':[], 'patterns':[], 'source_types':Counter(), 'external_domains':Counter(), 'geo_gaps':Counter(), 'value_score':0
        }), 'geo_scores':[], 'geo_gaps':Counter()
    })
    for q in qwork:
        qid=q.get('query_id'); query=q.get('query') or ''; journey=q.get('journey_category') or 'Unclassified'
        visibility=q.get('current_ai_visibility') or {}
        patterns=q.get('winning_patterns') or []
        mapped=q.get('mapped_owned_urls') or []
        if not mapped: continue
        # Use all mapped URLs, but give the strongest credit to top-ranked pages.
        for m in mapped:
            url=m.get('url')
            if not url: continue
            grp=page_groups[url]
            grp['url']=url; grp['title']=m.get('title') or grp.get('title') or ''
            grp['journeys'][journey]+=1
            grp['geo_scores'].append(m.get('current_geo_score_120') or 0)
            for gap in m.get('geo_gaps') or []: grp['geo_gaps'][gap]+=1
            mod=module_type_for_query(query, patterns)
            mg=grp['module_groups'][mod]
            mg['module_type']=mod
            query_value=1
            if visibility.get('status') in {'external_led','competitor_led'}: query_value += 3
            if not visibility.get('owned_target_cited'): query_value += 2
            query_value += max(0, 4-int(m.get('rank') or 3))
            query_value += min(5, len(patterns))
            mg['value_score'] += query_value
            mg['queries'].append({'query_id':qid,'query':query,'journey_category':journey,'visibility_status':visibility.get('status'),'ai_visibility_score':visibility.get('score')})
            for p in patterns:
                mg['patterns'].append(p)
                if p.get('source_type'): mg['source_types'][p.get('source_type')]+=1
                if p.get('source_domain'): mg['external_domains'][p.get('source_domain')]+=1
                mg['value_score'] += pattern_value_weight(p)
    page_recs=[]; actions=[]
    for url,grp in page_groups.items():
        ranked=sorted(grp['module_groups'].values(), key=lambda x:(x['value_score'], len(x['queries'])), reverse=True)[:max_changes_per_page]
        avg_geo=round(sum(float(x or 0) for x in grp['geo_scores'])/max(1,len(grp['geo_scores'])),1)
        primary_journey=grp['journeys'].most_common(1)[0][0] if grp['journeys'] else 'Unclassified'
        for idx,mg in enumerate(ranked, start=1):
            module_type=mg['module_type']
            linked_queries=mg['queries']
            unique_q=list({q['query_id']:q for q in linked_queries}.values())
            priority='High' if len(unique_q)>=3 or mg['value_score']>=30 or avg_geo<65 else ('Medium' if len(unique_q)>=2 else 'Low')
            top_patterns=[]
            seen=set()
            for pat in sorted(mg['patterns'], key=pattern_value_weight, reverse=True):
                key=(pat.get('source_type'), pat.get('pattern_type'))
                if key in seen: continue
                seen.add(key); top_patterns.append(pat)
                if len(top_patterns)>=5: break
            source_types=[{'source_type':k,'count':v} for k,v in mg['source_types'].most_common(5)]
            domains=[{'domain':k,'count':v} for k,v in mg['external_domains'].most_common(5)]
            rec_id=stable_id('pagecms',url,module_type)
            rec={
                'recommendation_id':rec_id,
                'target_url':url,
                'page_title':grp.get('title',''),
                'journey_category':primary_journey,
                'module_type':module_type,
                'title':f"{action_verb(module_type)} on page",
                'owner':'AEM/CMS + Product',
                'priority':priority,
                'value_score':round(mg['value_score'],1),
                'query_coverage_count':len(unique_q),
                'linked_queries':unique_q,
                'current_geo_score_120':avg_geo,
                'geo_gaps_addressed':[k for k,_ in grp['geo_gaps'].most_common(5)],
                'source_types_benchmarked':source_types,
                'external_domains_benchmarked':domains,
                'winning_patterns_to_aggregate':top_patterns,
                'recommended_change':f"Create one {module_label(module_type)} that answers the highest-value recurring query intents for this page, using the observed external winning patterns as structure but only verified owned facts as claims.",
                'content_requirements':[
                    'Aggregate overlapping query needs into one reusable page module rather than one module per query.',
                    'Open with a direct, quotable answer and then add proof, caveats and decision criteria.',
                    'Use verified brand facts only; do not copy or fabricate external-source claims.',
                    'Prefer statistics, citations, quotations, tables or FAQs where the evidence supports them.',
                    'Track post-update movement in both page GEO score and query AI visibility score.'
                ],
                'expected_impact':{
                    'geo_score_target_delta':'+8 to +20 points where evidence gaps are addressed',
                    'ai_visibility_target':'Increase owned target-page citation and reduce external/competitor-led status across linked queries',
                    'rerun_success_measures':['owned_target_cited=true for linked queries','higher page GEO score','reduced competitor/external-led count']
                },
                'validation_required':['Product','Legal/Compliance','SEO/GEO lead'],
            'output_language':'English',
            'copy_language_policy':'Write all CMS-ready headings, intro copy, body copy, bullets and FAQ items in English. Translate Japanese source evidence into English; keep Japanese terms only as named entities.'
            }
            page_recs.append(rec)
            actions.append({
                'action_id':stable_id('actcms',url,module_type),
                'action':f"{action_verb(module_type)}: {url}",
                'owner':'AEM/CMS + Product',
                'priority':priority,
                'effort':'M' if len(unique_q)<=4 else 'L',
                'status':'Not started',
                'target_url':url,
                'workstream':'CMS page optimisation',
                'source':'Page-level CMS recommendation',
                'value_score':round(mg['value_score'],1),
                'linked_query_ids':[q['query_id'] for q in unique_q],
                'query_coverage_count':len(unique_q),
                'module_type':module_type,
                'tracking_metrics':['page_geo_score_120','linked_query_ai_visibility_score','owned_target_citation_count']
            })
    # keep only high/medium value items; low stays in recs but not primary action backlog
    actions=[a for a in actions if a['priority'] in {'High','Medium'}]
    actions.sort(key=lambda a:({'High':0,'Medium':1,'Low':2}.get(a['priority'],3), -a.get('query_coverage_count',0), -a.get('value_score',0)))
    page_recs.sort(key=lambda r:({'High':0,'Medium':1,'Low':2}.get(r['priority'],3), -r.get('query_coverage_count',0), -r.get('value_score',0)))
    return page_recs, actions


def aggregate_pr_opportunities(qwork: list[dict], max_items: int = 20) -> tuple[list[dict], list[dict]]:
    """Aggregate PR opportunities by source type/theme and grouped queries.

    PR recommendations deliberately do not target owned URLs. They track external
    proof gaps and grouped query clusters where third-party validation can move
    AI visibility across many queries.
    """
    groups=defaultdict(lambda:{'source_type':'','journeys':Counter(),'queries':[], 'domains':Counter(), 'patterns':[], 'value_score':0, 'competitors':Counter()})
    for q in qwork:
        qid=q.get('query_id'); query=q.get('query') or ''; journey=q.get('journey_category') or 'Unclassified'
        vis=q.get('current_ai_visibility') or {}
        for comp in vis.get('competitors') or []: pass
        for c in q.get('external_top3_benchmark') or []:
            st=c.get('source_type') or 'other'
            if st in {'owned_brand_ecosystem'}: continue
            grp=groups[st]; grp['source_type']=st; grp['journeys'][journey]+=1
            grp['domains'][c.get('domain') or domain(c.get('url'))]+=1
            query_value=1
            if vis.get('status') in {'external_led','competitor_led'}: query_value += 3
            if not vis.get('owned_target_cited'): query_value += 2
            if st in {'authority_body','publisher_review','partner_infrastructure','finance_or_insurance'}: query_value += 3
            if st == 'forum_social_video': query_value += 1
            grp['value_score'] += query_value
            grp['queries'].append({'query_id':qid,'query':query,'journey_category':journey,'visibility_status':vis.get('status'),'ai_visibility_score':vis.get('score')})
            for comp in vis.get('competitors') or []: grp['competitors'][comp]+=1
        for p in q.get('winning_patterns') or []:
            st=p.get('source_type') or 'other'
            if st in groups: groups[st]['patterns'].append(p)
    out=[]; actions=[]
    for st,grp in groups.items():
        unique_q=list({q['query_id']:q for q in grp['queries']}.values())
        if len(unique_q)<2 and grp['value_score']<12:
            continue
        priority='High' if len(unique_q)>=5 or grp['value_score']>=35 else 'Medium'
        if st == 'forum_social_video':
            opportunity_type='objection_evidence_and_community_signal'
            action='Monitor and address recurring community objections with credible owned and third-party explainers'
        elif st in {'authority_body','partner_infrastructure'}:
            opportunity_type='authority_or_partner_proof'
            action='Create or secure authoritative third-party proof points aligned to recurring buyer questions'
        elif st in {'publisher_review','finance_or_insurance','aggregator_marketplace'}:
            opportunity_type='publisher_and_comparison_coverage'
            action='Secure neutral comparison/publisher coverage with verifiable facts and decision criteria'
        elif st == 'competitor_owned':
            opportunity_type='competitor_displacement_evidence'
            action='Build third-party validation that offsets competitor-owned evidence in AI answers'
        else:
            opportunity_type='external_proof_gap'
            action='Create third-party-referenceable proof assets for recurring AI answer gaps'
        opp_id=stable_id('prgrp',st,','.join(q['query_id'] for q in unique_q[:20]))
        top_patterns=[]; seen=set()
        for p in sorted(grp['patterns'], key=pattern_value_weight, reverse=True):
            key=(p.get('source_type'),p.get('pattern_type'))
            if key in seen: continue
            seen.add(key); top_patterns.append(p)
            if len(top_patterns)>=5: break
        rec={
            'recommendation_id':opp_id,
            'opportunity_type':opportunity_type,
            'source_type':st,
            'title':action,
            'owner':'PR / Communications',
            'priority':priority,
            'value_score':round(grp['value_score'],1),
            'query_coverage_count':len(unique_q),
            'grouped_queries':unique_q,
            'journey_mix':[{'journey_category':k,'count':v} for k,v in grp['journeys'].most_common()],
            'observed_external_domains':[{'domain':k,'count':v} for k,v in grp['domains'].most_common(10)],
            'competitors_observed':[{'competitor':k,'count':v} for k,v in grp['competitors'].most_common(8)],
            'winning_patterns_observed':top_patterns,
            'recommended_pr_action':action,
            'why_it_matters':'This external source pattern influences multiple queries, so it is a higher-value PR lever than query-by-query outreach.',
            'tracking_metrics':['grouped_query_ai_visibility_score','external_led_query_count','owned_domain_citation_count','competitor_led_query_count'],
            'exclusions':['No owned URL target is assigned to PR actions; PR is tracked by query group and source landscape only.']
        }
        out.append(rec)
        actions.append({
            'action_id':stable_id('actpr',st,opp_id),
            'action':action,
            'owner':'PR / Communications',
            'priority':priority,
            'effort':'M' if len(unique_q)<=6 else 'L',
            'status':'Not started',
            'workstream':'PR / external proof',
            'source':'Grouped PR opportunity',
            'source_type':st,
            'value_score':round(grp['value_score'],1),
            'linked_query_ids':[q['query_id'] for q in unique_q],
            'query_coverage_count':len(unique_q),
            'tracking_metrics':['grouped_query_ai_visibility_score','external_citation_mix','competitor_displacement']
        })
    out.sort(key=lambda r:({'High':0,'Medium':1}.get(r['priority'],2), -r.get('query_coverage_count',0), -r.get('value_score',0)))
    actions.sort(key=lambda a:({'High':0,'Medium':1}.get(a['priority'],2), -a.get('query_coverage_count',0), -a.get('value_score',0)))
    return out[:max_items], actions[:max_items]

def visibility_score(status: str, owned_target: bool, owned_domain: bool, competitors: list[str], external_count: int) -> int:
    score=0
    if owned_target: score+=55
    elif owned_domain: score+=30
    if not competitors: score+=15
    else: score+=max(0, 12-len(competitors)*4)
    score+=min(20, external_count*4)
    if "competitor" in status: score-=15
    if "external" in status: score-=8
    return max(0,min(100,score))




def build_brand_topic_scorecard(qwork: list[dict], run_history: list[dict] | None = None) -> list[dict]:
    """Build a CMO-ready topic scorecard from query-level evidence.

    This is intentionally deterministic. LLM nodes may polish narrative elsewhere,
    but numeric values and evidence caveats should originate here so the executive
    report is stable across uploads, latest-run loads and API-triggered refreshes.
    """
    groups = defaultdict(lambda: {
        "topic": "Unclassified",
        "queries": [],
        "scores": [],
        "owned_urls": set(),
        "citations": 0,
        "owned_target_citations": 0,
        "owned_domain_citations": 0,
        "competitors": Counter(),
        "source_types": Counter(),
        "statuses": Counter(),
        "delta_values": [],
    })
    for q in qwork or []:
        if not isinstance(q, dict):
            continue
        topic = text(q.get("brand_topic_category") or q.get("journey_category") or q.get("topic") or "Unclassified") or "Unclassified"
        topic = topic.replace("&amp;", "&")
        grp = groups[topic]
        grp["topic"] = topic
        vis = q.get("current_ai_visibility") if isinstance(q.get("current_ai_visibility"), dict) else {}
        query_id_value = text(q.get("query_id") or q.get("id") or q.get("query"))
        grp["queries"].append(query_id_value)
        status = text(vis.get("status") or q.get("visibility_status") or "not_collected") or "not_collected"
        grp["statuses"][status] += 1
        citations = vis.get("top_citations") if isinstance(vis.get("top_citations"), list) else []
        ext = q.get("external_top3_benchmark") if isinstance(q.get("external_top3_benchmark"), list) else []
        citation_count = len(citations) or len(ext)
        grp["citations"] += citation_count
        if vis.get("owned_target_cited"):
            grp["owned_target_citations"] += 1
        if vis.get("owned_domain_cited"):
            grp["owned_domain_citations"] += 1
        score_value = vis.get("score")
        try:
            score_float = float(score_value)
            if citation_count > 0 or status not in {"not_collected", "not_observed", "unknown"}:
                grp["scores"].append(score_float)
        except Exception:
            pass
        for comp in vis.get("competitors") or []:
            name = text(comp)
            if name:
                grp["competitors"][name] += 1
        for c in citations + ext:
            if isinstance(c, dict):
                st = text(c.get("source_type") or c.get("sourceType") or c.get("source_category"))
                if st:
                    grp["source_types"][st] += 1
                if c.get("is_competitor"):
                    d = text(c.get("domain") or domain(c.get("url")))
                    if d:
                        grp["competitors"][d] += 1
        for u in q.get("mapped_owned_urls") or []:
            if isinstance(u, dict) and u.get("url"):
                grp["owned_urls"].add(text(u.get("url")))
        prev = q.get("previous_run_delta")
        if isinstance(prev, dict):
            for k in ["ai_visibility_delta", "score_delta", "delta", "visibility_delta"]:
                try:
                    grp["delta_values"].append(float(prev[k]))
                    break
                except Exception:
                    continue
    rows = []
    for topic, grp in groups.items():
        query_count = len([q for q in grp["queries"] if q])
        if query_count == 0:
            continue
        scores = grp["scores"]
        avg_score = round(sum(scores) / len(scores), 1) if scores else None
        citation_count = int(grp["citations"])
        top_comp = grp["competitors"].most_common(1)[0][0] if grp["competitors"] else ""
        top_status = grp["statuses"].most_common(1)[0][0] if grp["statuses"] else "not_collected"
        if citation_count == 0:
            relative = "Requires fresh AI citation evidence"
        elif top_comp:
            relative = f"Benchmark against {top_comp}"
        elif grp["owned_target_citations"]:
            relative = "Owned target pages present in citation set"
        elif grp["owned_domain_citations"]:
            relative = "Owned domain visible, target-page ownership weak"
        else:
            relative = "External/category sources dominate observed citations"
        if grp["delta_values"]:
            delta = round(sum(grp["delta_values"]) / len(grp["delta_values"]), 1)
            direction = (f"+{delta} pts" if delta > 0 else f"{delta} pts" if delta < 0 else "Flat")
        else:
            direction = "Not available"
        if citation_count == 0:
            comment = f"{topic} has {query_count} mapped quer{'y' if query_count == 1 else 'ies'} and {len(grp['owned_urls'])} owned URL candidate{'s' if len(grp['owned_urls']) != 1 else ''}, but fresh AI citation evidence was not collected for this run."
        elif avg_score is not None and avg_score >= 70:
            comment = "Strong topic visibility; maintain evidence freshness and monitor competitor movement."
        elif avg_score is not None and avg_score >= 45:
            comment = "Present in AI evidence but not clearly owned; strengthen answer-first owned modules and proof points."
        else:
            comment = "Underrepresented in AI narratives; prioritise owned-page coverage and external authority signals."
        row = {
            "topic": topic,
            "aiVisibilityScore": avg_score,
            "relativePosition": relative,
            "directionVsLastPeriod": direction,
            "comment": comment,
            "queryCount": query_count,
            "ownedUrlCount": len(grp["owned_urls"]),
            "citationCount": citation_count,
            "ownedTargetCitationCount": int(grp["owned_target_citations"]),
            "ownedDomainCitationCount": int(grp["owned_domain_citations"]),
            "dominantVisibilityStatus": top_status,
            "topCompetitorOrExternal": top_comp,
            "sourceTypeMix": [{"source_type": k, "count": v} for k, v in grp["source_types"].most_common(5)],
        }
        # snake_case aliases for LLM/Bodhi consumers that do not preserve camelCase.
        row["ai_visibility_score"] = avg_score
        row["relative_position"] = relative
        row["direction_vs_last_period"] = direction
        row["query_count"] = query_count
        row["owned_url_count"] = len(grp["owned_urls"])
        row["citation_count"] = citation_count
        rows.append(row)
    rows.sort(key=lambda r: (-(r.get("queryCount") or 0), -(r.get("citationCount") or 0), -((r.get("aiVisibilityScore") or -1) if r.get("aiVisibilityScore") is not None else -1), r.get("topic") or ""))
    return rows[:12]



def upgrade_canonical_bundle(existing: dict, args) -> dict:
    """Upgrade an existing query_workbench.v1 bundle to the page-level CMS/grouped PR contract."""
    qwork=existing.get('query_workbench') or []
    if not isinstance(qwork, list): qwork=[]
    source_counts=Counter(); competitor_counts=Counter(); all_cms=[]; all_pr=[]
    for q in qwork:
        if not isinstance(q, dict): continue
        for c in (q.get('current_ai_visibility') or {}).get('top_citations') or []:
            if isinstance(c, dict): source_counts[c.get('source_type') or source_type(c.get('url',''))]+=1
        for comp in (q.get('current_ai_visibility') or {}).get('competitors') or []:
            competitor_counts[comp]+=1
        for c in q.get('cms_recommendations') or []:
            if isinstance(c,dict): all_cms.append(c)
        for pr in q.get('pr_recommendations') or []:
            if isinstance(pr,dict): all_pr.append(pr)
    owned_summary=existing.get('owned_url_readiness') if isinstance(existing.get('owned_url_readiness'), list) else build_owned_summary(qwork)
    upgraded=assemble_bundle(args, qwork, owned_summary, all_cms, all_pr, existing.get('action_checklist') or [], source_counts, competitor_counts)
    # Preserve LLM and render fields from the existing run, but do not override canonical recommendations/actions.
    preserve_keys=['executive_report','executive_kpis','dashboard_summary','visibility','cms_generation_summary','pr_strategy_synthesis','query_strategy_synthesis','executive_synthesis','validation','parser_manifest','cms_ready_content_modules']
    for k in preserve_keys:
        if k in existing: upgraded[k]=existing[k]
    upgraded['legacy_cms_recommendations']=existing.get('cms_recommendations') or []
    upgraded['legacy_pr_opportunities']=existing.get('pr_opportunities') or []
    upgraded['legacy_action_checklist']=existing.get('action_checklist') or []
    upgraded.setdefault('parser_manifest',{}).update({
        'upgraded_to_contract':'page_level_cms_grouped_pr.v2',
        'page_level_cms_recommendations':len(upgraded.get('page_level_cms_recommendations') or []),
        'grouped_pr_opportunities':len(upgraded.get('grouped_pr_opportunities') or []),
        'canonical_action_count':len(upgraded.get('action_checklist') or []),
    })
    return upgraded

def find_canonical_payload(obj: Any) -> Any:
    if isinstance(obj, dict):
        if obj.get("schema_version") == "query_workbench.v1" and isinstance(obj.get("query_workbench"), list): return obj
        if isinstance(obj.get("frontend_report_bundle"), dict):
            got=find_canonical_payload(obj["frontend_report_bundle"])
            if got: return got
        for key in ["data", "layout", "input"]:
            got=find_canonical_payload(obj.get(key))
            if got: return got
        default=obj.get("default") or obj.get("stdout") or obj.get("response")
        if isinstance(default, str) and default.strip().startswith(("{","[")):
            try:
                got=find_canonical_payload(json.loads(default))
                if got: return got
            except Exception: pass
        for v in obj.values():
            got=find_canonical_payload(v)
            if got: return got
    elif isinstance(obj, list):
        for v in obj:
            got=find_canonical_payload(v)
            if got: return got
    return None


def find_preview_payload(obj: Any) -> dict | None:
    if isinstance(obj, dict):
        if isinstance(obj.get("query_evidence"), list) and (isinstance(obj.get("owned_readiness"), list) or isinstance(obj.get("source_landscape"), dict)):
            return obj
        if obj.get("schema_version") == "frontend_report_bundle_v1_preview_contract": return obj
        # Bodhi output node stdout
        if "Frontend Preview Bundle Builder" in obj and isinstance(obj["Frontend Preview Bundle Builder"], dict):
            st=(obj["Frontend Preview Bundle Builder"].get("data") or {}).get("stdout")
            if isinstance(st,str):
                try: return find_preview_payload(json.loads(st))
                except Exception: pass
        for v in obj.values():
            if isinstance(v,str) and v.strip().startswith("{"):
                try:
                    got=find_preview_payload(json.loads(v))
                    if got: return got
                except Exception: pass
            got=find_preview_payload(v)
            if got: return got
    elif isinstance(obj, list):
        for v in obj:
            got=find_preview_payload(v)
            if got: return got
    return None


def write_compact_files_from_payload(root: Path, payload: Any) -> bool:
    if not isinstance(payload, dict): return False
    candidates=[]
    for key in ["files","bodhi_compact","compact_bundle","bundle","data","run","evidence","outputs"]:
        v=payload.get(key)
        if isinstance(v, dict): candidates.append(v)
    candidates.append(payload)
    mapping={
        "audit_context":["audit_context","audit_context.json","outputs/audit_context/audit_context.json"],
        "evidence_scope":["evidence_scope","evidence_scope.json","outputs/evidence_scope/evidence_scope.json"],
        "google_ai_mode_compact":["google_ai_mode_compact","google_ai_mode_compact.json","outputs/google_ai_mode/google_ai_mode_compact.json"],
        "owned_pages_full":["owned_pages_full","owned_pages_full.json","outputs/content_intelligence/owned_pages_full.json"],
        "external_pages_full":["external_pages_full","external_pages_full.json","outputs/external_pages/external_pages_full.json"],
        "visibility_matrix":["visibility_matrix","visibility_matrix.json","outputs/visibility/visibility_matrix.json"],
        "source_classification":["source_classification","source_classification.json","outputs/source_landscape/source_classification.json"],
        "ai_visibility_scores":["ai_visibility_scores","ai_visibility_scores.json","outputs/visibility/ai_visibility_scores.json"],
        "winning_source_patterns":["winning_source_patterns","winning_source_patterns.json","outputs/benchmark/winning_source_patterns.json"],
        "source_preference_benchmark":["source_preference_benchmark","source_preference_benchmark.json","outputs/benchmark/source_preference_benchmark.json"],
    }
    paths={
        "audit_context":"outputs/audit_context/audit_context.json",
        "evidence_scope":"outputs/evidence_scope/evidence_scope.json",
        "google_ai_mode_compact":"outputs/google_ai_mode/google_ai_mode_compact.json",
        "owned_pages_full":"outputs/content_intelligence/owned_pages_full.json",
        "external_pages_full":"outputs/external_pages/external_pages_full.json",
        "visibility_matrix":"outputs/visibility/visibility_matrix.json",
        "source_classification":"outputs/source_landscape/source_classification.json",
        "ai_visibility_scores":"outputs/visibility/ai_visibility_scores.json",
        "winning_source_patterns":"outputs/benchmark/winning_source_patterns.json",
        "source_preference_benchmark":"outputs/benchmark/source_preference_benchmark.json",
    }
    wrote=False
    for canonical,names in mapping.items():
        value=None
        for obj in candidates:
            for name in names:
                if name in obj:
                    value=obj[name]; break
            if value is not None: break
        if isinstance(value, dict) and "content" in value: value=value["content"]
        if isinstance(value, dict) and "data" in value and len(value)==1: value=value["data"]
        if isinstance(value, str):
            st=value.strip()
            if st.startswith(("{","[")):
                try: value=json.loads(st)
                except Exception: pass
        if value is not None:
            write_json(root/paths[canonical], value); wrote=True
    return wrote


def build_from_preview(preview: dict, args) -> dict:
    qrows=preview.get("query_evidence") or []
    owned_pages=preview.get("owned_readiness") or []
    old_kpis=preview.get("executive_kpis") if isinstance(preview.get("executive_kpis"),dict) else {}
    sl=preview.get("source_landscape") if isinstance(preview.get("source_landscape"),dict) else {}
    sources=sl.get("sources") if isinstance(sl.get("sources"),list) else []
    visibility=preview.get("visibility") if isinstance(preview.get("visibility"),dict) else {}
    patterns_lookup=visibility.get("external_benchmark_patterns") or []
    sources_by_q=defaultdict(list)
    for s in sources:
        if isinstance(s,dict):
            c=normalise_citation({**s,"url":s.get("source_url") or s.get("url"),"domain":s.get("source_domain") or s.get("domain")}, len(sources_by_q[text(s.get("query_id"))])+1)
            c["is_owned_domain"] = bool(s.get("is_owned_domain") or is_owned(c["url"]))
            c["is_owned_target_page"] = bool(s.get("is_owned_target_page"))
            c["is_competitor"] = bool(s.get("is_competitor") or c["source_type"]=="competitor_owned")
            sources_by_q[text(s.get("query_id"))].append(c)
    meta_index = build_query_metadata_index(preview)
    qwork=[]; all_cms=[]; all_pr=[]; actions_by_key={}; source_counts=Counter(); competitor_counts=Counter()
    for i,row in enumerate(qrows):
        row=record_dict(row, default_key="query")
        qid=query_id(row,i); q=normalise_query(row)
        row=enrich_query_row(row, qid, q, meta_index)
        tax=query_taxonomy(row); cat=tax["journey_category"]
        citations=[normalise_citation(c, j+1) for j,c in enumerate(row.get("citations") or []) if isinstance(c,dict)]
        if not citations and sources_by_q.get(qid): citations=sources_by_q[qid]
        for c in citations: source_counts[c["source_type"]]+=1
        competitors=list(row.get("competitor_brands_detected") or []) if isinstance(row.get("competitor_brands_detected"),list) else []
        if isinstance(row.get("competitor_brands_detected"),dict): competitors=[k.title() for k,v in row["competitor_brands_detected"].items() if v]
        if not competitors: competitors=detect_competitors(text(row), citations)
        for comp in competitors: competitor_counts[comp]+=1
        status=classify_visibility(row,citations,competitors)
        mapped=map_owned_urls(q, owned_pages, args.max_owned, qid=qid, category=cat)
        top3=external_top3_from_citations(citations, getattr(args, "max_external", 3))
        pats=winning_patterns(q, top3, patterns_lookup)
        cms=cms_recs(q,qid,mapped,pats); pr=pr_recs(q,qid,top3,pats)
        all_cms.extend(cms); all_pr.extend(pr)
        owned_target=bool(row.get("owned_target_page_cited") or row.get("owned_target_page_citations") or any(c.get("is_owned_target_page") for c in citations))
        owned_domain=bool(row.get("owned_domain_citations") or any(c.get("is_owned_domain") for c in citations))
        score=row.get("ai_visibility_score")
        try: score=int(float(score))
        except Exception: score=visibility_score(status,owned_target,owned_domain,competitors,len(top3))
        item={
            "query_id":qid,"query":q,"query_type":row.get("query_type") or ("branded" if args.brand and args.brand.lower() in q.lower() else "non_branded"),"journey_category":cat,
            **tax,
            "current_ai_visibility":{"score":score,"status":status,"owned_target_cited":owned_target,"owned_domain_cited":owned_domain,"competitors":competitors,"competitor_citation_count":int(row.get("competitor_citation_count") or len(competitors)),"top_citations":citations[:8]},
            "mapped_owned_urls":mapped,"external_top3_benchmark":top3,"winning_patterns":pats,"cms_recommendations":cms,"pr_recommendations":pr,"action_items":[],"previous_run_delta":None,"loop_state":"baseline_ready" if not owned_target else "monitor_and_refresh",
        }
        item["action_items"]=[{"action":c["title"],"owner":c["owner"],"priority":c["priority"],"effort":"M","status":"Not started","target":c["target_url"],"workstream":"CMS remediation","source_query_id":qid} for c in cms[:3]] + [{"action":p["title"],"owner":p["owner"],"priority":p["priority"],"effort":"M","status":"Not started","target":", ".join(p.get("target_domains_observed") or p.get("target_source_types") or []),"workstream":"PR / external proof","source_query_id":qid} for p in pr[:1]]
        for a in item["action_items"]:
            actions_by_key.setdefault((a["workstream"],a.get("target"),a["action"]), {**a,"linked_query_ids":[]})["linked_query_ids"].append(qid)
        qwork.append(item)
    # Prefer previous deduped action checklist if present and valid.
    old_actions=preview.get("action_checklist") if isinstance(preview.get("action_checklist"),list) else []
    action_checklist=old_actions or list(actions_by_key.values())
    owned_summary=build_owned_summary(qwork)
    bundle=assemble_bundle(args, qwork, owned_summary, all_cms, all_pr, action_checklist, source_counts, competitor_counts)
    # Carry rich legacy fields so frontend can render old-quality views too.
    # Carry rich legacy render fields, but do not overwrite the canonical v4
    # page-level CMS recommendations, grouped PR opportunities, or action backlog.
    for k in ["executive_report","executive_kpis","dashboard_summary","source_landscape","visibility","cms_ready_content_modules","cms_generation_summary","pr_strategy_synthesis","action_checklist_summary","validation"]:
        if k in preview: bundle[k]=preview[k]
    if "owned_page_recommendations" in preview:
        bundle["legacy_owned_page_recommendations"] = preview["owned_page_recommendations"]
    if "pr_opportunities" in preview:
        bundle["legacy_query_pr_opportunities"] = preview["pr_opportunities"]
    if "action_checklist" in preview:
        bundle["legacy_action_checklist"] = preview["action_checklist"]
    bundle["parser_manifest"]={**(preview.get("parser_manifest") if isinstance(preview.get("parser_manifest"),dict) else {}), "query_workbench_count":len(qwork), "source_of_truth":"query_workbench_builder_v5_from_preview_or_compact"}
    return bundle


def build_owned_summary(qwork: list[dict]) -> list[dict]:
    byurl={}
    for x in qwork:
        for m in x.get("mapped_owned_urls") or []:
            u=m.get("url")
            if not u: continue
            o=byurl.setdefault(u,{**m,"related_queries":[],"journey_category":x.get("journey_category"),"journeys":Counter()})
            if x.get("journey_category"):
                o["journeys"][x.get("journey_category")]+=1
                o["journey_category"]=o["journeys"].most_common(1)[0][0]
            o["related_queries"].append({"id":x.get("query_id"),"query":x.get("query"),"topic_id":x.get("topic_id"),"topic":x.get("topic"),"journey_category":x.get("journey_category"),"journey_stage":x.get("journey_stage"),"intent":x.get("intent"),"visibility_status":(x.get("current_ai_visibility") or {}).get("status")})
    out=list(byurl.values())
    for item in out:
        item.pop("journeys", None)
    return out


def assemble_bundle(args, qwork, owned_summary, all_cms, all_pr, action_checklist, source_counts, competitor_counts) -> dict:
    qcount=len(qwork)
    avg_ai=round(sum((x.get("current_ai_visibility") or {}).get("score",0) for x in qwork)/max(1,qcount),1)
    target_cites=sum(1 for x in qwork if (x.get("current_ai_visibility") or {}).get("owned_target_cited"))
    domain_cites=sum(1 for x in qwork if (x.get("current_ai_visibility") or {}).get("owned_domain_cited"))
    competitor_led=sum(1 for x in qwork if (x.get("current_ai_visibility") or {}).get("status")=="competitor_led")
    external_led=sum(1 for x in qwork if (x.get("current_ai_visibility") or {}).get("status")=="external_led")
    run_id=args.run_id or f"{args.brand}_{args.market}_{time.strftime('%Y%m%d_%H%M%S')}_baseline".replace(" ","_")

    # Canonical v4 prioritisation: CMS is page-level; PR is query-group/source-landscape level.
    page_cms_recommendations, cms_actions = aggregate_page_level_cms(qwork, max_changes_per_page=3)
    grouped_pr_opportunities, pr_actions = aggregate_pr_opportunities(qwork, max_items=20)
    brand_topic_scorecard = build_brand_topic_scorecard(qwork, run_history=[])
    query_level_cms = all_cms
    query_level_pr = all_pr
    canonical_actions = cms_actions + pr_actions
    if not canonical_actions:
        canonical_actions = action_checklist

    return {
        "schema_version":"query_workbench.v1",
        "contract_version":"page_level_cms_grouped_pr.v2",
        "run_id":run_id,
        "brand":args.brand,
        "market":args.market,
        "domain":args.domain,
        "output_language": getattr(args,"output_language","English") or "English",
        "generated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "locked_orchestration_strategy":"query -> top_3_owned_urls -> top_3_external_citations -> page_level_CMS_changes -> grouped_PR_opportunities -> rerun_delta -> refreshed_recommendations",
        "executive":{
            "summary": f"{args.brand} has {avg_ai}/100 average AI visibility across {qcount} audited queries. CMS work is aggregated by page so the highest-value modules can improve multiple linked queries; PR work is grouped by external source pattern, not owned URL.",
            "what_is_happening":["AI answers are compressing discovery into a small citation set.","Owned pages must compete at query level, but CMS implementation should happen at page level.","External sources reveal the answer structure and evidence patterns that models prefer."],
            "why_now":["Generative engines cite passages, not only rank pages.","Visibility should be managed as a recurring evidence and content loop.","Page-level CMS changes and grouped PR proof assets can be rerun against the same query set to measure GEO and AI visibility deltas."],
            "priority_actions":["Implement top page-level CMS modules that cover the most linked queries.","Prioritise PR opportunities that affect multiple grouped queries; do not map PR actions to owned URLs.","Rerun the same query portfolio after updates and compare page GEO score and query AI visibility deltas."],
            "headline_metrics":{"ai_visibility_score":avg_ai,"query_count":qcount,"owned_page_count":len(owned_summary),"owned_target_page_citations":target_cites,"owned_domain_citations":domain_cites,"competitor_led_query_count":competitor_led,"external_led_query_count":external_led,"external_source_count":sum(source_counts.values()),"average_owned_geo_score_120":round(sum(o.get("current_geo_score_120",0) for o in owned_summary)/max(1,len(owned_summary)),1),"page_level_cms_recommendations":len(page_cms_recommendations),"grouped_pr_opportunities":len(grouped_pr_opportunities),"brand_topic_scorecard_topics":len(brand_topic_scorecard)},
            "brandTopicScorecard": brand_topic_scorecard,
            "brand_topic_scorecard": brand_topic_scorecard
        },
        "executive_summary": {
            "schema_version": "executive_topic_scorecard.v1",
            "brand_topic_scorecard": brand_topic_scorecard,
            "scorecard_methodology": "Grouped from query_workbench by brand topic/journey, using observed AI visibility scores, citation counts, competitor/source evidence, mapped owned URL coverage and previous-run deltas where available."
        },
        "query_workbench":qwork,
        "owned_url_readiness":owned_summary,
        "cms_recommendations":page_cms_recommendations,
        "page_level_cms_recommendations":page_cms_recommendations,
        "query_level_cms_recommendations":query_level_cms,
        "pr_opportunities":grouped_pr_opportunities,
        "grouped_pr_opportunities":grouped_pr_opportunities,
        "query_level_pr_signals":query_level_pr,
        "action_checklist":canonical_actions,
        "source_landscape":{"source_type_counts":[{"source_type":k,"count":v} for k,v in source_counts.most_common()],"competitors":[{"name":k,"count":v} for k,v in competitor_counts.most_common()]},
        "run_history":[],
        "evidence_collection":{
            "run_mode":getattr(args,"run_mode","reuse_existing_evidence"),
            "query_portfolio_mode":getattr(args,"query_portfolio_mode","reuse"),
            "evidence_executor":"railway_evidence_service",
            "bodhi_executes_serpapi":False,
            "bodhi_executes_owned_crawl":False,
            "bodhi_executes_external_crawl":False,
            "requested_serpapi_refresh":str(getattr(args,"enable_serpapi","false")).lower() in {"1","true","yes"},
            "requested_owned_crawl_refresh":str(getattr(args,"enable_owned_crawl","false")).lower() in {"1","true","yes"},
            "requested_external_crawl_refresh":str(getattr(args,"enable_external_crawl","false")).lower() in {"1","true","yes"},
            "max_owned_pages_per_query":getattr(args,"max_owned",3),
            "max_external_citations_per_query":getattr(args,"max_external",3),
            "query_limit":getattr(args,"query_limit",0),
            "output_language":getattr(args,"output_language","English") or "English",
            "copy_language_policy":"All dashboard and CMS-ready copy should be written in English by default; translate/summarise Japanese evidence into English and retain Japanese proper nouns only where useful.",
            "notes":"Bodhi does not call SerpAPI or crawl pages. Refresh execution is owned by Railway evidence service; this builder only consumes stored evidence and assembles the report contract."
        },
        "tracking_plan":{
            "cms_actions_track":["page_geo_score_after_update","linked_query_ai_visibility_after_future_evidence_refresh","owned_target_citation_after_future_evidence_refresh"],
            "pr_actions_track":["affected_query_visibility_after_future_evidence_refresh","new_external_source_mentions_after_future_evidence_refresh","competitor_pressure_after_future_evidence_refresh"]
        },
        "measurement_contract":{
            "cms_tracking_level":"owned_page_url",
            "cms_success_metrics":["page_geo_score_120_delta","linked_query_ai_visibility_score_delta","owned_target_citation_count_delta"],
            "pr_tracking_level":"grouped_queries_and_source_type",
            "pr_success_metrics":["grouped_query_ai_visibility_score_delta","external_led_query_count_delta","competitor_led_query_count_delta"],
            "pr_url_reporting":"disabled; PR actions are not owned-URL-specific"
        },
        "methodology":{"visibility_principles":["Position/citation prominence, owned citation status, competitor displacement and source control are tracked at query level."],"geo_preference_rules":PREFERENCE_RULES,"prioritisation_rules":["CMS recommendations are aggregated by owned URL and ranked by query coverage, evidence value, current visibility gap and GEO gap.","Low-value page changes are retained only as supporting context and excluded from the primary action backlog.","PR opportunities are grouped by source type, journey mix and query coverage; no PR action is assigned to an owned URL."],"refresh_policy":"On rerun, preserve query ids, refresh top citations, recompute page-level CMS and grouped PR recommendations only where evidence changed."},
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--input-json", default="")
    ap.add_argument("--brand", default="", help="Brand name (required)")
    ap.add_argument("--market", default="", help="Market name (required)")
    ap.add_argument("--domain", default="", help="Primary owned domain (required)")
    ap.add_argument("--owned-domains", default="", help="Comma-separated owned domains for brand classification")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--max-owned", type=int, default=3)
    ap.add_argument("--max-external", type=int, default=3)
    ap.add_argument("--run-mode", default="reuse_existing_evidence", choices=["reuse_existing_evidence","fresh_mapping","refresh_owned_pages","refresh_external_pages","fresh_ai_citations","full_refresh"])
    ap.add_argument("--query-portfolio-mode", default="reuse", choices=["reuse","manual","synthetic"])
    ap.add_argument("--query-portfolio", default="", help="Path to query_portfolio JSON from manual input or DeepResearch workflow")
    ap.add_argument("--sitemap-inventory", default="", help="Path to sitemap_inventory JSON generated from site standards / sitemap loader")
    ap.add_argument("--ai-citations", default="", help="Path to normalised AI citations JSON")
    ap.add_argument("--owned-pages", default="", help="Optional owned page crawl evidence JSON")
    ap.add_argument("--external-pages", default="", help="Optional external page crawl evidence JSON")
    ap.add_argument("--enable-serpapi", default="false")
    ap.add_argument("--enable-owned-crawl", default="false")
    ap.add_argument("--enable-external-crawl", default="false")
    ap.add_argument("--query-limit", type=int, default=0)
    ap.add_argument("--output-language", default="English")
    args=ap.parse_args()
    root=Path(args.project_root).resolve()
    # Populate OWNED_HINTS from --owned-domains CLI arg for multi-brand support.
    global OWNED_HINTS
    if args.owned_domains:
        OWNED_HINTS = [d.strip().lower() for d in args.owned_domains.split(',') if d.strip()]
    elif args.domain:
        # Auto-derive from primary domain if no explicit owned domains provided.
        from urllib.parse import urlparse as _urlparse
        _host = _urlparse(args.domain).netloc.lower() or args.domain.replace('https://','').replace('http://','').split('/')[0].lower()
        OWNED_HINTS = [_host, _host.removeprefix('www.'), f'www.{_host.removeprefix("www.")}']
    raw_input=load_json(Path(args.input_json), {}) if args.input_json else {}
    query_portfolio_file = load_json(Path(args.query_portfolio), {}) if args.query_portfolio else load_json(root/'outputs/query_portfolio/query_portfolio.json', {})
    sitemap_inventory_file = load_json(Path(args.sitemap_inventory), {}) if args.sitemap_inventory else load_json(root/'outputs/sitemap/sitemap_inventory.json', {})
    ai_citations_file = load_json(Path(args.ai_citations), {}) if args.ai_citations else load_json(root/'outputs/ai_citations/ai_citations.json', {})
    owned_pages_file = load_json(Path(args.owned_pages), {}) if args.owned_pages else {}
    external_pages_file = load_json(Path(args.external_pages), {}) if args.external_pages else {}
    site_standards_file = load_json(root/'outputs/site_standards/site_standards.json', {}) or {}
    hygiene_sources = [raw_input, query_portfolio_file, sitemap_inventory_file, ai_citations_file, owned_pages_file, external_pages_file, site_standards_file]

    canonical=find_canonical_payload(raw_input) if isinstance(raw_input,dict) else None
    if isinstance(canonical,dict):
        hygiene_sources.append(canonical)
        bundle=upgrade_canonical_bundle(canonical,args)
    else:
        preview=find_preview_payload(raw_input) if isinstance(raw_input,dict) else None
        if preview:
            hygiene_sources.append(preview)
            bundle=build_from_preview(preview,args)
        else:
            if isinstance(raw_input,dict): write_compact_files_from_payload(root, raw_input)
            audit=load_json(root/'outputs/audit_context/audit_context.json', {}) or load_json(root/'inputs/audit_context.json', {}) or {}
            evidence=load_json(root/'outputs/evidence_scope/evidence_scope.json', {}) or {}
            visibility=load_json(root/'outputs/visibility/visibility_matrix.json', {}) or {}
            ai_scores=load_json(root/'outputs/visibility/ai_visibility_scores.json', {}) or {}
            google=load_json(root/'outputs/google_ai_mode/google_ai_mode_compact.json', {}) or {}
            owned_full=load_json(root/'outputs/content_intelligence/owned_pages_full.json', {}) or {}
            source_class=load_json(root/'outputs/source_landscape/source_classification.json', {}) or {}
            patterns=load_json(root/'outputs/benchmark/winning_source_patterns.json', {}) or {}
            hygiene_sources.extend([audit, evidence, visibility, ai_scores, google, owned_full, source_class, patterns])
            meta_index=build_query_metadata_index(query_portfolio_file, audit, evidence, visibility, ai_scores, google)
            query_rows=(as_list(query_portfolio_file,["queries","query_portfolio","items"]) or as_list(visibility,["queries","rows"]) or as_list(ai_scores,["scores","rows"]) or as_list(google,["queries","rows","results"]) or as_list(audit,["queries","query_portfolio"]) or as_list(evidence,["queries","query_scope"]))
            if args.query_limit and len(query_rows) > args.query_limit:
                query_rows = query_rows[:args.query_limit]
            owned_pages=(records_list(owned_pages_file,["pages","owned_pages","items"]) or records_list(sitemap_inventory_file,["urls","pages","owned_pages","items"]) or records_list(owned_full,["pages","owned_pages","items"]) or records_list(audit,["pages","owned_urls","candidate_owned_pages"]) or records_list(evidence,["owned_pages","candidate_owned_pages"]))
            # external/source rows can provide citations by query when visibility rows do not.
            # Include Evidence Service v3.4.7 fields from evidence_scope, source_classification
            # and google_ai_mode_compact so citations are retained when the primary query
            # rows come from the portfolio/audit_context rather than Google rows.
            sources_by_q=defaultdict(list)
            for qid, cites in build_evidence_citations_by_q(evidence, source_class).items():
                sources_by_q[qid].extend(cites)
            for qid, cites in build_google_citations_by_q(google).items():
                sources_by_q[qid].extend(cites)
            legacy_sources=records_list(ai_citations_file,["citations","sources","rows","items"], default_key="url")
            for src in legacy_sources:
                qid=text(src.get("query_id"))
                if qid:
                    sources_by_q[qid].append(normalise_citation({**src,"url":src.get("source_url") or src.get("url")}, len(sources_by_q[qid])+1))
            # de-dupe after combining all source channels
            for qid, cites in list(sources_by_q.items()):
                seen=set(); clean=[]
                for c in cites:
                    u=c.get("url")
                    if u and u not in seen:
                        seen.add(u); clean.append(c)
                sources_by_q[qid]=clean
            score_by_q={str(x.get("query_id") or x.get("id")):x for x in as_list(ai_scores,["scores","rows"]) if isinstance(x,dict)}
            pattern_lookup=as_list(patterns,["patterns","rows"])
            qwork=[]; all_cms=[]; all_pr=[]; source_counts=Counter(); competitor_counts=Counter(); actions_by_key={}
            for i,raw_row in enumerate(query_rows):
                row=record_dict(raw_row, default_key="query"); qid=query_id(row,i); q=normalise_query(row)
                row=enrich_query_row(row, qid, q, meta_index)
                q=normalise_query(row)
                if not q: continue
                tax=query_taxonomy(row); cat=tax["journey_category"]
                citations=refs_from(row) or sources_by_q.get(qid, [])
                for c in citations: source_counts[c["source_type"]]+=1
                competitors=detect_competitors(text(row),citations)
                if isinstance(score_by_q.get(qid,{}).get("competitor_brands_detected"),dict): competitors=[k.title() for k,v in score_by_q[qid]["competitor_brands_detected"].items() if v]
                for comp in competitors: competitor_counts[comp]+=1
                status=classify_visibility({**score_by_q.get(qid,{}),**row},citations,competitors)
                top3=external_top3_from_citations(citations, args.max_external)
                mapped=map_owned_urls(q,owned_pages,args.max_owned,qid=qid,category=cat)
                pats=winning_patterns(q,top3,pattern_lookup)
                cms=cms_recs(q,qid,mapped,pats); pr=pr_recs(q,qid,top3,pats)
                all_cms.extend(cms); all_pr.extend(pr)
                owned_target=any(c.get("is_owned_target_page") for c in citations)
                owned_domain=any(c.get("is_owned_domain") for c in citations)
                sc=score_by_q.get(qid,{})
                try: ai_score=int(float(sc.get("ai_visibility_score")))
                except Exception: ai_score=visibility_score(status,owned_target,owned_domain,competitors,len(top3))
                item={"query_id":qid,"query":q,"query_type":row.get("query_type") or ("branded" if args.brand and args.brand.lower() in q.lower() else "non_branded"),"journey_category":cat,**tax,"current_ai_visibility":{"score":ai_score,"status":status,"owned_target_cited":owned_target,"owned_domain_cited":owned_domain,"competitors":competitors,"competitor_citation_count":len(competitors),"top_citations":citations[:8]},"mapped_owned_urls":mapped,"external_top3_benchmark":top3,"winning_patterns":pats,"cms_recommendations":cms,"pr_recommendations":pr,"action_items":[],"previous_run_delta":None,"loop_state":"baseline_ready" if not owned_target else "monitor_and_refresh"}
                item["action_items"]=[{"action":c["title"],"owner":c["owner"],"priority":c["priority"],"effort":"M","status":"Not started","target":c["target_url"],"workstream":"CMS remediation","source_query_id":qid} for c in cms[:3]] + [{"action":p["title"],"owner":p["owner"],"priority":p["priority"],"effort":"M","status":"Not started","target":", ".join(p.get("target_domains_observed") or []),"workstream":"PR / external proof","source_query_id":qid} for p in pr[:1]]
                for a in item["action_items"]: actions_by_key.setdefault((a["workstream"],a.get("target"),a["action"]), {**a,"linked_query_ids":[]})["linked_query_ids"].append(qid)
                qwork.append(item)
            bundle=assemble_bundle(args,qwork,build_owned_summary(qwork),all_cms,all_pr,list(actions_by_key.values()),source_counts,competitor_counts)
    # validation / quality flags
    qwork=bundle.get("query_workbench") or []
    bundle.setdefault("parser_manifest", {})
    bundle["parser_manifest"].update({
        "query_workbench_count": len(qwork),
        "queries_with_top_citations": sum(1 for q in qwork if (q.get("current_ai_visibility") or {}).get("top_citations")),
        "queries_with_external_top3": sum(1 for q in qwork if q.get("external_top3_benchmark")),
        "queries_with_three_owned_urls": sum(1 for q in qwork if len(q.get("mapped_owned_urls") or []) >= 3),
        "source_of_truth": "query_workbench_builder_v5_phase2",
    })
    bundle.setdefault("validation", {})
    if isinstance(bundle["validation"], dict):
        warnings=[]
        if bundle["parser_manifest"]["queries_with_external_top3"] == 0: warnings.append("No query has external top-3 citations. Recommendations will be generic.")
        if bundle["parser_manifest"]["queries_with_three_owned_urls"] < len(qwork): warnings.append("Some queries have fewer than 3 mapped owned URLs.")
        bundle["validation"]["quality_warnings"] = warnings
        bundle["validation"]["status"] = bundle["validation"].get("status") or ("warning" if warnings else "passed")
    contract_sources = [
        raw_input,
        query_portfolio_file,
        sitemap_inventory_file,
        ai_citations_file,
        owned_pages_file,
        external_pages_file,
        load_json(root/'outputs/audit_context/audit_context.json', {}) or {},
        load_json(root/'outputs/evidence_scope/evidence_scope.json', {}) or {},
        load_json(root/'outputs/google_ai_mode/google_ai_mode_compact.json', {}) or {},
        load_json(root/'outputs/content_intelligence/owned_pages_full.json', {}) or {},
        load_json(root/'outputs/source_landscape/source_classification.json', {}) or {},
    ]
    finalise_frontend_contract(bundle, *contract_sources)
    attach_ai_discoverability_hygiene(bundle, *hygiene_sources)

    # --- Advanced GEO/AEO Recommendation Generator (Epic 3 & 4) ---
    # Attach advanced_geo_asset to CMS recommendations and
    # advanced_pr_asset_pack to PR opportunities using the two-pass
    # fact-matrix architecture. These are optional contract extensions;
    # existing reports without them continue to work.
    try:
        from advanced_cms_generator import attach_advanced_geo_assets_to_bundle
        from advanced_pr_generator import attach_advanced_pr_asset_packs_to_bundle

        # Collect owned page crawl data for fact matrix extraction.
        owned_page_sources = (
            records_list(load_json(root/'outputs/content_intelligence/owned_pages_full.json', {}), ["pages", "owned_pages", "items"])
            or records_list(load_json(Path(args.owned_pages), {}) if args.owned_pages else {}, ["pages", "owned_pages", "items"])
            or records_list(load_json(root/'outputs/sitemap/sitemap_inventory.json', {}), ["urls", "pages", "owned_pages", "items"])
        )
        attach_advanced_geo_assets_to_bundle(
            bundle,
            owned_pages=owned_page_sources,
            brand=args.brand,
            language=getattr(args, 'output_language', 'English') or 'en',
        )
        attach_advanced_pr_asset_packs_to_bundle(bundle, brand=args.brand)
    except Exception as adv_err:
        # Advanced assets are optional; never block the canonical bundle.
        bundle.setdefault("validation", {})["advanced_geo_aeo_error"] = str(adv_err)

    write_json(root/'outputs/query_workbench/query_workbench.json', {"query_workbench": qwork})
    if query_portfolio_file: write_json(root/'outputs/query_portfolio/query_portfolio.normalised.json', query_portfolio_file)
    if sitemap_inventory_file: write_json(root/'outputs/sitemap/sitemap_inventory.normalised.json', sitemap_inventory_file)
    write_json(root/'outputs/frontend_report_bundle.json', bundle)
    write_json(root/'outputs/bodhi/preview_node_bundle.json', bundle)
    write_json(root/'outputs/dashboard/ai_visibility_dashboard_dataset.json', bundle)
    write_json(root/'outputs/actions/action_checklist.json', {"actions": bundle.get("action_checklist", [])})
    print(json.dumps({"status":"ready","run_id":bundle.get("run_id"),"query_count":len(qwork),"queries_with_external_top3":bundle["parser_manifest"]["queries_with_external_top3"],"owned_urls":len(bundle.get("owned_url_readiness") or []),"cms_recommendations":len(bundle.get("cms_recommendations") or []),"pr_opportunities":len(bundle.get("pr_opportunities") or []),"actions":len(bundle.get("action_checklist") or []),"output":"outputs/frontend_report_bundle.json"}, ensure_ascii=False, indent=2))

if __name__=='__main__':
    main()
