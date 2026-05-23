"""Advanced GEO/AEO Recommendation Generator — Contract & Schema Definitions.

Defines the data contracts for:
- advanced_geo_asset.v1 (CMS recommendations)
- advanced_pr_asset_pack.v1 (PR opportunities)
- Fact traceability structures

This is a contract expansion, not a prompt-only improvement.
Existing dashboard fields remain backward compatible.
The frontend renders new fields when present; existing reports continue working.
"""
from __future__ import annotations

from typing import Any, Literal

# ---------------------------------------------------------------------------
# Fact Traceability
# ---------------------------------------------------------------------------

FACT_SOURCE_TYPES = Literal[
    "owned_page",
    "existing_json_ld",
    "crawl_metadata",
    "approved_input",
]


def make_fact_entry(
    fact: str,
    value: str | None = None,
    unit: str | None = None,
    source: str = "owned_page",
    source_context_snippet: str = "",
    source_url: str | None = None,
) -> dict[str, Any]:
    """Create a single fact_used entry with full traceability.

    Every numeric, technical, price, dimension, warranty, range, charging,
    capacity, safety, or family/practicality claim must be traceable.

    Allowed sources:
    - owned_page: visible crawl text from the owned page
    - existing_json_ld: JSON-LD extracted from the page
    - crawl_metadata: crawl metadata (title, description, canonical)
    - approved_input: facts supplied by client/product/legal

    NOT allowed:
    - External competitor pages as factual source
    - Inferred values
    - Model memory
    - Generic assumptions
    - Invented copy containing unverified specs
    """
    entry: dict[str, Any] = {
        "fact": fact,
        "source": source,
        "source_context_snippet": source_context_snippet,
    }
    if value is not None:
        entry["value"] = value
    if unit is not None:
        entry["unit"] = unit
    if source_url:
        entry["source_url"] = source_url
    return entry


# ---------------------------------------------------------------------------
# advanced_geo_asset.v1 — CMS Contract
# ---------------------------------------------------------------------------

ADVANCED_GEO_ASSET_SCHEMA_VERSION = "advanced_geo_asset.v1"

JSON_LD_STRATEGIES = Literal[
    "standalone_id_extension",
    "full_page_merge_patch",
]


def make_advanced_geo_asset(
    *,
    expected_impact_score_10: int | float = 0,
    direct_answer_40_words: str = "",
    html_component: str = "",
    json_ld_strategy: str = "standalone_id_extension",
    target_anchor_id: str | None = None,
    json_ld_script: str = "",
    json_ld_merge_notes: list[str] | None = None,
    localized_copy_language: str = "en",
    facts_used: list[dict[str, Any]] | None = None,
    validation_flags: list[str] | None = None,
    legal_review_required: bool = False,
) -> dict[str, Any]:
    """Build an advanced_geo_asset.v1 object for a CMS recommendation.

    This asset contains deployable CMS HTML, safe JSON-LD extension scripts,
    and strict fact traceability.
    """
    asset: dict[str, Any] = {
        "schema_version": ADVANCED_GEO_ASSET_SCHEMA_VERSION,
        "expected_impact_score_10": max(0, min(10, round(float(expected_impact_score_10), 1))),
        "direct_answer_40_words": direct_answer_40_words,
        "html_component": html_component,
        "json_ld_strategy": json_ld_strategy,
        "json_ld_script": json_ld_script,
        "json_ld_merge_notes": json_ld_merge_notes or [],
        "localized_copy_language": localized_copy_language,
        "facts_used": facts_used or [],
        "validation_flags": validation_flags or [],
        "legal_review_required": legal_review_required,
    }
    if target_anchor_id:
        asset["target_anchor_id"] = target_anchor_id
    return asset


# ---------------------------------------------------------------------------
# advanced_pr_asset_pack.v1 — PR Contract
# ---------------------------------------------------------------------------

ADVANCED_PR_ASSET_PACK_SCHEMA_VERSION = "advanced_pr_asset_pack.v1"


def make_advanced_pr_asset_pack(
    *,
    asset_name: str = "",
    asset_type: str = "",
    information_gain_trigger: str = "",
    unique_brand_data_required: list[str] | None = None,
    target_publisher_types: list[str] | None = None,
    target_domains_observed: list[str] | None = None,
    publisher_format_requirements: list[str] | None = None,
    semantic_triggers: list[str] | None = None,
    suggested_headline: str = "",
    briefing_copy: str = "",
    validation_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Build an advanced_pr_asset_pack.v1 object for a PR opportunity.

    This asset pack contains everything a PR team needs to create
    corroborating third-party evidence.
    """
    return {
        "schema_version": ADVANCED_PR_ASSET_PACK_SCHEMA_VERSION,
        "asset_name": asset_name,
        "asset_type": asset_type,
        "information_gain_trigger": information_gain_trigger,
        "unique_brand_data_required": unique_brand_data_required or [],
        "target_publisher_types": target_publisher_types or [],
        "target_domains_observed": target_domains_observed or [],
        "publisher_format_requirements": publisher_format_requirements or [],
        "semantic_triggers": semantic_triggers or [],
        "suggested_headline": suggested_headline,
        "briefing_copy": briefing_copy,
        "validation_flags": validation_flags or [],
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_fact_snippet_contains_claim(fact: dict[str, Any]) -> bool:
    """Validate that source_context_snippet contains the claimed fact/value/unit.

    Critical validation rule:
    source_context_snippet must contain the fact/value/unit being used,
    or a directly equivalent source node.

    Returns True if the snippet validates, False otherwise.
    """
    snippet = str(fact.get("source_context_snippet") or "").lower()
    if not snippet:
        return False

    value = str(fact.get("value") or "").lower()
    unit = str(fact.get("unit") or "").lower()
    fact_name = str(fact.get("fact") or "").lower()

    # If there is a specific numeric value, the snippet must contain it.
    if value:
        # Try exact match first.
        if value in snippet:
            return True
        # Try without commas/periods for numeric formatting differences.
        clean_value = value.replace(",", "").replace(".", "")
        clean_snippet = snippet.replace(",", "").replace(".", "")
        if clean_value and clean_value in clean_snippet:
            return True
        return False

    # If no specific value but there is a fact name, check for that.
    if fact_name and fact_name in snippet:
        return True

    # If unit is present, check for it.
    if unit and unit in snippet:
        return True

    # No verifiable claim data found.
    return False


def validate_direct_answer_word_count(text: str, max_words: int = 40) -> bool:
    """Validate that direct_answer_40_words is under 40 words."""
    words = text.split()
    return len(words) <= max_words


def validate_html_component(html: str) -> list[str]:
    """Validate html_component contains required elements.

    Returns list of validation issues (empty = valid).
    """
    issues: list[str] = []
    if not html.strip():
        issues.append("html_component is empty")
        return issues
    if 'class="geo-lead-answer"' not in html and "class='geo-lead-answer'" not in html:
        issues.append('html_component must contain class="geo-lead-answer"')
    # Check for basic semantic HTML elements.
    semantic_tags = ["<section", "<article", "<div", "<h2", "<h3", "<p", "<ul", "<ol"]
    if not any(tag in html.lower() for tag in semantic_tags):
        issues.append("html_component should contain semantic HTML elements")
    return issues


def validate_json_ld_script(script: str) -> list[str]:
    """Validate that json_ld_script is valid JSON.

    Returns list of validation issues (empty = valid).
    """
    import json

    issues: list[str] = []
    if not script.strip():
        # Empty is acceptable when no JSON-LD is generated.
        return issues
    try:
        parsed = json.loads(script)
        if not isinstance(parsed, dict):
            issues.append("json_ld_script must be a JSON object")
        elif "@context" not in parsed and "@type" not in parsed:
            issues.append("json_ld_script should contain @context or @type")
    except json.JSONDecodeError as exc:
        issues.append(f"json_ld_script is not valid JSON: {exc}")
    return issues


def validate_advanced_geo_asset(asset: dict[str, Any]) -> list[str]:
    """Full validation of an advanced_geo_asset.v1 object.

    Returns list of validation issues (empty = valid).
    """
    issues: list[str] = []

    if asset.get("schema_version") != ADVANCED_GEO_ASSET_SCHEMA_VERSION:
        issues.append(f"Expected schema_version={ADVANCED_GEO_ASSET_SCHEMA_VERSION}")

    # Validate direct answer word count.
    direct_answer = str(asset.get("direct_answer_40_words") or "")
    if direct_answer and not validate_direct_answer_word_count(direct_answer):
        issues.append(f"direct_answer_40_words exceeds 40 words ({len(direct_answer.split())} words)")

    # Validate HTML component.
    html = str(asset.get("html_component") or "")
    if html:
        issues.extend(validate_html_component(html))

    # Validate JSON-LD script.
    json_ld = str(asset.get("json_ld_script") or "")
    if json_ld:
        issues.extend(validate_json_ld_script(json_ld))

    # Validate fact traceability.
    facts = asset.get("facts_used") or []
    for i, fact in enumerate(facts):
        if not isinstance(fact, dict):
            issues.append(f"facts_used[{i}] is not a dict")
            continue
        if not fact.get("fact"):
            issues.append(f"facts_used[{i}] missing 'fact' field")
        if not fact.get("source"):
            issues.append(f"facts_used[{i}] missing 'source' field")
        if fact.get("source") not in ("owned_page", "existing_json_ld", "crawl_metadata", "approved_input", None):
            issues.append(f"facts_used[{i}] has invalid source: {fact.get('source')}")
        if not validate_fact_snippet_contains_claim(fact):
            issues.append(f"facts_used[{i}] snippet does not contain claimed value for fact '{fact.get('fact')}'")

    # Validate impact score range.
    score = asset.get("expected_impact_score_10")
    if score is not None:
        try:
            s = float(score)
            if s < 0 or s > 10:
                issues.append(f"expected_impact_score_10 out of range: {s}")
        except (TypeError, ValueError):
            issues.append(f"expected_impact_score_10 is not numeric: {score}")

    return issues


def validate_advanced_pr_asset_pack(pack: dict[str, Any]) -> list[str]:
    """Full validation of an advanced_pr_asset_pack.v1 object.

    Returns list of validation issues (empty = valid).
    """
    issues: list[str] = []

    if pack.get("schema_version") != ADVANCED_PR_ASSET_PACK_SCHEMA_VERSION:
        issues.append(f"Expected schema_version={ADVANCED_PR_ASSET_PACK_SCHEMA_VERSION}")

    required_fields = ["asset_name", "asset_type", "information_gain_trigger"]
    for field in required_fields:
        if not pack.get(field):
            issues.append(f"Missing required field: {field}")

    if not pack.get("target_publisher_types"):
        issues.append("target_publisher_types should not be empty")

    if not pack.get("semantic_triggers"):
        issues.append("semantic_triggers should not be empty")

    return issues
