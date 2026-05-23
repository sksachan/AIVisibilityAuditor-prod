"""Advanced CMS Asset Generator - Pass 2 of Two-Pass Architecture.

Generates deployable CMS HTML, JSON-LD extensions, and direct answers
using ONLY facts from the fact_matrix. No invented claims.

Rule: No fact matrix source = no claim.
"""
from __future__ import annotations

import json
import re
from typing import Any

from advanced_geo_contracts import (
    make_advanced_geo_asset,
    make_fact_entry,
    validate_fact_snippet_contains_claim,
    ADVANCED_GEO_ASSET_SCHEMA_VERSION,
)
from fact_matrix import extract_fact_matrix_for_owned_url


def _safe_placeholder(label: str) -> str:
    return f"[{label}]"


def _estimate_impact_score(
    cms_rec: dict[str, Any],
    fact_matrix: dict[str, Any],
) -> float:
    score = 3.0
    query_count = cms_rec.get("query_coverage_count") or len(cms_rec.get("linked_queries") or [])
    if query_count >= 5:
        score += 2.0
    elif query_count >= 3:
        score += 1.0
    geo_score = cms_rec.get("current_geo_score_120") or 0
    if geo_score < 50:
        score += 2.0
    elif geo_score < 80:
        score += 1.0
    fact_count = fact_matrix.get("facts_count", 0)
    if fact_count >= 10:
        score += 1.5
    elif fact_count >= 5:
        score += 0.5
    if fact_matrix.get("has_json_ld"):
        score += 0.5
    return min(10.0, round(score, 1))


def _build_direct_answer(
    cms_rec: dict[str, Any],
    fact_matrix: dict[str, Any],
    brand: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    facts_used: list[dict[str, Any]] = []
    validated = fact_matrix.get("validated_facts") or []
    title = fact_matrix.get("title") or cms_rec.get("page_title") or ""
    queries = cms_rec.get("linked_queries") or []
    primary_query = queries[0].get("query", "") if queries else ""
    key_facts = [f for f in validated if f.get("value") and f.get("source") in ("existing_json_ld", "owned_page")]
    top_facts = key_facts[:3]
    parts = []
    if brand and title:
        parts.append(f"{brand}'s {title} page")
    elif title:
        parts.append(title)
    if primary_query:
        parts.append(f"addresses: {primary_query}.")
    for fact in top_facts:
        fact_str = f"{fact.get('fact', '')}"
        if fact.get('value'):
            fact_str += f": {fact['value']}"
        if fact.get('unit'):
            fact_str += f" {fact['unit']}"
        parts.append(fact_str)
        facts_used.append(fact)
    if not top_facts:
        parts.append(_safe_placeholder("verified product specifications pending"))
    answer = ". ".join(parts)
    words = answer.split()
    if len(words) > 40:
        answer = " ".join(words[:40])
    return answer, facts_used


def _build_html_component(
    cms_rec: dict[str, Any],
    fact_matrix: dict[str, Any],
    direct_answer: str,
    facts_used: list[dict[str, Any]],
    brand: str = "",
) -> str:
    title = cms_rec.get("page_title") or fact_matrix.get("title") or "Page"
    module_type = cms_rec.get("module_type") or "answer_first_summary_plus_faq"
    heading = cms_rec.get("title") or f"Key Information: {title}"
    lines = []
    lines.append(f'<section class="geo-lead-answer" data-module-type="{module_type}">')
    lines.append(f"  <h2>{heading}</h2>")
    lines.append(f"  <p class=\"direct-answer\">{direct_answer}</p>")
    spec_facts = [f for f in facts_used if f.get("value")]
    if spec_facts:
        lines.append("  <dl class=\"verified-specs\">")
        for fact in spec_facts[:6]:
            label = str(fact.get("fact", "")).replace("_", " ").title()
            val = str(fact.get("value", ""))
            unit = str(fact.get("unit", ""))
            display = f"{val} {unit}".strip() if unit else val
            lines.append(f"    <dt>{label}</dt>")
            lines.append(f"    <dd>{display}</dd>")
        lines.append("  </dl>")
    gaps = cms_rec.get("geo_gaps_addressed") or []
    if gaps:
        lines.append("  <div class=\"improvement-areas\">")
        lines.append("    <h3>Areas for Improvement</h3>")
        lines.append("    <ul>")
        for gap in gaps[:4]:
            lines.append(f"      <li>{gap.replace('_', ' ').title()}</li>")
        lines.append("    </ul>")
        lines.append("  </div>")
    lines.append("</section>")
    return "\n".join(lines)


def _build_json_ld_extension(
    cms_rec: dict[str, Any],
    fact_matrix: dict[str, Any],
    facts_used: list[dict[str, Any]],
) -> tuple[str, str, str | None, list[str]]:
    url = fact_matrix.get("url") or cms_rec.get("target_url") or ""
    schema_types = fact_matrix.get("schema_types") or []
    has_existing = fact_matrix.get("json_ld_present", False)
    merge_notes: list[str] = []
    strategy = "standalone_id_extension"
    target_anchor_id = None
    if has_existing and schema_types:
        existing_json_ld_facts = [
            f for f in fact_matrix.get("validated_facts", [])
            if f.get("source") == "existing_json_ld"
        ]
        if len(existing_json_ld_facts) >= 3:
            strategy = "full_page_merge_patch"
            merge_notes.append("Existing JSON-LD has sufficient structured data for merge.")
            if url:
                target_anchor_id = url
        else:
            merge_notes.append("Using standalone extension; existing JSON-LD is minimal.")
    else:
        merge_notes.append("No existing JSON-LD found; creating standalone extension block.")
    ld_obj: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "WebPage",
    }
    if url:
        ld_obj["@id"] = url
    if fact_matrix.get("title"):
        ld_obj["name"] = fact_matrix["title"]
    spec_facts = [f for f in facts_used if f.get("value") and f.get("source") in ("existing_json_ld", "owned_page")]
    if spec_facts:
        additional = []
        for fact in spec_facts[:8]:
            prop: dict[str, Any] = {
                "@type": "PropertyValue",
                "name": str(fact.get("fact", "")).replace("_", " "),
                "value": str(fact.get("value", "")),
            }
            if fact.get("unit"):
                prop["unitText"] = fact["unit"]
            additional.append(prop)
        ld_obj["additionalProperty"] = additional
    json_ld_script = json.dumps(ld_obj, ensure_ascii=False, indent=2)
    return json_ld_script, strategy, target_anchor_id, merge_notes


def build_advanced_geo_asset(
    cms_rec: dict[str, Any],
    fact_matrix: dict[str, Any],
    patterns: list[dict[str, Any]] | None = None,
    brand: str = "",
    language: str = "en",
) -> dict[str, Any]:
    impact = _estimate_impact_score(cms_rec, fact_matrix)
    direct_answer, facts_used = _build_direct_answer(cms_rec, fact_matrix, brand)
    html = _build_html_component(cms_rec, fact_matrix, direct_answer, facts_used, brand)
    json_ld_script, strategy, anchor_id, merge_notes = _build_json_ld_extension(
        cms_rec, fact_matrix, facts_used,
    )
    validation_flags: list[str] = list(fact_matrix.get("validation_flags") or [])
    if not facts_used:
        validation_flags.append("No verified facts available; all claims use placeholders.")
    if not fact_matrix.get("has_crawl_text"):
        validation_flags.append("Limited crawl text; fact extraction may be incomplete.")
    legal_review = bool(
        any("price" in str(f.get("fact", "")).lower() for f in facts_used)
        or any("warranty" in str(f.get("fact", "")).lower() for f in facts_used)
        or any("legal" in flag.lower() for flag in validation_flags)
    )
    return make_advanced_geo_asset(
        expected_impact_score_10=impact,
        direct_answer_40_words=direct_answer,
        html_component=html,
        json_ld_strategy=strategy,
        target_anchor_id=anchor_id,
        json_ld_script=json_ld_script,
        json_ld_merge_notes=merge_notes,
        localized_copy_language=language,
        facts_used=facts_used,
        validation_flags=validation_flags,
        legal_review_required=legal_review,
    )


def attach_advanced_geo_assets_to_bundle(
    bundle: dict[str, Any],
    owned_pages: list[dict[str, Any]] | None = None,
    brand: str = "",
    language: str = "en",
) -> dict[str, Any]:
    pages = owned_pages or []
    if not pages:
        for key in ("owned_pages_full", "owned_url_readiness", "owned_pages"):
            candidate = bundle.get(key)
            if isinstance(candidate, dict):
                candidate = candidate.get("pages") or []
            if isinstance(candidate, list) and candidate:
                pages = candidate
                break
    from fact_matrix import build_fact_matrices_for_bundle
    matrices = build_fact_matrices_for_bundle(pages)
    cms_recs = (
        bundle.get("page_level_cms_recommendations")
        or bundle.get("cms_recommendations")
        or []
    )
    for rec in cms_recs:
        if not isinstance(rec, dict):
            continue
        if rec.get("advanced_geo_asset"):
            continue
        target_url = str(
            rec.get("target_url") or rec.get("targetUrl") or rec.get("url") or ""
        ).strip().rstrip("/").lower()
        matrix = matrices.get(target_url)
        if not matrix:
            for key in matrices:
                if target_url and key.endswith(target_url.split("/")[-1]):
                    matrix = matrices[key]
                    break
        if not matrix:
            matrix = {
                "url": target_url,
                "title": rec.get("page_title", ""),
                "facts_count": 0,
                "validated_facts": [],
                "validation_flags": ["No crawl data available for this URL"],
                "has_json_ld": False,
                "has_crawl_text": False,
                "crawl_text_length": 0,
                "schema_types": [],
                "json_ld_present": False,
                "json_ld_facts_count": 0,
                "visible_facts_count": 0,
                "metadata_facts_count": 0,
            }
        asset = build_advanced_geo_asset(
            cms_rec=rec,
            fact_matrix=matrix,
            brand=brand or bundle.get("brand", ""),
            language=language,
        )
        rec["advanced_geo_asset"] = asset
    return bundle
