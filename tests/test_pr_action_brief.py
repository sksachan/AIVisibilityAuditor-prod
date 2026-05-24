"""Tests for PR & Brand Suggestions screen quality improvement.

Validates the new advanced_pr_asset_pack schema with insight-led fields:
insight_summary, recommended_pr_action, core_claim_to_prove, asset_concept,
publishable_assets, publisher_groups, semantic_trigger_groups, brand_data_required,
legal_review_required, measurement_plan.
"""
from __future__ import annotations

import json
import sys
import os

# Ensure scripts directory is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from advanced_pr_generator import (
    build_advanced_pr_asset_pack,
    attach_advanced_pr_asset_packs_to_bundle,
    _build_insight_summary,
    _build_recommended_pr_action,
    _build_core_claim,
    _build_asset_concept,
    _build_publishable_assets,
    _build_publisher_groups,
    _build_semantic_trigger_groups,
    _build_measurement_plan,
    _build_legal_review_items,
)


def _sample_pr_opp(source_type="publisher_review", query_count=5):
    return {
        "source_type": source_type,
        "opportunity_type": "publisher_and_comparison_coverage",
        "query_coverage_count": query_count,
        "grouped_queries": [
            {"query_id": f"q{i:03d}", "query": q, "journey_category": "EV range, charging and battery confidence", "visibility_status": "external_led"}
            for i, q in enumerate([
                "What is the real-world range of electric SUVs?",
                "How long does it take to charge an EV at home?",
                "What is the total cost of ownership for an EV vs hybrid?",
                "Are compact EVs practical for city parking and narrow streets?",
                "Which EV has the best warranty and battery coverage?",
            ], start=1)
        ],
        "journey_mix": [{"journey_category": "EV range, charging and battery confidence", "count": 3}, {"journey_category": "Value, offers, finance and total cost of ownership", "count": 2}],
        "observed_external_domains": [{"domain": "carwow.co.uk", "count": 3}, {"domain": "autocar.co.uk", "count": 2}, {"domain": "whatcar.com", "count": 1}],
        "competitors_observed": [{"competitor": "Toyota", "count": 3}],
    }


def test_insight_summary_generated():
    opp = _sample_pr_opp()
    summary = _build_insight_summary(opp, "Nissan")
    assert summary, "insight_summary should not be empty"
    assert "Nissan" in summary, "insight_summary should mention the brand"
    assert len(summary) > 50, "insight_summary should be substantive"
    print(f"  \u2713 insight_summary generated: {summary[:100]}...")


def test_recommended_pr_action_generated():
    opp = _sample_pr_opp()
    action = _build_recommended_pr_action(opp, "Nissan")
    assert action, "recommended_pr_action should not be empty"
    assert "Nissan" in action, "recommended_pr_action should mention the brand"
    print(f"  \u2713 recommended_pr_action generated: {action[:100]}...")


def test_core_claim_generated():
    opp = _sample_pr_opp()
    claim = _build_core_claim(opp, "Nissan")
    assert claim, "core_claim_to_prove should not be empty"
    assert "Nissan" in claim, "core_claim should mention the brand"
    print(f"  \u2713 core_claim_to_prove generated: {claim[:100]}...")


def test_asset_concept_is_sharp():
    opp = _sample_pr_opp()
    concept = _build_asset_concept(opp, "Nissan")
    assert concept, "asset_concept should not be empty"
    assert "Nissan" in concept, "asset_concept should mention the brand"
    assert "General" not in concept, "asset_concept should not be generic"
    print(f"  \u2713 asset_concept is sharp: {concept}")


def test_publishable_assets_generated():
    opp = _sample_pr_opp()
    assets = _build_publishable_assets(opp)
    assert len(assets) >= 3, f"Expected at least 3 publishable assets, got {len(assets)}"
    assert "Data-led press release" in assets, "Should include press release"
    print(f"  \u2713 publishable_assets: {assets}")


def test_publisher_groups_by_role():
    opp = _sample_pr_opp()
    groups = _build_publisher_groups(opp)
    assert len(groups) >= 1, f"Expected at least 1 publisher group, got {len(groups)}"
    for g in groups:
        assert g.get("group"), "Each group must have a name"
        assert g.get("why_it_matters"), "Each group must explain why it matters"
        assert g.get("pitch_angle"), "Each group must have a pitch angle"
        assert isinstance(g.get("observed_domains"), list), "observed_domains must be a list"
        assert isinstance(g.get("proof_required"), list), "proof_required must be a list"
    print(f"  \u2713 publisher_groups: {[g['group'] for g in groups]}")


def test_semantic_trigger_groups():
    opp = _sample_pr_opp()
    groups = _build_semantic_trigger_groups(opp)
    assert len(groups) >= 1, f"Expected at least 1 trigger group, got {len(groups)}"
    for g in groups:
        assert g.get("theme"), "Each group must have a theme"
        assert isinstance(g.get("triggers"), list) and len(g["triggers"]) > 0, "triggers must be non-empty list"
        assert isinstance(g.get("required_evidence"), list) and len(g["required_evidence"]) > 0, "required_evidence must be non-empty list"
    print(f"  \u2713 semantic_trigger_groups: {[g['theme'] for g in groups]}")


def test_measurement_plan():
    opp = _sample_pr_opp()
    plan = _build_measurement_plan(opp)
    assert len(plan) >= 3, f"Expected at least 3 measurement items, got {len(plan)}"
    print(f"  \u2713 measurement_plan: {plan}")


def test_legal_review_items():
    opp = _sample_pr_opp()
    items = _build_legal_review_items(opp)
    assert len(items) >= 3, f"Expected at least 3 legal review items, got {len(items)}"
    print(f"  \u2713 legal_review_required: {items}")


def test_full_pack_has_all_new_fields():
    opp = _sample_pr_opp()
    pack = build_advanced_pr_asset_pack(opp, brand="Nissan")
    required_fields = [
        "insight_summary", "recommended_pr_action", "core_claim_to_prove",
        "asset_concept", "publishable_assets", "publisher_groups",
        "semantic_trigger_groups", "brand_data_required", "legal_review_required",
        "measurement_plan", "priority_queries",
    ]
    for field in required_fields:
        assert field in pack, f"Missing field: {field}"
        val = pack[field]
        if isinstance(val, str):
            assert val, f"Field {field} should not be empty string"
        elif isinstance(val, list):
            assert len(val) > 0, f"Field {field} should not be empty list"
    # Verify no generic asset name
    assert "General" not in pack.get("asset_name", ""), "asset_name should not be generic"
    print(f"  \u2713 Full pack has all {len(required_fields)} new fields")


def test_pack_no_generic_title():
    opp = _sample_pr_opp()
    pack = build_advanced_pr_asset_pack(opp, brand="Nissan")
    title = pack.get("insight_summary", "")
    assert "generic" not in title.lower(), "insight_summary should not be generic"
    assert "Create third-party-referenceable proof assets for recurring AI answer gaps" not in title, "Should not use the old generic title"
    print(f"  \u2713 Pack title is insight-led, not generic")


def test_attach_to_bundle():
    bundle = {
        "brand": "Nissan",
        "grouped_pr_opportunities": [_sample_pr_opp(), _sample_pr_opp("authority_body", 3)],
    }
    result = attach_advanced_pr_asset_packs_to_bundle(bundle, brand="Nissan")
    for opp in result["grouped_pr_opportunities"]:
        pack = opp.get("advanced_pr_asset_pack")
        assert pack is not None, "Each opportunity should have an advanced_pr_asset_pack"
        assert pack.get("insight_summary"), "Pack should have insight_summary"
        assert pack.get("publisher_groups"), "Pack should have publisher_groups"
    print(f"  \u2713 attach_advanced_pr_asset_packs_to_bundle works for {len(result['grouped_pr_opportunities'])} opportunities")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("PR & Brand Suggestions Quality Improvement Tests")
    print("=" * 60)

    tests = [
        test_insight_summary_generated,
        test_recommended_pr_action_generated,
        test_core_claim_generated,
        test_asset_concept_is_sharp,
        test_publishable_assets_generated,
        test_publisher_groups_by_role,
        test_semantic_trigger_groups,
        test_measurement_plan,
        test_legal_review_items,
        test_full_pack_has_all_new_fields,
        test_pack_no_generic_title,
        test_attach_to_bundle,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  \u2717 {test.__name__}: {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed out of {len(tests)} tests")
    sys.exit(1 if failed else 0)
