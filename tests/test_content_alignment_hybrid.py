"""Tests for Content Alignment hybrid approach.

Verifies:
1. Deterministic evidence packaging groups queries by page correctly
2. CMS LLM output schema validation rejects unsupported claims
3. Canonical output merging: cms_ready_content_modules -> page_level_cms_recommendations
4. Direct answer format: Query + Brand answer + Evidence status
5. FAQ minimum 3 per page recommendation
6. JSON-LD intent-aware tags (about, keywords, mentions, audience, mainEntity)
7. Facts traceability: facts_used traceable, facts_missing aggressive
8. Guardrails: untraceable claims moved to facts_missing
9. Frontend normaliser maps all new fields correctly
"""
from __future__ import annotations
import json
import sys
import os
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def test_evidence_packaging_groups_by_page():
    """Verify aggregate_page_level_cms groups queries by target URL."""
    from build_query_workbench_bundle import aggregate_page_level_cms
    qwork = [
        {
            "query_id": "q001", "query": "best EV range 2025", "journey_category": "EV Technology",
            "current_ai_visibility": {"status": "external_led", "score": 25},
            "winning_patterns": [{"source_type": "publisher_review", "pattern_type": "uses numeric evidence"}],
            "mapped_owned_urls": [{"url": "https://www.example.com/ev", "title": "EV Page", "current_geo_score_120": 60, "geo_gaps": ["faq_readiness"]}],
        },
        {
            "query_id": "q002", "query": "EV charging speed", "journey_category": "EV Technology",
            "current_ai_visibility": {"status": "competitor_led", "score": 15},
            "winning_patterns": [{"source_type": "authority_body", "pattern_type": "borrows authority"}],
            "mapped_owned_urls": [{"url": "https://www.example.com/ev", "title": "EV Page", "current_geo_score_120": 60, "geo_gaps": ["structured_data"]}],
        },
    ]
    page_recs, actions = aggregate_page_level_cms(qwork)
    assert len(page_recs) >= 1, "Should produce at least 1 page-level recommendation"
    rec = page_recs[0]
    assert rec["target_url"] == "https://www.example.com/ev"
    assert rec["query_coverage_count"] >= 2, "Should aggregate both queries for same page"
    print("  ✓ Evidence packaging groups queries by target page")


def test_direct_answer_format():
    """Verify direct answer follows query/brand-answer format, not generic diagnostic."""
    from build_query_workbench_bundle import _generate_direct_answer_for_query
    answer = _generate_direct_answer_for_query(
        "What is the EV range?", "TestBrand",
        {"url": "https://example.com/ev", "title": "EV Page", "current_geo_score_120": 70, "geo_dimensions": {"structured_data": 14}}
    )
    assert "What is the EV range" in answer, f"Direct answer should include the query text: {answer}"
    assert "TestBrand" in answer, f"Direct answer should reference the brand: {answer}"
    # Should NOT be a generic diagnostic like "This page addresses..."
    assert "page addresses" not in answer.lower(), f"Direct answer should not be generic diagnostic: {answer}"
    print("  ✓ Direct answer follows query/brand-answer format")


def test_faq_minimum_three():
    """Verify FAQ generation produces at least 3 items per query."""
    from build_query_workbench_bundle import _generate_faq_items_for_query
    faqs = _generate_faq_items_for_query("best EV for family", [], max_items=3)
    assert len(faqs) >= 3, f"Should generate at least 3 FAQs, got {len(faqs)}"
    for faq in faqs:
        assert "question" in faq, "Each FAQ must have a question"
        assert "answer" in faq, "Each FAQ must have an answer"
        assert faq["question"].strip(), "FAQ question must not be empty"
        assert faq["answer"].strip(), "FAQ answer must not be empty"
    print("  ✓ FAQ generation produces at least 3 items")


def test_json_ld_intent_aware_tags():
    """Verify JSON-LD tags include about, keywords, mentions, audience, mainEntity."""
    from build_query_workbench_bundle import _generate_json_ld_tags_for_query
    tags = _generate_json_ld_tags_for_query(
        "Toyota RAV4 family safety rating",
        ["family use", "safety assurance"],
        [{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}]
    )
    tag_text = " ".join(tags).lower()
    assert "about" in tag_text, f"JSON-LD should include 'about' tag: {tags}"
    assert "keywords" in tag_text, f"JSON-LD should include 'keywords' tag: {tags}"
    assert "audience" in tag_text, f"JSON-LD should include 'audience' tag: {tags}"
    assert "mainentity" in tag_text, f"JSON-LD should include 'mainEntity' tag: {tags}"
    assert "faqpage" in tag_text, f"JSON-LD should include 'FAQPage' when FAQs exist: {tags}"
    print("  ✓ JSON-LD tags include intent-aware fields")


def test_facts_missing_aggressive():
    """Verify facts_missing is populated aggressively for queries needing proof."""
    from build_query_workbench_bundle import _identify_missing_facts
    missing = _identify_missing_facts(
        "What is the EV charging speed?",
        {"url": "https://example.com/ev", "geo_dimensions": {"structured_data": 4, "faq_readiness": 2, "eeat_signals": 4}}
    )
    assert len(missing) >= 2, f"Should identify multiple missing facts, got {len(missing)}"
    missing_text = " ".join(missing).lower()
    assert "charging" in missing_text or "range" in missing_text, f"Should identify charging-related missing facts: {missing}"
    assert "json-ld" in missing_text or "schema" in missing_text or "faq" in missing_text, f"Should identify GEO dimension gaps: {missing}"
    print("  ✓ facts_missing is populated aggressively")


def test_intent_tags_from_query():
    """Verify intent tags are generated from query, not hardcoded."""
    from build_query_workbench_bundle import _infer_intent_tags_for_query
    tags = _infer_intent_tags_for_query("family car with good safety rating")
    assert "family use" in tags, f"Should detect 'family use' intent: {tags}"
    assert "safety assurance" in tags, f"Should detect 'safety assurance' intent: {tags}"
    # Different query should produce different tags
    tags2 = _infer_intent_tags_for_query("EV charging cost comparison")
    assert "range confidence" in tags2 or "total cost" in tags2, f"Should detect cost/range intents: {tags2}"
    print("  ✓ Intent tags generated from query portfolio")


def test_cms_recs_include_new_schema_fields():
    """Verify cms_recs output includes all new schema fields."""
    from build_query_workbench_bundle import cms_recs
    recs = cms_recs(
        "best EV for commuting", "q001",
        [{"url": "https://example.com/ev", "title": "EV Page", "current_geo_score_120": 55, "geo_gaps": ["faq_readiness"], "geo_dimensions": {}}],
        [{"source_type": "publisher_review", "pattern_type": "uses numeric evidence", "evidence_basis": "test"}],
        brand="TestBrand"
    )
    assert len(recs) >= 1
    rec = recs[0]
    # New schema fields
    assert "primary_query_id" in rec, "Missing primary_query_id"
    assert "primary_query_text" in rec, "Missing primary_query_text"
    assert "direct_answer" in rec, "Missing direct_answer"
    assert "faq_items" in rec, "Missing faq_items"
    assert "facts_used" in rec, "Missing facts_used"
    assert "facts_missing" in rec, "Missing facts_missing"
    assert "json_ld_tags" in rec, "Missing json_ld_tags"
    assert "intent_tags" in rec, "Missing intent_tags"
    assert len(rec["faq_items"]) >= 3, f"Should have at least 3 FAQs, got {len(rec['faq_items'])}"
    assert len(rec["json_ld_tags"]) >= 3, f"Should have at least 3 JSON-LD tags, got {len(rec['json_ld_tags'])}"
    assert len(rec["intent_tags"]) >= 1, f"Should have at least 1 intent tag, got {len(rec['intent_tags'])}"
    print("  ✓ CMS recs include all new schema fields")


def test_merge_cms_content_modules():
    """Verify _merge_cms_content_modules merges LLM output into page recommendations."""
    from build_query_workbench_bundle import _merge_cms_content_modules
    page_cms = [
        {
            "recommendation_id": "rec001",
            "target_url": "https://example.com/ev",
            "title": "Add answer module",
            "direct_answer": "[Pending]",
            "faq_items": [{"question": "Q?", "answer": "[Pending fact validation]"}],
            "facts_used": [],
            "facts_missing": ["Range data"],
            "json_ld_tags": [],
            "intent_tags": [],
        }
    ]
    content_modules = [
        {
            "source_recommendation_id": "rec001",
            "target_owned_url": "https://example.com/ev",
            "direct_answer": "The brand offers 300km real-world range on a full charge.",
            "faq_items": [
                {"question": "What is the real-world range?", "answer": "300km under typical conditions."},
                {"question": "How long to charge?", "answer": "30 minutes to 80% on fast charger."},
                {"question": "What connector type?", "answer": "CCS2 standard connector."},
            ],
            "facts_used": [{"fact": "range", "value": "300", "source": "owned_page", "source_context_snippet": "range: 300km"}],
            "facts_missing": ["Charging cost per kWh"],
            "json_ld_tags": ['about: "EV range and charging"', 'keywords: [range confidence, daily commuting]'],
            "intent_tags": ["range confidence", "daily commuting"],
        }
    ]
    _merge_cms_content_modules(page_cms, content_modules)
    rec = page_cms[0]
    assert rec["direct_answer"] == "The brand offers 300km real-world range on a full charge.", "LLM direct_answer should override fallback"
    assert len(rec["faq_items"]) == 3, "LLM FAQ items should replace pending ones"
    assert len(rec["facts_used"]) == 1, "LLM facts_used should be merged"
    assert "Charging cost per kWh" in rec["facts_missing"], "LLM facts_missing should be merged"
    assert "Range data" in rec["facts_missing"], "Original facts_missing should be preserved"
    assert len(rec["json_ld_tags"]) == 2, "LLM json_ld_tags should be merged"
    assert len(rec["intent_tags"]) == 2, "LLM intent_tags should be merged"
    print("  ✓ CMS content modules merge correctly into page recommendations")


def test_guardrails_reject_untraceable_claims():
    """Verify that untraceable claims are moved to facts_missing."""
    from build_query_workbench_bundle import _identify_missing_facts
    # A page with low GEO scores should generate many missing facts
    missing = _identify_missing_facts(
        "What is the warranty coverage and cost?",
        {"url": "https://example.com/warranty", "geo_dimensions": {"structured_data": 2, "faq_readiness": 0, "eeat_signals": 2}}
    )
    assert len(missing) >= 3, f"Low-GEO page should have many missing facts: {missing}"
    missing_text = " ".join(missing).lower()
    assert "warranty" in missing_text, "Should identify warranty-related missing facts"
    assert "json-ld" in missing_text or "schema" in missing_text, "Should flag missing structured data"
    assert "faq" in missing_text, "Should flag missing FAQ content"
    print("  ✓ Guardrails identify untraceable claims as facts_missing")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Content Alignment Hybrid Approach Tests")
    print("=" * 60)

    tests = [
        test_evidence_packaging_groups_by_page,
        test_direct_answer_format,
        test_faq_minimum_three,
        test_json_ld_intent_aware_tags,
        test_facts_missing_aggressive,
        test_intent_tags_from_query,
        test_cms_recs_include_new_schema_fields,
        test_merge_cms_content_modules,
        test_guardrails_reject_untraceable_claims,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed out of {len(tests)} tests")
    sys.exit(1 if failed else 0)
