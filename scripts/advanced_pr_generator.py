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


def _build_insight_summary(pr_opp: dict[str, Any], brand: str = "") -> str:
    """Generate an insight-led summary describing the AI visibility gap."""
    effective_brand = brand or "the brand"
    source_type = pr_opp.get("source_type") or "external"
    query_count = pr_opp.get("query_coverage_count") or 0
    queries = pr_opp.get("grouped_queries") or []
    journey_mix = pr_opp.get("journey_mix") or []
    journeys = [j.get("journey_category", "") for j in journey_mix if isinstance(j, dict) and j.get("journey_category")]
    journey_text = ", ".join(journeys[:3]) if journeys else "multiple journey categories"
    query_themes = set()
    for q in queries[:10]:
        qt = str(q.get("query", "")).lower() if isinstance(q, dict) else ""
        if any(kw in qt for kw in ["cost", "price", "finance"]): query_themes.add("ownership cost")
        if any(kw in qt for kw in ["range", "battery", "charging"]): query_themes.add("range and charging")
        if any(kw in qt for kw in ["safety", "crash", "rating"]): query_themes.add("safety")
        if any(kw in qt for kw in ["family", "seat", "storage"]): query_themes.add("family practicality")
        if any(kw in qt for kw in ["warranty", "guarantee"]): query_themes.add("warranty")
        if any(kw in qt for kw in ["compare", "vs", "best", "alternative"]): query_themes.add("comparison")
    theme_text = ", ".join(sorted(query_themes)[:4]) if query_themes else source_type.replace("_", " ")
    return f"AI answers are relying on {source_type.replace('_', ' ')} sources for {theme_text} queries across {journey_text}. {effective_brand} is present in owned pages but lacks third-party proof that AI systems can cite confidently across {query_count} affected queries."


def _build_recommended_pr_action(pr_opp: dict[str, Any], brand: str = "") -> str:
    """Generate a recommended PR action statement."""
    effective_brand = brand or "the brand"
    source_type = pr_opp.get("source_type") or "external"
    query_count = pr_opp.get("query_coverage_count") or 0
    queries = pr_opp.get("grouped_queries") or []
    query_themes = set()
    for q in queries[:10]:
        qt = str(q.get("query", "")).lower() if isinstance(q, dict) else ""
        if any(kw in qt for kw in ["cost", "price"]): query_themes.add("ownership cost")
        if any(kw in qt for kw in ["range", "charging"]): query_themes.add("range and charging")
        if any(kw in qt for kw in ["safety"]): query_themes.add("safety")
        if any(kw in qt for kw in ["family", "practicality"]): query_themes.add("daily-use suitability")
    theme_text = ", ".join(sorted(query_themes)[:3]) if query_themes else "key buyer decision criteria"
    return f"Create a third-party-referenceable evidence package covering {theme_text} for {effective_brand} targeting {source_type.replace('_', ' ')} publishers across {query_count} buyer queries."


def _build_core_claim(pr_opp: dict[str, Any], brand: str = "") -> str:
    """Generate the single core claim the brand wants third parties to validate."""
    effective_brand = brand or "the brand"
    queries = pr_opp.get("grouped_queries") or []
    query_themes = []
    for q in queries[:10]:
        qt = str(q.get("query", "")).lower() if isinstance(q, dict) else ""
        if any(kw in qt for kw in ["range", "charging", "ev"]): query_themes.append("range, charging access")
        if any(kw in qt for kw in ["cost", "price", "finance"]): query_themes.append("ownership cost")
        if any(kw in qt for kw in ["safety", "crash"]): query_themes.append("safety")
        if any(kw in qt for kw in ["family", "seat", "parking"]): query_themes.append("daily-use practicality")
    unique_themes = list(dict.fromkeys(query_themes))[:3]
    if unique_themes:
        return f"{effective_brand} products can meet buyer expectations when consumers understand {', '.join(unique_themes)} tradeoffs."
    return f"{effective_brand} products address the key buyer questions that AI answer engines currently source from external publishers."


def _build_asset_concept(pr_opp: dict[str, Any], brand: str = "") -> str:
    """Generate a sharp asset concept name."""
    effective_brand = brand or "Brand"
    source_type = pr_opp.get("source_type") or "external"
    queries = pr_opp.get("grouped_queries") or []
    query_themes = set()
    for q in queries[:10]:
        qt = str(q.get("query", "")).lower() if isinstance(q, dict) else ""
        if any(kw in qt for kw in ["range", "charging", "ev"]): query_themes.add("EV")
        if any(kw in qt for kw in ["cost", "price"]): query_themes.add("Ownership")
        if any(kw in qt for kw in ["safety"]): query_themes.add("Safety")
        if any(kw in qt for kw in ["family", "practicality"]): query_themes.add("Daily-Use")
    theme = " & ".join(sorted(query_themes)[:2]) if query_themes else source_type.replace("_", " ").title()
    return f"{effective_brand} {theme} Confidence Report"


def _build_publishable_assets(pr_opp: dict[str, Any]) -> list[str]:
    """Generate list of publishable assets based on query themes."""
    base = ["Data-led press release", "Downloadable proof sheet"]
    queries = pr_opp.get("grouped_queries") or []
    combined = " ".join(str(q.get("query", "")).lower() for q in queries if isinstance(q, dict))
    if any(kw in combined for kw in ["range", "charging", "ev"]): base.append("Range and charging explainer")
    if any(kw in combined for kw in ["cost", "price", "finance"]): base.append("Total cost of ownership comparison")
    if any(kw in combined for kw in ["safety", "crash"]): base.append("Safety rating summary")
    if any(kw in combined for kw in ["family", "seat", "parking"]): base.append("Practicality buyer guide")
    base.extend(["Dealer-ready FAQ", "Expert commentary pitch"])
    return base


def _build_publisher_groups(pr_opp: dict[str, Any]) -> list[dict[str, Any]]:
    """Build publisher groups by role from citation evidence."""
    groups: list[dict[str, Any]] = []
    source_type = pr_opp.get("source_type") or "other"
    domains = pr_opp.get("observed_external_domains") or []
    domain_names = [d.get("domain", "") for d in domains[:15] if isinstance(d, dict) and d.get("domain")]
    queries = pr_opp.get("grouped_queries") or []
    combined = " ".join(str(q.get("query", "")).lower() for q in queries if isinstance(q, dict))
    unique_data = _infer_unique_brand_data(pr_opp)
    if source_type in ("publisher_review", "aggregator_marketplace") or any(kw in combined for kw in ["compare", "vs", "best"]):
        groups.append({"group": "Auto review / comparison media", "why_it_matters": "Influence comparison and shortlist queries where buyers evaluate alternatives.", "observed_domains": [d for d in domain_names if any(kw in d for kw in ["review", "car", "auto", "motor", "compare"])][:5] or domain_names[:3], "pitch_angle": "Evidence-based comparison using verified specifications and real-world data.", "proof_required": [d for d in unique_data if any(kw in d for kw in ["spec", "test", "comparison"])] or unique_data[:2]})
    if any(kw in combined for kw in ["charge", "range", "battery", "ev"]):
        groups.append({"group": "Charging / EV infrastructure sources", "why_it_matters": "Improve confidence around charging access and range for prospective buyers.", "observed_domains": [d for d in domain_names if any(kw in d for kw in ["charge", "ev", "energy", "electric"])][:5] or domain_names[:2], "pitch_angle": "Practical charging guidance and real-world range data for target market drivers.", "proof_required": [d for d in unique_data if any(kw in d for kw in ["range", "charging", "battery"])] or ["real_world_range_test_data", "charging_speed_specifications"]})
    if any(kw in combined for kw in ["cost", "price", "finance", "insurance", "tax"]):
        groups.append({"group": "Consumer cost / ownership publications", "why_it_matters": "Support cost, tax, finance, and incentive queries with transparent ownership data.", "observed_domains": [d for d in domain_names if any(kw in d for kw in ["finance", "cost", "price", "money"])][:5] or domain_names[:2], "pitch_angle": "Total cost of ownership comparison with transparent methodology.", "proof_required": [d for d in unique_data if any(kw in d for kw in ["cost", "pricing", "ownership"])] or ["verified_pricing_data", "total_cost_of_ownership_analysis"]})
    if any(kw in combined for kw in ["family", "parking", "city", "compact", "urban"]):
        groups.append({"group": "Local / city mobility sources", "why_it_matters": "Support parking, compact, and urban-use queries with practical evidence.", "observed_domains": [d for d in domain_names if any(kw in d for kw in ["city", "local", "urban", "mobility"])][:5] or domain_names[:2], "pitch_angle": "City-friendly ownership with practical dimensions, parking, and daily-use evidence.", "proof_required": [d for d in unique_data if any(kw in d for kw in ["dimension", "interior", "cargo"])] or ["interior_dimension_measurements", "cargo_capacity_data"]})
    if not groups:
        groups.append({"group": f"{source_type.replace('_', ' ').title()} publishers", "why_it_matters": f"Influence {source_type.replace('_', ' ')} queries with credible third-party evidence.", "observed_domains": domain_names[:5], "pitch_angle": "Neutral, data-driven coverage with verifiable brand facts.", "proof_required": unique_data[:3]})
    return groups


def _build_semantic_trigger_groups(pr_opp: dict[str, Any]) -> list[dict[str, Any]]:
    """Build semantic trigger groups as AI answer hooks."""
    groups: list[dict[str, Any]] = []
    queries = pr_opp.get("grouped_queries") or []
    combined = " ".join(str(q.get("query", "")).lower() for q in queries if isinstance(q, dict))
    if any(kw in combined for kw in ["range", "battery", "charging", "ev"]):
        groups.append({"theme": "Range confidence", "triggers": ["real-world range", "highway range", "city range", "charging time", "battery capacity"], "required_evidence": ["official range by grade", "charging scenarios", "usage assumptions"]})
    if any(kw in combined for kw in ["parking", "compact", "city", "family", "narrow"]):
        groups.append({"theme": "Urban practicality", "triggers": ["narrow streets", "parking", "compact EV", "family use", "city driving"], "required_evidence": ["dimensions", "turning radius", "parking guidance", "cargo/seating facts"]})
    if any(kw in combined for kw in ["cost", "price", "incentive", "tax", "maintenance"]):
        groups.append({"theme": "Ownership cost", "triggers": ["incentives", "tax", "fuel saving", "maintenance", "resale"], "required_evidence": ["TCO examples", "tax/incentive eligibility", "maintenance guidance"]})
    if any(kw in combined for kw in ["warranty", "reliability", "battery", "durability"]):
        groups.append({"theme": "Reliability and trust", "triggers": ["long-term reliability", "warranty", "battery durability", "service network"], "required_evidence": ["warranty terms", "battery coverage", "service network", "owner support"]})
    if any(kw in combined for kw in ["safety", "crash", "adas", "assist"]):
        groups.append({"theme": "Safety assurance", "triggers": ["safety rating", "crash test", "ADAS features", "driver assist"], "required_evidence": ["safety test results", "feature specifications", "third-party ratings"]})
    if not groups:
        triggers = _infer_semantic_triggers(pr_opp)
        groups.append({"theme": "General visibility", "triggers": triggers, "required_evidence": _infer_unique_brand_data(pr_opp)[:3]})
    return groups


def _build_measurement_plan(pr_opp: dict[str, Any]) -> list[str]:
    """Generate measurement plan for tracking PR asset success."""
    return [
        "Track external citations mentioning the brand",
        "Track source type mix shift after asset publication",
        "Track linked query visibility score delta",
        "Track whether AI answers cite new proof asset",
    ]


def _build_legal_review_items(pr_opp: dict[str, Any]) -> list[str]:
    """Generate legal/compliance review checklist."""
    items = [
        "No unsupported comparison claims",
        "All numeric claims source-linked",
        "All competitor references neutral",
    ]
    queries = pr_opp.get("grouped_queries") or []
    combined = " ".join(str(q.get("query", "")).lower() for q in queries if isinstance(q, dict))
    if any(kw in combined for kw in ["incentive", "tax", "subsidy"]):
        items.append("No stale incentive values")
    if any(kw in combined for kw in ["price", "cost", "finance"]):
        items.append("Pricing data verified as current")
    if any(kw in combined for kw in ["safety", "crash", "rating"]):
        items.append("Safety claims reference official test results only")
    return items


def build_advanced_pr_asset_pack(
    pr_opp: dict[str, Any],
    brand: str = "",
) -> dict[str, Any]:
    source_type = pr_opp.get("source_type") or "other"
    asset_type = _SOURCE_TYPE_TO_ASSET_TYPE.get(source_type, "general_proof_asset")
    effective_brand = brand or "the brand"
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

    # New PR action brief fields
    insight_summary = _build_insight_summary(pr_opp, brand)
    recommended_pr_action = _build_recommended_pr_action(pr_opp, brand)
    core_claim = _build_core_claim(pr_opp, brand)
    asset_concept = _build_asset_concept(pr_opp, brand)
    asset_name = asset_concept  # Use the sharper concept name
    publishable_assets = _build_publishable_assets(pr_opp)
    publisher_groups = _build_publisher_groups(pr_opp)
    semantic_trigger_groups = _build_semantic_trigger_groups(pr_opp)
    measurement_plan = _build_measurement_plan(pr_opp)
    legal_review = _build_legal_review_items(pr_opp)

    queries = pr_opp.get("grouped_queries") or []
    priority_query_texts = [str(q.get("query", "")) for q in queries[:5] if isinstance(q, dict) and q.get("query")]
    journey_mix = pr_opp.get("journey_mix") or []
    primary_journey = journey_mix[0].get("journey_category", "") if journey_mix else ""

    asset_objective = f"Create third-party-referenceable evidence for {source_type.replace('_', ' ')} sources that can shift AI answer citations toward {effective_brand} across {len(queries)} buyer queries"
    target_angle = f"Neutral, data-driven coverage targeting {source_type.replace('_', ' ')} publishers"
    if primary_journey:
        target_angle += f" in the {primary_journey} journey category"
    proof_gap = f"AI answers currently cite external {source_type.replace('_', ' ')} sources for these queries; {effective_brand} lacks corroborating third-party evidence"

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
    # Attach new PR action brief fields
    result["insight_summary"] = insight_summary
    result["recommended_pr_action"] = recommended_pr_action
    result["core_claim_to_prove"] = core_claim
    result["asset_concept"] = asset_concept
    result["publishable_assets"] = publishable_assets
    result["publisher_groups"] = publisher_groups
    result["semantic_trigger_groups"] = semantic_trigger_groups
    result["brand_data_required"] = unique_data
    result["legal_review_required"] = legal_review
    result["measurement_plan"] = measurement_plan
    result["priority_queries"] = priority_query_texts
    # Legacy fields for backward compatibility
    result["asset_objective"] = asset_objective
    result["target_publication_angle"] = target_angle
    result["required_brand_data"] = unique_data
    result["proof_gap_addressed"] = proof_gap
    result["example_pitch_headline"] = headline
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
