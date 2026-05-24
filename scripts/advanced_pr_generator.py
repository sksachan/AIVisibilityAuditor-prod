"""Advanced PR Asset Pack Generator.

Generates advanced_pr_asset_pack.v1 for each grouped PR opportunity.
Maps publisher targets from citation evidence, defines formatting requirements,
and identifies semantic triggers.
"""
from __future__ import annotations

from typing import Any

from advanced_geo_contracts import make_advanced_pr_asset_pack


_SOURCE_TYPE_TO_ASSET_TYPE = {
    "publisher_review": "data_study_or_comparison",
    "authority_body": "authority_validation_brief",
    "partner_infrastructure": "partner_proof_point",
    "competitor_owned": "competitive_displacement_asset",
    "forum_social_video": "community_evidence_pack",
    "aggregator_marketplace": "comparison_data_pack",
    "finance_or_insurance": "ownership_cost_study",
}

_SOURCE_TYPE_TO_PUBLISHER_TYPES = {
    "publisher_review": ["automotive_review_sites", "consumer_comparison_publishers", "industry_news"],
    "authority_body": ["government_agencies", "safety_rating_bodies", "industry_standards_orgs"],
    "partner_infrastructure": ["charging_networks", "energy_providers", "infrastructure_partners"],
    "competitor_owned": ["neutral_comparison_publishers", "independent_review_sites"],
    "forum_social_video": ["community_platforms", "video_creators", "social_influencers"],
    "aggregator_marketplace": ["price_comparison_sites", "marketplace_platforms"],
    "finance_or_insurance": ["financial_publishers", "insurance_comparison_sites"],
}

_SOURCE_TYPE_TO_FORMAT_REQS = {
    "publisher_review": ["structured_data_tables", "comparison_methodology", "verifiable_test_results"],
    "authority_body": ["official_certification_reference", "standards_compliance_data"],
    "partner_infrastructure": ["network_coverage_maps", "compatibility_specifications"],
    "competitor_owned": ["neutral_third_party_validation", "independent_test_data"],
    "forum_social_video": ["real_owner_testimonials", "usage_scenario_evidence"],
    "aggregator_marketplace": ["price_transparency_data", "feature_comparison_matrices"],
    "finance_or_insurance": ["total_cost_of_ownership_data", "financing_comparison_tables"],
}


def _infer_semantic_triggers(pr_opp: dict[str, Any]) -> list[str]:
    triggers: list[str] = []
    source_type = pr_opp.get("source_type") or ""
    queries = pr_opp.get("grouped_queries") or []
    query_texts = [str(q.get("query", "")).lower() for q in queries if isinstance(q, dict)]
    combined = " ".join(query_texts)
    trigger_map = {
        "cost": ["cost", "price", "finance", "lease", "insurance", "resale", "running cost"],
        "safety": ["safety", "adas", "crash", "collision", "rating", "assist"],
        "range_charging": ["range", "battery", "charging", "charger", "ev", "electric"],
        "comparison": ["vs", "versus", "compare", "better", "best", "alternative"],
        "warranty": ["warranty", "guarantee", "coverage"],
        "family": ["family", "seat", "luggage", "storage", "comfort"],
        "technology": ["hybrid", "e-power", "powertrain", "fuel", "technology"],
        "sustainability": ["environment", "emission", "green", "eco", "carbon"],
    }
    for trigger_name, keywords in trigger_map.items():
        if any(kw in combined for kw in keywords):
            triggers.append(trigger_name)
    if source_type == "authority_body":
        triggers.append("official_validation")
    elif source_type == "partner_infrastructure":
        triggers.append("infrastructure_readiness")
    elif source_type == "competitor_owned":
        triggers.append("competitive_differentiation")
    return list(dict.fromkeys(triggers)) or ["general_visibility"]


def _infer_information_gain(pr_opp: dict[str, Any], brand: str = "") -> str:
    source_type = pr_opp.get("source_type") or ""
    opportunity_type = pr_opp.get("opportunity_type") or ""
    query_count = pr_opp.get("query_coverage_count") or 0
    brand_name = brand or "the brand"
    if "authority" in opportunity_type or source_type == "authority_body":
        return f"Independent authority validation of {brand_name} claims across {query_count} buyer queries"
    if "competitor" in opportunity_type or source_type == "competitor_owned":
        return f"Third-party evidence that offsets competitor-owned citations for {query_count} queries"
    if "publisher" in opportunity_type or source_type == "publisher_review":
        return f"Neutral publisher coverage with verifiable data for {query_count} buyer decision queries"
    if source_type == "forum_social_video":
        return f"Real-world owner evidence addressing {query_count} community-driven queries"
    if source_type == "partner_infrastructure":
        return f"Infrastructure partner validation for {query_count} practical-use queries"
    return f"New third-party evidence for {query_count} queries currently dominated by external sources"


def _infer_unique_brand_data(pr_opp: dict[str, Any]) -> list[str]:
    data_needed: list[str] = []
    queries = pr_opp.get("grouped_queries") or []
    query_texts = " ".join(str(q.get("query", "")).lower() for q in queries if isinstance(q, dict))
    if any(kw in query_texts for kw in ["cost", "price", "finance"]):
        data_needed.append("verified_pricing_data")
        data_needed.append("total_cost_of_ownership_analysis")
    if any(kw in query_texts for kw in ["range", "battery", "charging"]):
        data_needed.append("real_world_range_test_data")
        data_needed.append("charging_speed_specifications")
    if any(kw in query_texts for kw in ["safety", "crash", "rating"]):
        data_needed.append("safety_test_results")
        data_needed.append("safety_feature_specifications")
    if any(kw in query_texts for kw in ["warranty", "guarantee"]):
        data_needed.append("warranty_terms_and_conditions")
    if any(kw in query_texts for kw in ["family", "seat", "storage"]):
        data_needed.append("interior_dimension_measurements")
        data_needed.append("cargo_capacity_data")
    if not data_needed:
        data_needed.append("brand_specific_product_data")
        data_needed.append("verified_specifications")
    return data_needed


def _build_suggested_headline(pr_opp: dict[str, Any], brand: str = "") -> str:
    source_type = pr_opp.get("source_type") or ""
    brand_name = brand or "Brand"
    queries = pr_opp.get("grouped_queries") or []
    primary_query = queries[0].get("query", "") if queries else ""
    if source_type == "publisher_review":
        return f"{brand_name} Data Study: Evidence-Based Analysis for {primary_query[:60]}"
    if source_type == "authority_body":
        return f"Independent Validation: {brand_name} Meets Industry Standards for {primary_query[:50]}"
    if source_type == "competitor_owned":
        return f"Comparative Analysis: How {brand_name} Addresses {primary_query[:60]}"
    if source_type == "forum_social_video":
        return f"Real Owner Insights: {brand_name} in Practice for {primary_query[:60]}"
    return f"{brand_name}: New Evidence for {primary_query[:70]}"


def _build_briefing_copy(pr_opp: dict[str, Any], brand: str = "") -> str:
    brand_name = brand or "the brand"
    query_count = pr_opp.get("query_coverage_count") or 0
    source_type = pr_opp.get("source_type") or "external"
    domains = pr_opp.get("observed_external_domains") or []
    domain_names = [d.get("domain", "") for d in domains[:3] if isinstance(d, dict)]
    parts = [
        f"AI answer engines currently cite external sources for {query_count} buyer queries relevant to {brand_name}.",
    ]
    if domain_names:
        parts.append(f"Key citation domains include: {', '.join(domain_names)}.")
    parts.append(
        f"This {source_type.replace('_', ' ')} asset pack provides the evidence structure "
        f"needed to create corroborating third-party proof that can shift the citation mix."
    )
    parts.append(
        "All claims must use verified brand data only. Do not fabricate specifications or pricing."
    )
    return " ".join(parts)


def build_advanced_pr_asset_pack(
    pr_opp: dict[str, Any],
    brand: str = "",
) -> dict[str, Any]:
    source_type = pr_opp.get("source_type") or "other"
    asset_type = _SOURCE_TYPE_TO_ASSET_TYPE.get(source_type, "general_proof_asset")
    asset_name = f"{brand or 'Brand'} {asset_type.replace('_', ' ').title()}"
    publisher_types = _SOURCE_TYPE_TO_PUBLISHER_TYPES.get(source_type, ["general_publishers"])
    format_reqs = _SOURCE_TYPE_TO_FORMAT_REQS.get(source_type, ["structured_evidence_format"])
    domains = pr_opp.get("observed_external_domains") or []
    target_domains = [d.get("domain", "") for d in domains[:8] if isinstance(d, dict) and d.get("domain")]
    semantic_triggers = _infer_semantic_triggers(pr_opp)
    info_gain = _infer_information_gain(pr_opp, brand)
    unique_data = _infer_unique_brand_data(pr_opp)
    headline = _build_suggested_headline(pr_opp, brand)
    briefing = _build_briefing_copy(pr_opp, brand)
    validation_flags: list[str] = []
    if not target_domains:
        validation_flags.append("No observed external domains; publisher targeting is generic.")
    if pr_opp.get("query_coverage_count", 0) < 3:
        validation_flags.append("Low query coverage; PR impact may be limited.")
    # New actionable PR fields
    queries = pr_opp.get("grouped_queries") or []
    priority_query_texts = [str(q.get("query", "")) for q in queries[:5] if isinstance(q, dict) and q.get("query")]
    journey_mix = pr_opp.get("journey_mix") or []
    primary_journey = journey_mix[0].get("journey_category", "") if journey_mix else ""
    effective_brand = brand or "the brand"
    asset_objective = f"Create third-party-referenceable evidence for {source_type.replace('_', ' ')} sources that can shift AI answer citations toward {effective_brand} across {len(queries)} buyer queries"
    target_angle = f"Neutral, data-driven coverage targeting {source_type.replace('_', ' ')} publishers"
    if primary_journey:
        target_angle += f" in the {primary_journey} journey category"
    proof_gap = f"AI answers currently cite external {source_type.replace('_', ' ')} sources for these queries; {effective_brand} lacks corroborating third-party evidence"
    pitch_headline = headline

    result = make_advanced_pr_asset_pack(
        asset_name=asset_name,
        asset_type=asset_type,
        information_gain_trigger=info_gain,
        unique_brand_data_required=unique_data,
        target_publisher_types=publisher_types,
        target_domains_observed=target_domains,
        publisher_format_requirements=format_reqs,
        semantic_triggers=semantic_triggers,
        suggested_headline=headline,
        briefing_copy=briefing,
        validation_flags=validation_flags,
    )
    # Attach new actionable fields
    result["asset_objective"] = asset_objective
    result["target_publication_angle"] = target_angle
    result["required_brand_data"] = unique_data
    result["proof_gap_addressed"] = proof_gap
    result["example_pitch_headline"] = pitch_headline
    result["priority_queries"] = priority_query_texts
    return result


def attach_advanced_pr_asset_packs_to_bundle(
    bundle: dict[str, Any],
    brand: str = "",
) -> dict[str, Any]:
    pr_opps = (
        bundle.get("grouped_pr_opportunities")
        or bundle.get("pr_opportunities")
        or []
    )
    effective_brand = brand or bundle.get("brand", "")
    for opp in pr_opps:
        if not isinstance(opp, dict):
            continue
        if opp.get("advanced_pr_asset_pack"):
            continue
        pack = build_advanced_pr_asset_pack(opp, brand=effective_brand)
        opp["advanced_pr_asset_pack"] = pack
    return bundle
