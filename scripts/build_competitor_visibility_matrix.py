#!/usr/bin/env python3
"""Non-Branded Competitor Visibility Matrix Builder.

Derived analytics layer that generates an executive-ready competitor matrix
from existing audit evidence. No fresh SerpAPI, crawl, or LLM calls.

This module answers:
"Within the audited brand's non-branded AI search demand universe, which
competitors are visible, how visible are they, and which source types/domains
are driving that visibility?"

Usage:
    from build_competitor_visibility_matrix import build_competitor_visibility_matrix
    matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Configurable competitor dictionary
# ---------------------------------------------------------------------------

def default_competitor_dictionary() -> dict[str, dict[str, Any]]:
    """Return the default Japan automotive market competitor dictionary.

    Each competitor has:
      - aliases: list of brand names, model names, and Japanese equivalents
      - domains: list of official OEM / dealer domains
      - ambiguous_aliases: aliases that should only match with domain evidence
    """
    return {
        "Toyota": {
            "aliases": ["toyota", "\u30c8\u30e8\u30bf", "prius", "aqua", "yaris", "corolla", "crown", "alphard", "vellfire", "harrier", "rav4"],
            "domains": ["toyota.jp", "toyota.co.jp", "toyota.com", "crowntoyota.com"],
            "ambiguous_aliases": ["crown"],  # crown could be non-automotive
        },
        "Honda": {
            "aliases": ["honda", "\u30db\u30f3\u30c0", "vezel", "fit", "freed", "n-box", "stepwgn", "civic", "accord"],
            "domains": ["honda.co.jp", "honda.com"],
            "ambiguous_aliases": ["fit", "freed", "civic", "accord"],
        },
        "Mitsubishi": {
            "aliases": ["mitsubishi", "\u4e09\u83f1", "outlander", "delica", "ek x", "ek\u30af\u30ed\u30b9"],
            "domains": ["mitsubishi-motors.co.jp", "mitsubishi-motors.com"],
            "ambiguous_aliases": [],
        },
        "Mazda": {
            "aliases": ["mazda", "\u30de\u30c4\u30c0", "cx-3", "cx-5", "cx-30", "cx-60", "mx-30", "mazda2", "mazda3"],
            "domains": ["mazda.co.jp", "mazda.com"],
            "ambiguous_aliases": [],
        },
        "Subaru": {
            "aliases": ["subaru", "\u30b9\u30d0\u30eb", "forester", "impreza", "levorg", "crosstrek", "outback"],
            "domains": ["subaru.jp", "subaru.co.jp"],
            "ambiguous_aliases": ["outback"],
        },
        "Suzuki": {
            "aliases": ["suzuki", "\u30b9\u30ba\u30ad", "swift", "solio", "wagon r", "hustler", "jimny", "spacia"],
            "domains": ["suzuki.co.jp"],
            "ambiguous_aliases": ["swift"],
        },
        "Daihatsu": {
            "aliases": ["daihatsu", "\u30c0\u30a4\u30cf\u30c4", "tanto", "move", "rocky", "taft"],
            "domains": ["daihatsu.co.jp"],
            "ambiguous_aliases": ["move", "rocky"],
        },
        "Lexus": {
            "aliases": ["lexus", "\u30ec\u30af\u30b5\u30b9", "nx", "rx", "ux", "rz"],
            "domains": ["lexus.jp", "lexus.com"],
            "ambiguous_aliases": ["nx", "rx", "ux", "rz"],
        },
        "Tesla": {
            "aliases": ["tesla", "\u30c6\u30b9\u30e9", "model 3", "model y"],
            "domains": ["tesla.com"],
            "ambiguous_aliases": [],
        },
        "BYD": {
            "aliases": ["byd", "\u30d3\u30fc\u30ef\u30a4\u30c7\u30a3\u30fc", "atto 3", "dolphin", "seal"],
            "domains": ["byd.com", "bydauto.co.jp"],
            "ambiguous_aliases": ["dolphin", "seal"],
        },
    }


def default_brand_exclusion_terms(brand: str) -> list[str]:
    """Return configurable brand-specific terms to identify branded queries.

    These terms are used to filter OUT branded queries so only non-branded
    category queries are analysed.
    """
    brand_lower = brand.lower()
    known: dict[str, list[str]] = {
        "nissan": ["nissan", "leaf", "sakura", "ariya", "x-trail", "serena",
                   "note", "kicks", "aura", "e-power", "\u65e5\u7523"],
        "toyota": ["toyota", "\u30c8\u30e8\u30bf", "prius", "aqua", "yaris", "corolla",
                   "crown", "alphard", "vellfire", "harrier", "rav4"],
        "honda": ["honda", "\u30db\u30f3\u30c0", "vezel", "fit", "freed", "n-box",
                  "stepwgn", "civic", "accord"],
    }
    return known.get(brand_lower, [brand_lower])


# ---------------------------------------------------------------------------
# Source type classification
# ---------------------------------------------------------------------------

SOURCE_TYPE_CATEGORIES = [
    "competitor_owned_domain",
    "dealer_or_retailer",
    "publisher_review",
    "forum_social_video",
    "authority_body",
    "partner_infrastructure",
    "aggregator_marketplace",
    "other_external",
]

_FORUM_SOCIAL_DOMAINS = {"reddit", "youtube", "facebook", "instagram", "x.com",
                         "twitter", "tiktok", "quora", "kakaku", "minkara"}
_AUTHORITY_DOMAINS = {"go.jp", "mlit", "meti", "nasva", "enecho", "jaf"}
_PARTNER_DOMAINS = {"tepco", "charging", "charge", "evdays", "enechange"}
_AGGREGATOR_DOMAINS = {"price", "carmo", "rakuten", "tc-v", "goo-net", "carsensor"}
_PUBLISHER_DOMAINS = {"nikkei", "asahi", "recharged", "autonews", "carwow",
                      "parkers", "greencarreports", "motor1", "autocar",
                      "response.jp", "webcg", "bestcarweb"}
_DEALER_PATTERNS = {"dealer", "dealership", "\u8ca9\u58f2\u5e97"}


def _extract_domain(url: str) -> str:
    """Extract clean domain from URL."""
    try:
        d = urlparse(url or "").netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def classify_source_type(
    url: str,
    competitor_domains: set[str],
    existing_source_type: str = "",
) -> str:
    """Classify a citation URL into one of the standard source type categories."""
    d = _extract_domain(url)
    raw = (existing_source_type or "").lower().replace(" ", "_")

    # Map existing source_type if available
    source_type_map = {
        "competitor_owned": "competitor_owned_domain",
        "competitor_owned_domain": "competitor_owned_domain",
        "dealer_or_retailer": "dealer_or_retailer",
        "publisher_review": "publisher_review",
        "forum_social_video": "forum_social_video",
        "authority_body": "authority_body",
        "partner_infrastructure": "partner_infrastructure",
        "aggregator_marketplace": "aggregator_marketplace",
        "finance_or_insurance": "partner_infrastructure",
    }
    if raw in source_type_map:
        return source_type_map[raw]

    # Domain-based classification
    if any(cd in d for cd in competitor_domains):
        return "competitor_owned_domain"
    if any(x in d for x in _FORUM_SOCIAL_DOMAINS):
        return "forum_social_video"
    if any(x in d for x in _AUTHORITY_DOMAINS):
        return "authority_body"
    if any(x in d for x in _PARTNER_DOMAINS):
        return "partner_infrastructure"
    if any(x in d for x in _AGGREGATOR_DOMAINS):
        return "aggregator_marketplace"
    if any(x in d for x in _PUBLISHER_DOMAINS) or "review" in raw or "publisher" in raw:
        return "publisher_review"
    if any(x in d for x in _DEALER_PATTERNS):
        return "dealer_or_retailer"

    return "other_external"


# ---------------------------------------------------------------------------
# Rank weighting
# ---------------------------------------------------------------------------

RANK_WEIGHTS: dict[int, float] = {
    1: 1.00,
    2: 0.75,
    3: 0.55,
    4: 0.35,
}
DEFAULT_RANK_WEIGHT = 0.20
NO_RANK_DEFAULT_WEIGHT = 0.35


def rank_weight(rank: int | None) -> float:
    """Return the weight for a given citation rank/position."""
    if rank is None or rank < 1:
        return NO_RANK_DEFAULT_WEIGHT
    return RANK_WEIGHTS.get(rank, DEFAULT_RANK_WEIGHT)


# ---------------------------------------------------------------------------
# Framing signal detection
# ---------------------------------------------------------------------------

POSITIVE_FRAMING_TERMS_EN = {
    "recommended", "best", "top", "reliable", "popular", "practical",
    "cheaper", "safer", "better", "efficient", "spacious", "trusted",
    "award", "rating", "review", "leading", "superior", "excellent",
}
POSITIVE_FRAMING_TERMS_JA = {
    "\u304a\u3059\u3059\u3081", "\u4eba\u6c17", "\u5b89\u5168", "\u4fe1\u983c",
    "\u5b9f\u7528\u7684", "\u53e3\u30b3\u30df", "\u8a55\u4fa1",
    "\u30e9\u30f3\u30ad\u30f3\u30b0", "\u6bd4\u8f03",
}
ALL_FRAMING_TERMS = POSITIVE_FRAMING_TERMS_EN | POSITIVE_FRAMING_TERMS_JA
NEUTRAL_FRAMING_SCORE = 3


def compute_framing_score(texts: list[str]) -> float:
    """Compute a 0-10 framing signal score from citation/answer texts."""
    if not texts:
        return NEUTRAL_FRAMING_SCORE
    combined = " ".join(texts).lower()
    hits = sum(1 for term in ALL_FRAMING_TERMS if term in combined)
    if hits == 0:
        return NEUTRAL_FRAMING_SCORE
    return min(10.0, NEUTRAL_FRAMING_SCORE + hits * 1.5)


# ---------------------------------------------------------------------------
# Core extraction and scoring
# ---------------------------------------------------------------------------

def _text(v: Any, limit: int = 0) -> str:
    """Safely extract text from any value."""
    if v is None:
        return ""
    if isinstance(v, str):
        s = v
    elif isinstance(v, (int, float, bool)):
        s = str(v)
    elif isinstance(v, list):
        s = " ".join(_text(x) for x in v)
    elif isinstance(v, dict):
        s = " ".join(_text(x) for x in v.values())
    else:
        s = str(v)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if limit and len(s) > limit else s


def is_non_branded_query(
    query_row: dict,
    brand: str,
    brand_exclusion_terms: list[str],
) -> bool:
    """Determine if a query is non-branded.

    A query is non-branded if:
    - query_type == "non_branded", OR
    - the query text does not contain the audited brand name or model names.
    """
    query_type = _text(query_row.get("query_type")).lower()
    if query_type == "non_branded":
        return True
    if query_type == "branded":
        return False

    # Fallback: check query text against brand exclusion terms
    query_text = _text(
        query_row.get("query") or query_row.get("search_query") or ""
    ).lower()
    if not query_text:
        return False

    for term in brand_exclusion_terms:
        if term.lower() in query_text:
            # Special handling for "e-power" - only exclude if clearly branded
            if term.lower() == "e-power" and brand.lower() not in query_text:
                continue
            return False
    return True


def _extract_citations(query_row: dict) -> list[dict]:
    """Extract all citations from a query workbench row."""
    citations: list[dict] = []
    vis = query_row.get("current_ai_visibility")
    if isinstance(vis, dict):
        for c in vis.get("top_citations") or []:
            if isinstance(c, dict):
                citations.append(c)
    for c in query_row.get("external_top3_benchmark") or []:
        if isinstance(c, dict):
            citations.append(c)
    for c in query_row.get("citations") or []:
        if isinstance(c, dict):
            citations.append(c)
    # Deduplicate by URL
    seen: set[str] = set()
    deduped: list[dict] = []
    for c in citations:
        url = _text(c.get("url") or c.get("source_url") or "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(c)
    return deduped


def _citation_rank(c: dict) -> int | None:
    """Extract citation rank/position."""
    for key in ("rank", "citation_position", "observed_citation_position"):
        val = c.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    return None


def _citation_text_blob(c: dict) -> str:
    """Combine all text fields from a citation for text matching."""
    parts = []
    for key in ("title", "snippet", "citation_text", "text", "summary"):
        val = _text(c.get(key))
        if val:
            parts.append(val)
    return " ".join(parts).lower()


def _detect_competitors_in_citation(
    citation: dict,
    competitor_dict: dict[str, dict[str, Any]],
    all_competitor_domains: dict[str, str],
) -> list[tuple[str, bool]]:
    """Detect which competitors are linked to a citation.

    Returns list of (competitor_name, is_domain_match) tuples.
    Domain matches carry stronger evidence than text alias matches.
    """
    url = _text(citation.get("url") or citation.get("source_url") or "")
    domain = _extract_domain(url)
    text_blob = _citation_text_blob(citation)
    matches: list[tuple[str, bool]] = []

    for comp_name, comp_data in competitor_dict.items():
        is_domain_match = False
        is_text_match = False

        # Check domain match (stronger evidence)
        for comp_domain in comp_data.get("domains", []):
            if comp_domain.lower() in domain:
                is_domain_match = True
                break

        # Check text alias match
        ambiguous = {a.lower() for a in comp_data.get("ambiguous_aliases", [])}
        for alias in comp_data.get("aliases", []):
            alias_lower = alias.lower()
            if alias_lower in ambiguous:
                # Ambiguous aliases only count if domain also matches
                if is_domain_match and alias_lower in text_blob:
                    is_text_match = True
            elif len(alias_lower) >= 3 and alias_lower in text_blob:
                is_text_match = True
                break

        if is_domain_match or is_text_match:
            matches.append((comp_name, is_domain_match))

    return matches


def _allocate_citation_credit(
    competitors_found: list[tuple[str, bool]],
    domain: str,
    all_competitor_domains: dict[str, str],
) -> dict[str, float]:
    """Allocate citation credit across matched competitors.

    Rules:
    - If domain clearly belongs to one competitor, that competitor gets full credit.
    - If publisher article mentions multiple competitors equally, split credit.
    """
    if not competitors_found:
        return {}

    # Check if domain belongs to exactly one competitor
    domain_owner = all_competitor_domains.get(domain)
    if domain_owner:
        # Domain owner gets full credit
        return {domain_owner: 1.0}

    # Check if any competitor has a domain match
    domain_matches = [c for c, is_domain in competitors_found if is_domain]
    if len(domain_matches) == 1:
        return {domain_matches[0]: 1.0}

    # Split credit equally among all matched competitors
    share = 1.0 / len(competitors_found)
    return {comp: share for comp, _ in competitors_found}


def _get_answer_text(query_row: dict) -> str:
    """Extract AI answer text from query row if available."""
    vis = query_row.get("current_ai_visibility")
    if isinstance(vis, dict):
        for key in ("answer_text", "ai_answer", "answer", "response_text"):
            val = _text(vis.get(key))
            if val:
                return val
    for key in ("answer_text", "ai_answer", "answer", "response_text"):
        val = _text(query_row.get(key))
        if val:
            return val
    return ""


def _check_competitor_in_answer(
    answer_text: str,
    competitor_dict: dict[str, dict[str, Any]],
) -> set[str]:
    """Check which competitors are mentioned in the AI answer text."""
    if not answer_text:
        return set()
    answer_lower = answer_text.lower()
    found: set[str] = set()
    for comp_name, comp_data in competitor_dict.items():
        ambiguous = {a.lower() for a in comp_data.get("ambiguous_aliases", [])}
        for alias in comp_data.get("aliases", []):
            alias_lower = alias.lower()
            if alias_lower in ambiguous:
                continue  # Skip ambiguous aliases in answer text
            if len(alias_lower) >= 3 and alias_lower in answer_lower:
                found.add(comp_name)
                break
    return found


def _check_explicit_competitor_fields(query_row: dict) -> set[str]:
    """Check if query row has explicit competitor fields."""
    found: set[str] = set()
    vis = query_row.get("current_ai_visibility")
    if isinstance(vis, dict):
        for comp in vis.get("competitors") or []:
            name = _text(comp)
            if name:
                found.add(name)
    for comp in query_row.get("competitors") or []:
        name = _text(comp)
        if name:
            found.add(name)
    return found


# ---------------------------------------------------------------------------
# Main builder function
# ---------------------------------------------------------------------------

def build_competitor_visibility_matrix(
    bundle: dict,
    brand: str = "",
    market: str = "",
    competitor_dict: dict[str, dict[str, Any]] | None = None,
    brand_exclusion_terms: list[str] | None = None,
) -> dict:
    """Build the Non-Branded Competitor Visibility Matrix.

    Args:
        bundle: The frontend report bundle or query workbench data.
        brand: The audited brand name (e.g. "Nissan").
        market: The audited market (e.g. "Japan").
        competitor_dict: Optional custom competitor dictionary.
        brand_exclusion_terms: Optional custom brand exclusion terms.

    Returns:
        A competitor_visibility_matrix dict matching the schema.
    """
    if not brand:
        brand = _text(bundle.get("brand") or "")
    if not market:
        market = _text(bundle.get("market") or "")

    if competitor_dict is None:
        competitor_dict = default_competitor_dictionary()
    if brand_exclusion_terms is None:
        brand_exclusion_terms = default_brand_exclusion_terms(brand)

    # Remove the audited brand from competitor dictionary
    brand_lower = brand.lower()
    filtered_competitors = {
        k: v for k, v in competitor_dict.items()
        if k.lower() != brand_lower
    }

    # Build domain -> competitor lookup
    all_competitor_domains: dict[str, str] = {}
    all_competitor_domain_set: set[str] = set()
    for comp_name, comp_data in filtered_competitors.items():
        for d in comp_data.get("domains", []):
            d_lower = d.lower()
            all_competitor_domains[d_lower] = comp_name
            all_competitor_domain_set.add(d_lower)

    # Extract query workbench rows (preferred source)
    qwork = bundle.get("query_workbench") or []
    if not isinstance(qwork, list):
        qwork = []

    # Filter to non-branded queries only
    non_branded_queries: list[dict] = []
    for q in qwork:
        if not isinstance(q, dict):
            continue
        if is_non_branded_query(q, brand, brand_exclusion_terms):
            non_branded_queries.append(q)

    query_count_total = len(qwork)
    query_count_non_branded = len(non_branded_queries)

    # Collect all topics from non-branded queries
    all_topics: set[str] = set()
    for q in non_branded_queries:
        topic = _text(
            q.get("topic") or q.get("brand_topic") or
            q.get("brand_topic_category") or q.get("journey_category") or ""
        )
        if topic and topic != "Unclassified":
            all_topics.add(topic)

    # Per-competitor accumulators
    comp_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "queries_present": set(),
        "citation_count": 0.0,
        "weighted_citation_score": 0.0,
        "citation_ranks": [],
        "source_type_weighted": defaultdict(float),
        "topic_presence": Counter(),
        "domain_stats": defaultdict(lambda: {
            "citation_count": 0.0,
            "weighted_citation_score": 0.0,
            "source_type": "",
        }),
        "query_stats": defaultdict(lambda: {
            "citation_count": 0.0,
            "best_citation_rank": 999,
            "source_types": set(),
        }),
        "framing_texts": [],
    })

    total_non_branded_citations = 0

    # Process each non-branded query
    for q in non_branded_queries:
        qid = _text(q.get("query_id") or q.get("id") or "")
        query_text = _text(q.get("query") or q.get("search_query") or "")
        topic = _text(
            q.get("topic") or q.get("brand_topic") or
            q.get("brand_topic_category") or q.get("journey_category") or ""
        )

        citations = _extract_citations(q)
        answer_text = _get_answer_text(q)
        explicit_competitors = _check_explicit_competitor_fields(q)
        answer_competitors = _check_competitor_in_answer(
            answer_text, filtered_competitors
        )

        # Track competitors present in this query (from any evidence source)
        query_competitors: set[str] = set()
        query_competitors.update(explicit_competitors & set(filtered_competitors.keys()))
        query_competitors.update(answer_competitors)

        total_non_branded_citations += len(citations)

        # Process each citation
        for c in citations:
            url = _text(c.get("url") or c.get("source_url") or "")
            domain = _extract_domain(url)
            cit_rank = _citation_rank(c)
            weight = rank_weight(cit_rank)
            existing_st = _text(c.get("source_type") or c.get("source_category") or "")

            # Detect competitors in this citation
            matches = _detect_competitors_in_citation(
                c, filtered_competitors, all_competitor_domains
            )
            if not matches:
                continue

            # Allocate credit
            credit = _allocate_citation_credit(
                matches, domain, all_competitor_domains
            )

            for comp_name, share in credit.items():
                cd = comp_data[comp_name]
                cd["queries_present"].add(qid or query_text)
                cd["citation_count"] += share
                cd["weighted_citation_score"] += weight * share
                if cit_rank is not None:
                    cd["citation_ranks"].append(cit_rank)

                # Source type classification
                st = classify_source_type(
                    url, all_competitor_domain_set, existing_st
                )
                cd["source_type_weighted"][st] += weight * share

                # Topic presence
                if topic and topic != "Unclassified":
                    cd["topic_presence"][topic] += 1

                # Domain stats
                ds = cd["domain_stats"][domain]
                ds["citation_count"] += share
                ds["weighted_citation_score"] += weight * share
                if not ds["source_type"]:
                    ds["source_type"] = st

                # Query stats
                qs = cd["query_stats"][qid or query_text]
                qs["citation_count"] += share
                if cit_rank is not None and cit_rank < qs["best_citation_rank"]:
                    qs["best_citation_rank"] = cit_rank
                qs["source_types"].add(st)

                # Framing text
                text_blob = _citation_text_blob(c)
                if text_blob:
                    cd["framing_texts"].append(text_blob)

                query_competitors.add(comp_name)

        # Also mark competitors found via answer text or explicit fields
        for comp_name in query_competitors:
            if comp_name in filtered_competitors:
                comp_data[comp_name]["queries_present"].add(qid or query_text)
                if topic and topic != "Unclassified":
                    comp_data[comp_name]["topic_presence"][topic] += 1

    # Compute scores and build output
    max_weighted_score = max(
        (cd["weighted_citation_score"] for cd in comp_data.values()),
        default=1.0
    ) or 1.0
    max_source_types_observed = max(
        (len(cd["source_type_weighted"]) for cd in comp_data.values()),
        default=1
    ) or 1
    total_non_branded_topics = len(all_topics) or 1

    competitors_output: list[dict] = []

    for comp_name in sorted(comp_data.keys()):
        cd = comp_data[comp_name]
        queries_present = len(cd["queries_present"])
        citation_count = cd["citation_count"]
        weighted_score = cd["weighted_citation_score"]
        ranks = cd["citation_ranks"]
        avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else 0.0

        # Query presence %
        query_presence_pct = round(
            (queries_present / query_count_non_branded * 100)
            if query_count_non_branded > 0 else 0, 1
        )

        # Citation share %
        citation_share_pct = round(
            (citation_count / total_non_branded_citations * 100)
            if total_non_branded_citations > 0 else 0, 1
        )

        # Source type influence %
        total_weighted = sum(cd["source_type_weighted"].values()) or 1.0
        source_type_influence: dict[str, float] = {}
        for st in SOURCE_TYPE_CATEGORIES:
            pct = round(
                cd["source_type_weighted"].get(st, 0) / total_weighted * 100, 1
            )
            source_type_influence[st] = pct

        # Topic presence
        topic_presence = dict(cd["topic_presence"].most_common(10))

        # Top domains (top 5)
        top_domains = sorted(
            [
                {
                    "domain": d,
                    "citation_count": round(ds["citation_count"], 1),
                    "weighted_citation_score": round(ds["weighted_citation_score"], 2),
                    "source_type": ds["source_type"],
                }
                for d, ds in cd["domain_stats"].items()
                if d
            ],
            key=lambda x: x["weighted_citation_score"],
            reverse=True,
        )[:5]

        # Top queries (top 5)
        top_queries = sorted(
            [
                {
                    "query_id": qid_or_text,
                    "query": qid_or_text,
                    "topic": "",  # Will be enriched below
                    "citation_count": round(qs["citation_count"], 1),
                    "best_citation_rank": qs["best_citation_rank"] if qs["best_citation_rank"] < 999 else None,
                    "source_types": sorted(qs["source_types"]),
                }
                for qid_or_text, qs in cd["query_stats"].items()
            ],
            key=lambda x: x["citation_count"],
            reverse=True,
        )[:5]

        # Enrich top queries with topic from original data
        qid_to_topic: dict[str, str] = {}
        for q in non_branded_queries:
            qid = _text(q.get("query_id") or q.get("id") or "")
            qt = _text(q.get("query") or "")
            t = _text(
                q.get("topic") or q.get("brand_topic") or
                q.get("journey_category") or ""
            )
            if qid:
                qid_to_topic[qid] = t
            if qt:
                qid_to_topic[qt] = t
        for tq in top_queries:
            tq["topic"] = qid_to_topic.get(tq["query_id"], "")

        # AI Visibility Score components
        query_presence_component = min(
            25.0,
            25.0 * queries_present / query_count_non_branded
            if query_count_non_branded > 0 else 0,
        )
        citation_presence_component = min(
            30.0,
            30.0 * citation_count / total_non_branded_citations
            if total_non_branded_citations > 0 else 0,
        )
        citation_rank_component = min(
            15.0,
            15.0 * weighted_score / max_weighted_score,
        )
        topic_breadth_component = min(
            10.0,
            10.0 * len(cd["topic_presence"]) / total_non_branded_topics,
        )
        source_diversity_component = min(
            10.0,
            10.0 * len(cd["source_type_weighted"]) / max_source_types_observed,
        )
        framing_component = compute_framing_score(cd["framing_texts"])

        ai_visibility_score = round(
            query_presence_component +
            citation_presence_component +
            citation_rank_component +
            topic_breadth_component +
            source_diversity_component +
            framing_component,
            1,
        )

        score_components = {
            "query_presence": round(query_presence_component, 1),
            "citation_presence": round(citation_presence_component, 1),
            "citation_rank": round(citation_rank_component, 1),
            "topic_breadth": round(topic_breadth_component, 1),
            "source_diversity": round(source_diversity_component, 1),
            "framing_signal": round(framing_component, 1),
        }

        # Interpretation (deterministic, not LLM)
        top_source = max(
            source_type_influence.items(),
            key=lambda x: x[1],
            default=("other_external", 0),
        )
        interpretation = (
            f"{comp_name} visibility is primarily driven by "
            f"{top_source[0].replace('_', ' ')} sources "
            f"({top_source[1]}% of weighted citations). "
            f"Present in {queries_present} of {query_count_non_branded} "
            f"non-branded queries ({query_presence_pct}%)."
        )

        competitors_output.append({
            "competitor": comp_name,
            "ai_visibility_score": ai_visibility_score,
            "queries_present": queries_present,
            "query_presence_pct": query_presence_pct,
            "citation_count": round(citation_count, 1),
            "citation_share_pct": citation_share_pct,
            "weighted_citation_score": round(weighted_score, 2),
            "avg_citation_rank": avg_rank,
            "source_type_influence_pct": source_type_influence,
            "topic_presence": topic_presence,
            "top_domains": top_domains,
            "top_queries": top_queries,
            "score_components": score_components,
            "interpretation": interpretation,
        })

    # Sort by AI visibility score descending
    competitors_output.sort(
        key=lambda x: x["ai_visibility_score"], reverse=True
    )

    matrix = {
        "schema_version": "competitor_visibility_matrix.v1",
        "brand": brand,
        "market": market,
        "basis": "non_branded_queries_in_brand_audit",
        "query_count_total": query_count_total,
        "query_count_non_branded": query_count_non_branded,
        "competitors": competitors_output,
        "methodology": {
            "score_type": "observed_competitor_visibility_index",
            "score_scale": "0-100",
            "scoring_components": {
                "query_presence": 25,
                "citation_presence": 30,
                "citation_rank": 15,
                "topic_breadth": 10,
                "source_diversity": 10,
                "framing_signal": 10,
            },
            "citation_rank_weights": {
                "1": 1.0,
                "2": 0.75,
                "3": 0.55,
                "4": 0.35,
                "5": 0.2,
            },
        },
    }

    return matrix


def write_competitor_visibility_matrix(
    matrix: dict,
    output_dir: Path,
) -> Path:
    """Write the competitor visibility matrix to disk."""
    output_path = output_dir / "competitor_visibility" / "competitor_visibility_matrix.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def print_summary(matrix: dict) -> None:
    """Print a concise summary after generation."""
    competitors = matrix.get("competitors") or []
    top_comp = competitors[0] if competitors else None
    print(json.dumps({
        "status": "competitor_visibility_matrix_ready",
        "non_branded_queries_used": matrix.get("query_count_non_branded", 0),
        "total_queries": matrix.get("query_count_total", 0),
        "observed_competitors": len(competitors),
        "top_competitor": top_comp["competitor"] if top_comp else None,
        "top_competitor_score": top_comp["ai_visibility_score"] if top_comp else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build Non-Branded Competitor Visibility Matrix")
    ap.add_argument("--input", required=True, help="Path to frontend_report_bundle.json")
    ap.add_argument("--output-dir", default="outputs", help="Output directory")
    ap.add_argument("--brand", default="", help="Audited brand name")
    ap.add_argument("--market", default="", help="Audited market")
    args = ap.parse_args()

    bundle_path = Path(args.input)
    if not bundle_path.exists():
        print(f"Error: Input file not found: {bundle_path}")
        raise SystemExit(1)

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    matrix = build_competitor_visibility_matrix(
        bundle, brand=args.brand or "", market=args.market or ""
    )
    output_path = write_competitor_visibility_matrix(matrix, Path(args.output_dir))
    print_summary(matrix)
    print(f"Output: {output_path}")
