from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from lib import (
    get_config,
    read_json,
    write_json,
    resolve_path,
    classify_source_type,
    domain_of,
    compact_whitespace,
    is_owned_url,
)


def load_dotenv_minimal(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def safe_slug(text: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len] or "query"


def query_id(row: Dict[str, Any], idx: int) -> str:
    return str(row.get("query_id") or f"q{idx:03d}")


def raw_output_dir() -> Path:
    p = resolve_path("outputs/google_ai_mode/raw")
    p.mkdir(parents=True, exist_ok=True)
    return p


def raw_output_path(row: Dict[str, Any], idx: int) -> Path:
    qid = query_id(row, idx)
    q = row.get("query", "") or qid
    digest = hashlib.sha1(q.encode("utf-8")).hexdigest()[:10]
    return raw_output_dir() / f"{qid}_{safe_slug(q)}_{digest}.json"


def extract_queries(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    max_queries = int(cfg.get("max_queries", 50))

    audit_path = cfg.get("paths", {}).get("audit_context_output")
    input_path = cfg.get("paths", {}).get("audit_context_input", "inputs/audit_context.json")

    audit = {}
    if audit_path and resolve_path(audit_path).exists():
        audit = read_json(audit_path)
    elif input_path and resolve_path(input_path).exists():
        audit = read_json(input_path)

    queries = audit.get("queries", []) if isinstance(audit, dict) else []

    if not queries:
        qpath = resolve_path("inputs/query_portfolios/nissan_japan_query_portfolio.json")
        data = read_json(qpath)
        queries = data.get("query_portfolio") or data.get("queries") or []

    cleaned = []
    for i, q in enumerate(queries[:max_queries], 1):
        if not isinstance(q, dict):
            continue
        q = dict(q)
        q["query_id"] = query_id(q, i)
        q.pop("journey_category", None)
        cleaned.append(q)

    return cleaned


def get_mapped_owned_pages(row: Dict[str, Any]) -> List[str]:
    candidates = (
        row.get("mapped_pages")
        or row.get("owned_page_urls")
        or row.get("target_pages")
        or row.get("mapped_owned_pages")
        or []
    )
    if isinstance(candidates, str):
        candidates = [candidates]
    if not isinstance(candidates, list):
        candidates = []

    if row.get("mapped_url"):
        candidates.append(row["mapped_url"])

    out = []
    seen = set()
    for url in candidates:
        if isinstance(url, dict):
            url = url.get("url") or url.get("page_url") or url.get("target_page") or ""
        if isinstance(url, str) and url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def native_text_blocks(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    blocks = raw.get("text_blocks") or []
    if not isinstance(blocks, list):
        return []

    out = []
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue

        item = {
            "block_index": i,
            "type": block.get("type", ""),
            "snippet": compact_whitespace(block.get("snippet", "")),
            "snippet_highlighted_words": block.get("snippet_highlighted_words", []),
            "snippet_inline_code": block.get("snippet_inline_code", []),
            "snippet_links": block.get("snippet_links", []),
            "reference_indexes": block.get("reference_indexes", []),
        }

        if block.get("type") == "table":
            item["table"] = block.get("table", [])
            item["formatted"] = block.get("formatted", [])
            item["detailed"] = block.get("detailed", [])

        if block.get("type") == "list":
            item["list"] = block.get("list", [])

        if block.get("type") == "comparison":
            item["comparison"] = block.get("comparison", [])

        if block.get("type") == "code_block":
            item["language"] = block.get("language", "")
            item["code"] = block.get("code", "")

        out.append(item)

    return out


def collect_reference_indexes_from_nested(value: Any) -> List[int]:
    found = []

    if isinstance(value, dict):
        refs = value.get("reference_indexes")
        if isinstance(refs, list):
            for r in refs:
                try:
                    found.append(int(r))
                except Exception:
                    pass
        for v in value.values():
            found.extend(collect_reference_indexes_from_nested(v))

    elif isinstance(value, list):
        for item in value:
            found.extend(collect_reference_indexes_from_nested(item))

    return found


def native_references(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs = raw.get("references") or []
    if not isinstance(refs, list):
        return []

    out = []
    seen = set()

    for i, ref in enumerate(refs):
        if not isinstance(ref, dict):
            continue

        url = ref.get("link") or ref.get("url") or ""
        if not isinstance(url, str) or not url.startswith("http"):
            continue

        key = url.split("#")[0]
        if key in seen:
            continue
        seen.add(key)

        domain = domain_of(url)
        title = ref.get("title", "") or domain
        source = ref.get("source", "") or domain

        try:
            ref_index = int(ref.get("index", i))
        except Exception:
            ref_index = i

        out.append(
            {
                "reference_index": ref_index,
                "citation_position": i + 1,
                "title": title,
                "url": url,
                "link": url,
                "domain": domain,
                "source": source,
                "snippet": compact_whitespace(ref.get("snippet", "")),
                "thumbnail": ref.get("thumbnail", ""),
                "source_icon": ref.get("source_icon", ""),
                "source_type": classify_source_type(url, f"{title} {source}"),
            }
        )

    return out


def quick_results(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = raw.get("quick_results") or []
    out = []

    if not isinstance(rows, list):
        return out

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        url = row.get("link") or ""
        out.append(
            {
                "position": i + 1,
                "title": row.get("title", ""),
                "url": url,
                "link": url,
                "domain": domain_of(url),
                "snippet": compact_whitespace(row.get("snippet", "")),
                "source": row.get("source", ""),
                "displayed_link": row.get("displayed_link", ""),
                "favicon": row.get("favicon", ""),
                "source_type": classify_source_type(url, row.get("title", "")),
            }
        )

    return out


def inline_videos(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = raw.get("inline_videos") or []
    out = []

    if not isinstance(rows, list):
        return out

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        url = row.get("link") or ""
        out.append(
            {
                "position": i + 1,
                "title": row.get("title", ""),
                "url": url,
                "link": url,
                "domain": domain_of(url),
                "thumbnail": row.get("thumbnail", ""),
                "duration": row.get("duration", ""),
                "channel": row.get("channel", ""),
                "platform": row.get("platform", ""),
                "source_type": "forum_social_video",
            }
        )

    return out


def related_questions(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = raw.get("related_questions") or []
    out = []

    if not isinstance(rows, list):
        return out

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "position": i + 1,
                "question": row.get("question", ""),
                "serpapi_link": row.get("serpapi_link", ""),
            }
        )

    return out


def shopping_results(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = raw.get("shopping_results") or []
    if not isinstance(rows, list):
        return []
    return rows


def local_results(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = raw.get("local_results") or []
    if not isinstance(rows, list):
        return []
    return rows


def answer_patterns(blocks: List[Dict[str, Any]], raw: Dict[str, Any]) -> Dict[str, Any]:
    types = [b.get("type") for b in blocks]
    markdown = raw.get("reconstructed_markdown") or ""
    lower = markdown.lower()

    return {
        "has_answer_first_summary": bool(blocks and blocks[0].get("type") == "paragraph"),
        "has_heading": "heading" in types,
        "has_table": "table" in types,
        "has_list": "list" in types,
        "has_expandable": "expandable" in types,
        "has_comparison": "comparison" in types or any(w in lower for w in [" vs ", "versus", "compare", "comparison"]),
        "has_code_block": "code_block" in types,
        "has_inline_images": bool(raw.get("inline_images")),
        "has_quick_results": bool(raw.get("quick_results")),
        "has_related_questions": bool(raw.get("related_questions")),
        "has_inline_videos": bool(raw.get("inline_videos")),
        "has_local_results": bool(raw.get("local_results")),
        "has_shopping_results": bool(raw.get("shopping_results")),
        "has_numeric_claims": bool(re.search(r"(\d+[%¥$]|\d+\s?%|¥\s?\d|\$\s?\d|\d{4})", markdown)),
        "has_cost_or_value_estimates": any(w in lower for w in ["cost", "price", "tax", "insurance", "value", "resale", "depreciation", "¥", "$"]),
        "has_caveats_or_variables": any(w in lower for w in ["depends", "assuming", "varies", "if you", "depending", "estimate", "caveat"]),
        "block_type_counts": {t: types.count(t) for t in sorted(set(types)) if t},
    }


def reference_influence(blocks: List[Dict[str, Any]], refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ref_by_index = {int(r.get("reference_index", i)): r for i, r in enumerate(refs)}

    influence: Dict[int, Dict[str, Any]] = {}

    weights = {
        "paragraph": 1,
        "heading": 1,
        "list": 2,
        "expandable": 2,
        "comparison": 3,
        "table": 4,
        "code_block": 2,
    }

    for block in blocks:
        btype = block.get("type", "")
        weight = weights.get(btype, 1)

        direct_refs = []
        for r in block.get("reference_indexes", []) or []:
            try:
                direct_refs.append(int(r))
            except Exception:
                pass

        nested_refs = collect_reference_indexes_from_nested(block.get("list", []))
        all_refs = sorted(set(direct_refs + nested_refs))

        for idx in all_refs:
            if idx not in ref_by_index:
                continue

            if idx not in influence:
                influence[idx] = {
                    "reference_index": idx,
                    "answer_support_count": 0,
                    "answer_support_weight": 0,
                    "supported_block_types": set(),
                    "supported_block_indexes": [],
                }

            influence[idx]["answer_support_count"] += 1
            influence[idx]["answer_support_weight"] += weight
            influence[idx]["supported_block_types"].add(btype)
            influence[idx]["supported_block_indexes"].append(block.get("block_index"))

    enriched = []

    for i, ref in enumerate(refs):
        idx = int(ref.get("reference_index", i))
        inf = influence.get(
            idx,
            {
                "reference_index": idx,
                "answer_support_count": 0,
                "answer_support_weight": 0,
                "supported_block_types": set(),
                "supported_block_indexes": [],
            },
        )

        row = dict(ref)
        row["answer_support_count"] = int(inf["answer_support_count"])
        row["answer_support_weight"] = int(inf["answer_support_weight"])
        row["supported_block_types"] = sorted(list(inf["supported_block_types"]))
        row["supported_block_indexes"] = inf["supported_block_indexes"]
        row["is_answer_supporting_source"] = row["answer_support_count"] > 0
        enriched.append(row)

    return sorted(
        enriched,
        key=lambda x: (
            -int(x.get("answer_support_weight", 0)),
            int(x.get("citation_position", 999)),
        ),
    )


def detect_mentions(text: str, refs: List[Dict[str, Any]], brand: str = "Nissan") -> Dict[str, Any]:
    combined = f"{text} " + " ".join(
        f"{r.get('title','')} {r.get('source','')} {r.get('domain','')} {r.get('snippet','')}"
        for r in refs
    )
    lower = combined.lower()

    competitors = [
        "toyota",
        "honda",
        "mazda",
        "subaru",
        "mitsubishi",
        "suzuki",
        "daihatsu",
        "lexus",
        "kia",
        "hyundai",
        "byd",
        "tesla",
        "volkswagen",
        "bmw",
        "mercedes",
        "audi",
    ]

    found = sorted({c for c in competitors if re.search(rf"\b{re.escape(c)}\b", lower)})

    brand_lower = brand.lower()
    brand_mentions = [brand] if brand_lower and brand_lower in lower else []

    negative_context = any(
        phrase in lower
        for phrase in [
            "low resale",
            "depreciates",
            "battery degradation",
            "trap",
            "replacement cost",
            "worst",
            "lower value",
        ]
    )

    positive_context = any(
        phrase in lower
        for phrase in [
            "recommended",
            "best",
            "high resale",
            "lower lifetime cost",
            "cost effective",
            "reliable",
        ]
    )

    if brand_mentions and negative_context and not positive_context:
        brand_framing = "mixed_or_weak"
    elif brand_mentions and positive_context:
        brand_framing = "positive_or_recommended"
    elif brand_mentions:
        brand_framing = "neutral"
    else:
        brand_framing = "not_mentioned"

    return {
        "brand_mentions": brand_mentions,
        "competitor_mentions": found,
        "brand_framing": brand_framing,
    }


def source_landscape(refs: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in refs:
        st = r.get("source_type") or "low_quality_unknown"
        counts[st] = counts.get(st, 0) + 1
    return counts


def build_compact_row(raw: Dict[str, Any], q: Dict[str, Any], cfg: Dict[str, Any], idx: int, raw_file: str) -> Dict[str, Any]:
    blocks = native_text_blocks(raw)
    refs = native_references(raw)
    refs_by_influence = reference_influence(blocks, refs)

    answer_supporting = [r for r in refs_by_influence if r.get("is_answer_supporting_source")]
    if not answer_supporting:
        answer_supporting = refs_by_influence[:]

    max_external = int(cfg.get("max_external_pages_per_query", 3))
    top_cited_sources = answer_supporting[:max_external]

    markdown = raw.get("reconstructed_markdown") or " ".join(
        b.get("snippet", "") for b in blocks if b.get("snippet")
    )
    markdown = compact_whitespace(markdown)

    brand = cfg.get("brand", "Nissan")
    mentions = detect_mentions(markdown, refs, brand=brand)

    return {
        "query_id": query_id(q, idx),
        "query": q.get("query", ""),
        "query_type": q.get("query_type", ""),
        "brand_topic_category": q.get("brand_topic_category", ""),
        "journey_stage": q.get("journey_stage", ""),
        "intent_type": q.get("intent_type", ""),
        "answer_type": q.get("answer_type", ""),
        "commercial_value": q.get("commercial_value", ""),
        "priority": q.get("priority", ""),
        "mapped_owned_pages": get_mapped_owned_pages(q),
        "mapped_owned_page": (get_mapped_owned_pages(q) or [""])[0],
        "raw_serpapi_file": raw_file,
        "search_metadata": raw.get("search_metadata") or {},
        "search_parameters": raw.get("search_parameters") or {},
        "inline_images": raw.get("inline_images") or [],
        "quick_results": quick_results(raw),
        "answer_blocks": blocks,
        "text_blocks": blocks,
        "answer_patterns": answer_patterns(blocks, raw),
        "all_references": refs_by_influence,
        "answer_supporting_references": answer_supporting,
        "top_cited_sources": top_cited_sources,
        "references": top_cited_sources,
        "shopping_results": shopping_results(raw),
        "local_results": local_results(raw),
        "inline_videos": inline_videos(raw),
        "related_questions": related_questions(raw),
        "subsequent_request_token": raw.get("subsequent_request_token", ""),
        "error": raw.get("error", ""),
        "reconstructed_markdown": markdown,
        "brand_mentions": mentions["brand_mentions"],
        "competitor_mentions": mentions["competitor_mentions"],
        "brand_framing": mentions["brand_framing"],
        "source_landscape": source_landscape(refs_by_influence),
        "raw_top_level_keys": list(raw.keys())[:50],
    }


def consolidated_output(rows: List[Dict[str, Any]], cfg: Dict[str, Any], failed: List[Dict[str, Any]]) -> Dict[str, Any]:
    owned_domains = cfg.get("owned_domains", [])
    brand = cfg.get("brand", "Nissan")

    per_query = []

    for row in rows:
        refs = row.get("all_references") or []
        top_refs = row.get("top_cited_sources") or []
        mapped_pages = row.get("mapped_owned_pages") or []

        target_page_cited = any((r.get("url") or r.get("link")) in mapped_pages for r in refs)
        target_domain_cited = any(is_owned_url((r.get("url") or r.get("link") or ""), owned_domains) for r in refs)

        per_query.append(
            {
                "query_id": row.get("query_id", ""),
                "query": row.get("query", ""),
                "query_type": row.get("query_type", ""),
                "brand_topic_category": row.get("brand_topic_category", ""),
                "journey_stage": row.get("journey_stage", ""),
                "status": "available" if row.get("reconstructed_markdown") or refs else "not_available",
                "market": cfg.get("market", ""),
                "gl": cfg.get("localisation", {}).get("gl", "jp"),
                "hl": cfg.get("localisation", {}).get("hl", "en"),
                "answer_summary": compact_whitespace(row.get("reconstructed_markdown", ""))[:1400],
                "answer_patterns": row.get("answer_patterns", {}),
                "target_page": mapped_pages[0] if mapped_pages else "",
                "target_pages": mapped_pages,
                "target_page_cited": target_page_cited,
                "target_domain_cited": target_domain_cited,
                "brand_present": bool(row.get("brand_mentions")),
                "brand_prominence": "medium" if row.get("brand_mentions") else "absent",
                "brand_framing": row.get("brand_framing", "not_mentioned"),
                "top_competitors": row.get("competitor_mentions", []),
                "brand_mentions": row.get("brand_mentions", []),
                "top_cited_sources": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url") or r.get("link") or "",
                        "source_name": r.get("source") or domain_of(r.get("url") or r.get("link") or ""),
                        "source_domain": domain_of(r.get("url") or r.get("link") or ""),
                        "source_type": r.get("source_type") or classify_source_type(r.get("url") or r.get("link") or "", r.get("title", "")),
                        "snippet": r.get("snippet", "")[:700],
                        "citation_count": r.get("answer_support_count", 0),
                        "first_cited_position": r.get("citation_position"),
                        "answer_support_weight": r.get("answer_support_weight", 0),
                        "supported_block_types": r.get("supported_block_types", []),
                    }
                    for r in top_refs
                    if r.get("url") or r.get("link")
                ],
                "all_cited_sources": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url") or r.get("link") or "",
                        "source_name": r.get("source") or domain_of(r.get("url") or r.get("link") or ""),
                        "source_domain": domain_of(r.get("url") or r.get("link") or ""),
                        "source_type": r.get("source_type") or classify_source_type(r.get("url") or r.get("link") or "", r.get("title", "")),
                        "snippet": r.get("snippet", "")[:700],
                        "first_cited_position": r.get("citation_position"),
                        "answer_support_count": r.get("answer_support_count", 0),
                        "answer_support_weight": r.get("answer_support_weight", 0),
                        "supported_block_types": r.get("supported_block_types", []),
                        "is_answer_supporting_source": r.get("is_answer_supporting_source", False),
                    }
                    for r in refs
                    if r.get("url") or r.get("link")
                ],
                "quick_results": row.get("quick_results", []),
                "inline_videos": row.get("inline_videos", []),
                "related_questions": row.get("related_questions", []),
                "source_landscape": row.get("source_landscape", {}),
                "sentiment": row.get("brand_framing", "neutral"),
                "confidence": "high" if refs and row.get("reconstructed_markdown") else ("medium" if refs else "low"),
                "raw_serpapi_file": row.get("raw_serpapi_file", ""),
                "evidence_notes": [],
            }
        )

    return {
        "provider": "Google AI Mode",
        "status": "success" if per_query else "failed",
        "failure_reason": "",
        "localization": {
            "market": cfg.get("market", ""),
            "gl": cfg.get("localisation", {}).get("gl", "jp"),
            "hl": cfg.get("localisation", {}).get("hl", "en"),
            "localization_status": "matched",
        },
        "per_query": per_query,
        "aggregate": {
            "queries_checked": len(per_query),
            "available_queries": sum(1 for x in per_query if x["status"] == "available"),
            "failed_queries": len(failed),
            "total_top_cited_sources": sum(len(x["top_cited_sources"]) for x in per_query),
            "total_all_cited_sources": sum(len(x["all_cited_sources"]) for x in per_query),
            "total_answer_supporting_sources": sum(
                sum(1 for s in x["all_cited_sources"] if s.get("is_answer_supporting_source"))
                for x in per_query
            ),
            "queries_with_minimum_3_sources": sum(1 for x in per_query if len(x["top_cited_sources"]) >= 3),
            "target_domain_cited_count": sum(1 for x in per_query if x["target_domain_cited"]),
            "target_page_cited_count": sum(1 for x in per_query if x["target_page_cited"]),
            "queries_with_competitor_mentions": sum(1 for x in per_query if x.get("top_competitors")),
            "queries_with_related_questions": sum(1 for x in per_query if x.get("related_questions")),
            "summary": "Google AI Mode evidence collected with native SerpAPI parser and raw payload preservation.",
        },
    }


def main() -> None:
    load_dotenv_minimal()

    cfg = get_config()
    cfg["max_queries"] = int(cfg.get("max_queries", 50))

    out_path = cfg["paths"]["google_ai_mode_output"]
    compact_path = cfg["paths"]["google_ai_mode_compact"]

    if cfg.get("reuse_existing_outputs", True) and not cfg.get("force_refetch_serpapi") and resolve_path(out_path).exists():
        print(f"Reusing existing {out_path}; set force_refetch_serpapi=true for live refresh.")
        return

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is missing. Add SERPAPI_API_KEY=... to .env")

    queries = extract_queries(cfg)
    if not queries:
        raise RuntimeError("No queries found. Expected inputs/query_portfolios/nissan_japan_query_portfolio.json or inputs/audit_context.json")

    rows = []
    failed = []
    raw_manifest = []

    for idx, q in enumerate(queries, start=1):
        qid = query_id(q, idx)
        query_text = q.get("query", "")
        raw_file = raw_output_path(q, idx)

        params = {
            "api_key": api_key,
            "engine": "google_ai_mode",
            "q": query_text,
            "gl": cfg.get("localisation", {}).get("gl", "jp"),
            "hl": cfg.get("localisation", {}).get("hl", "en"),
            "device": "desktop",
        }

        try:
            print(f"[{idx}/{len(queries)}] Google AI Mode: {query_text[:100]}")
            response = requests.get("https://serpapi.com/search.json", params=params, timeout=180)
            response.raise_for_status()
            raw = response.json()

            raw_payload = {
                "query_id": qid,
                "query": query_text,
                "query_type": q.get("query_type", ""),
                "brand_topic_category": q.get("brand_topic_category", ""),
                "journey_stage": q.get("journey_stage", ""),
                "request_params_without_api_key": {k: v for k, v in params.items() if k != "api_key"},
                "serpapi_response": raw,
            }
            raw_file.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            row = build_compact_row(raw, q, cfg, idx, str(raw_file))
            rows.append(row)

            raw_manifest.append(
                {
                    "query_id": qid,
                    "query": query_text,
                    "brand_topic_category": q.get("brand_topic_category", ""),
                    "status": "success",
                    "raw_file": str(raw_file),
                    "raw_chars": len(json.dumps(raw, ensure_ascii=False)),
                    "raw_top_level_keys": list(raw.keys())[:50],
                    "text_block_count": len(raw.get("text_blocks") or []),
                    "reference_count": len(raw.get("references") or []),
                    "answer_supporting_reference_count": len(row.get("answer_supporting_references") or []),
                    "related_question_count": len(raw.get("related_questions") or []),
                    "inline_video_count": len(raw.get("inline_videos") or []),
                }
            )

            time.sleep(float(cfg.get("serpapi_delay_seconds", 0.4)))

        except Exception as e:
            err = {
                "query_id": qid,
                "query": query_text,
                "brand_topic_category": q.get("brand_topic_category", ""),
                "status": "failed",
                "error": str(e),
                "raw_file": str(raw_file),
            }
            failed.append(err)
            raw_manifest.append(err)
            rows.append(
                {
                    "query_id": qid,
                    "query": query_text,
                    "query_type": q.get("query_type", ""),
                    "brand_topic_category": q.get("brand_topic_category", ""),
                    "journey_stage": q.get("journey_stage", ""),
                    "mapped_owned_pages": get_mapped_owned_pages(q),
                    "mapped_owned_page": (get_mapped_owned_pages(q) or [""])[0],
                    "answer_blocks": [],
                    "text_blocks": [],
                    "all_references": [],
                    "answer_supporting_references": [],
                    "top_cited_sources": [],
                    "references": [],
                    "reconstructed_markdown": "",
                    "error": str(e),
                }
            )

    write_json(compact_path, {"rows": rows, "failed": failed, "raw_manifest": raw_manifest})
    write_json(out_path, consolidated_output(rows, cfg, failed))
    write_json("outputs/google_ai_mode/raw_manifest.json", {"raw_manifest": raw_manifest})

    print(f"Wrote {compact_path}")
    print(f"Wrote {out_path}")
    print("Wrote outputs/google_ai_mode/raw_manifest.json")


if __name__ == "__main__":
    main()
