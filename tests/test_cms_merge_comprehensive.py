#!/usr/bin/env python3
"""Comprehensive tests for CMS content module merge into page_level_cms_recommendations.

Covers:
- Matching by source_recommendation_id
- Matching by normalised URL (strip protocol, www, trailing slash)
- Matching by overlapping linked_query_ids
- Overwriting ALL weak deterministic fields with LLM values
- Creating frontend-facing copy_modules from flat fields
- cms_merge_status validation guardrail
- Unmerged module tracking
"""
from __future__ import annotations
import sys
import os

# Add scripts dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from build_query_workbench_bundle import _merge_cms_content_modules, _normalise_merge_url


def test_normalise_merge_url():
    """Test URL normalisation strips protocol, www, trailing slash."""
    assert _normalise_merge_url("https://www3.nissan.co.jp/vehicles/new/ariya.html") == "www3.nissan.co.jp/vehicles/new/ariya.html"
    assert _normalise_merge_url("https://www.nissan.co.jp/vehicles/") == "nissan.co.jp/vehicles"
    assert _normalise_merge_url("http://www.nissan.co.jp/vehicles") == "nissan.co.jp/vehicles"
    assert _normalise_merge_url("nissan.co.jp/vehicles/") == "nissan.co.jp/vehicles"
    assert _normalise_merge_url("") == ""
    assert _normalise_merge_url(None) == ""
    print("  \u2713 URL normalisation works correctly")


def test_match_by_recommendation_id():
    """Test matching by source_recommendation_id === recommendation_id."""
    page_cms = [
        {"recommendation_id": "pagecms_53a36612cc", "target_url": "https://www3.nissan.co.jp/vehicles/new/ariya.html", "direct_answer": None, "faq_items": None},
    ]
    content_modules = [
        {"source_recommendation_id": "pagecms_53a36612cc", "target_owned_url": "https://www3.nissan.co.jp/vehicles/new/ariya.html", "direct_answer": "The Nissan Ariya offers...", "faq_items": [{"question": "Q1", "answer": "A1"}]},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["direct_answer"] == "The Nissan Ariya offers...", f"Expected LLM direct_answer, got: {page_cms[0]['direct_answer']}"
    assert len(page_cms[0]["faq_items"]) == 1
    assert page_cms[0]["cms_llm_merged"] is True
    assert status["merged_into_page_recommendations"] == 1
    assert status["unmerged_module_ids"] == []
    print("  \u2713 Match by recommendation_id works")


def test_match_by_normalised_url():
    """Test matching by normalised URL (strips protocol, www, trailing slash)."""
    page_cms = [
        {"recommendation_id": "pagecms_abc123", "target_url": "https://www3.nissan.co.jp/vehicles/new/ariya.html", "direct_answer": None},
    ]
    content_modules = [
        {"source_recommendation_id": "different_id", "target_owned_url": "https://www3.nissan.co.jp/vehicles/new/ariya.html", "direct_answer": "LLM answer here"},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["direct_answer"] == "LLM answer here"
    assert status["merged_into_page_recommendations"] == 1
    print("  \u2713 Match by normalised URL works")


def test_match_by_normalised_url_with_www_stripping():
    """Test URL matching strips www. prefix."""
    page_cms = [
        {"recommendation_id": "pagecms_xyz", "target_url": "https://www.nissan.co.jp/vehicles/", "direct_answer": None},
    ]
    content_modules = [
        {"source_recommendation_id": "no_match", "target_owned_url": "http://nissan.co.jp/vehicles", "direct_answer": "LLM answer"},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["direct_answer"] == "LLM answer"
    assert status["merged_into_page_recommendations"] == 1
    print("  \u2713 URL matching with www stripping works")


def test_match_by_linked_query_ids():
    """Test matching by overlapping linked_query_ids."""
    page_cms = [
        {"recommendation_id": "pagecms_no_url", "target_url": "", "linked_queries": [{"query_id": "q001"}, {"query_id": "q002"}], "direct_answer": None},
    ]
    content_modules = [
        {"source_recommendation_id": "no_match", "target_owned_url": "", "linked_query_ids": ["q002", "q003"], "direct_answer": "LLM via query match"},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["direct_answer"] == "LLM via query match"
    assert status["merged_into_page_recommendations"] == 1
    print("  \u2713 Match by linked_query_ids works")


def test_match_priority_rec_id_first():
    """Test that rec_id match takes priority over URL match."""
    page_cms = [
        {"recommendation_id": "pagecms_target", "target_url": "https://nissan.co.jp/page1", "direct_answer": None},
        {"recommendation_id": "pagecms_other", "target_url": "https://nissan.co.jp/page2", "direct_answer": None},
    ]
    content_modules = [
        {"source_recommendation_id": "pagecms_target", "target_owned_url": "https://nissan.co.jp/page2", "direct_answer": "Should go to rec_id match"},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["direct_answer"] == "Should go to rec_id match", "rec_id should take priority over URL"
    assert page_cms[1]["direct_answer"] is None, "URL match should NOT be used when rec_id matches"
    print("  \u2713 Match priority: rec_id > URL works")


def test_overwrite_all_weak_fields():
    """Test that ALL weak deterministic fields are overwritten by LLM values."""
    page_cms = [
        {
            "recommendation_id": "pagecms_test",
            "target_url": "https://nissan.co.jp/test",
            "direct_answer": "[Direct answer pending]",
            "faq_items": [],
            "facts_used": [],
            "facts_missing": ["existing_fact"],
            "json_ld_tags": [],
            "intent_tags": [],
            "recommended_placement": None,
            "heading": None,
            "intro_copy": None,
            "body_copy": None,
            "bullets": [],
            "evidence_basis": None,
            "validation_required": [],
        },
    ]
    content_modules = [
        {
            "source_recommendation_id": "pagecms_test",
            "direct_answer": "Real LLM answer",
            "faq_items": [{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}, {"question": "Q3", "answer": "A3"}],
            "facts_used": [{"fact": "range", "value": "470", "unit": "km", "source": "owned_page"}],
            "facts_missing": ["new_missing_fact"],
            "json_ld_tags": [{"@type": "FAQPage"}],
            "intent_tags": ["ev_range", "daily_commuting"],
            "recommended_placement": "Above hero section",
            "heading": "LLM Heading",
            "intro_copy": "LLM intro",
            "body_copy": "LLM body",
            "bullets": ["Bullet 1", "Bullet 2"],
            "evidence_basis": "Based on owned page crawl data",
            "validation_required": ["Product", "Legal"],
        },
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    rec = page_cms[0]
    assert rec["direct_answer"] == "Real LLM answer", f"direct_answer not overwritten: {rec['direct_answer']}"
    assert len(rec["faq_items"]) == 3, f"faq_items not overwritten: {rec['faq_items']}"
    assert len(rec["facts_used"]) == 1, f"facts_used not overwritten: {rec['facts_used']}"
    assert "existing_fact" in rec["facts_missing"], "existing facts_missing should be preserved"
    assert "new_missing_fact" in rec["facts_missing"], "new facts_missing should be added"
    assert len(rec["json_ld_tags"]) == 1
    assert len(rec["intent_tags"]) == 2
    assert rec["recommended_placement"] == "Above hero section"
    assert rec["heading"] == "LLM Heading"
    assert rec["intro_copy"] == "LLM intro"
    assert rec["body_copy"] == "LLM body"
    assert len(rec["bullets"]) == 2
    assert rec["evidence_basis"] == "Based on owned page crawl data"
    assert len(rec["validation_required"]) == 2
    print("  \u2713 All weak deterministic fields overwritten by LLM values")


def test_copy_modules_created_from_flat_fields():
    """Test that copy_modules are created from heading/intro_copy/body_copy/bullets."""
    page_cms = [
        {"recommendation_id": "pagecms_copy", "target_url": "https://nissan.co.jp/copy", "direct_answer": None},
    ]
    content_modules = [
        {
            "source_recommendation_id": "pagecms_copy",
            "heading": "Test Heading",
            "intro_copy": "Test intro",
            "body_copy": "Test body",
            "bullets": ["B1", "B2"],
            "faq_items": [{"question": "Q", "answer": "A"}],
        },
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    rec = page_cms[0]
    assert "copy_modules" in rec, "copy_modules should be created"
    assert len(rec["copy_modules"]) == 1
    cm = rec["copy_modules"][0]
    assert cm["heading"] == "Test Heading"
    assert cm["intro_copy"] == "Test intro"
    assert cm["body_copy"] == "Test body"
    assert cm["bullets"] == ["B1", "B2"]
    assert len(cm["faq_items"]) == 1
    assert "module_id" in cm
    print("  \u2713 copy_modules created from flat fields")


def test_existing_copy_modules_preserved():
    """Test that existing copy_modules from LLM are preserved as-is."""
    page_cms = [
        {"recommendation_id": "pagecms_existing", "target_url": "https://nissan.co.jp/existing"},
    ]
    existing_cm = [{"module_id": "m1", "heading": "Existing", "intro_copy": "Existing intro", "body_copy": "", "bullets": [], "faq_items": []}]
    content_modules = [
        {"source_recommendation_id": "pagecms_existing", "copy_modules": existing_cm},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["copy_modules"] == existing_cm
    print("  \u2713 Existing copy_modules preserved")


def test_unmerged_modules_tracked():
    """Test that unmerged modules are tracked in cms_merge_status."""
    page_cms = [
        {"recommendation_id": "pagecms_only", "target_url": "https://nissan.co.jp/only"},
    ]
    content_modules = [
        {"source_recommendation_id": "pagecms_only", "direct_answer": "Merged"},
        {"source_recommendation_id": "pagecms_orphan", "target_owned_url": "https://unknown.com/page", "direct_answer": "Orphan"},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert status["cms_ready_modules"] == 2
    assert status["merged_into_page_recommendations"] == 1
    assert len(status["unmerged_module_ids"]) == 1
    assert "pagecms_orphan" in status["unmerged_module_ids"]
    print("  \u2713 Unmerged modules tracked in cms_merge_status")


def test_empty_llm_values_not_overwritten():
    """Test that empty/None LLM values don't overwrite existing values."""
    page_cms = [
        {"recommendation_id": "pagecms_keep", "target_url": "https://nissan.co.jp/keep", "direct_answer": "Existing answer", "heading": "Existing heading"},
    ]
    content_modules = [
        {"source_recommendation_id": "pagecms_keep", "direct_answer": "", "heading": None, "faq_items": []},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["direct_answer"] == "Existing answer", "Empty string should not overwrite"
    assert page_cms[0]["heading"] == "Existing heading", "None should not overwrite"
    print("  \u2713 Empty/None LLM values don't overwrite existing values")


def test_cms_llm_merged_flag():
    """Test that cms_llm_merged flag is set on merged recommendations."""
    page_cms = [
        {"recommendation_id": "pagecms_flag", "target_url": "https://nissan.co.jp/flag"},
    ]
    content_modules = [
        {"source_recommendation_id": "pagecms_flag", "direct_answer": "Test"},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["cms_llm_merged"] is True
    print("  \u2713 cms_llm_merged flag set correctly")


def test_primary_query_metadata_merged():
    """Test that primary_query_id and primary_query_text are merged."""
    page_cms = [
        {"recommendation_id": "pagecms_pq", "target_url": "https://nissan.co.jp/pq"},
    ]
    content_modules = [
        {"source_recommendation_id": "pagecms_pq", "primary_query_id": "q001", "primary_query_text": "best electric SUV"},
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    assert page_cms[0]["primary_query_id"] == "q001"
    assert page_cms[0]["primary_query_text"] == "best electric SUV"
    print("  \u2713 Primary query metadata merged")


def test_real_world_scenario():
    """Test the exact scenario from the bug report: 16 CMS modules, 25 page recs."""
    page_cms = [
        {"recommendation_id": f"pagecms_{i:02d}", "target_url": f"https://www3.nissan.co.jp/page{i}", "direct_answer": None, "faq_items": None, "json_ld_tags": None, "intent_tags": None}
        for i in range(25)
    ]
    content_modules = [
        {"source_recommendation_id": f"pagecms_{i:02d}", "target_owned_url": f"https://www3.nissan.co.jp/page{i}", "direct_answer": f"Answer for page {i}", "faq_items": [{"question": f"Q{i}", "answer": f"A{i}"}], "json_ld_tags": [{"@type": "FAQPage"}], "intent_tags": [f"intent_{i}"]}
        for i in range(16)
    ]
    status = _merge_cms_content_modules(page_cms, content_modules)
    
    # Verify all 16 modules merged
    assert status["cms_ready_modules"] == 16
    assert status["merged_into_page_recommendations"] == 16
    assert status["unmerged_module_ids"] == []
    
    # Verify first 16 pages have LLM content
    for i in range(16):
        assert page_cms[i]["direct_answer"] == f"Answer for page {i}", f"Page {i} direct_answer not merged"
        assert page_cms[i]["faq_items"] is not None and len(page_cms[i]["faq_items"]) == 1
        assert page_cms[i]["json_ld_tags"] is not None and len(page_cms[i]["json_ld_tags"]) == 1
        assert page_cms[i]["intent_tags"] is not None and len(page_cms[i]["intent_tags"]) == 1
        assert page_cms[i]["cms_llm_merged"] is True
    
    # Verify remaining 9 pages still have null
    for i in range(16, 25):
        assert page_cms[i]["direct_answer"] is None, f"Page {i} should still be None"
        assert page_cms[i].get("cms_llm_merged") is not True
    
    print(f"  \u2713 Real-world scenario: {status['merged_into_page_recommendations']}/16 modules merged into 25 page recs")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("CMS Content Module Merge — Comprehensive Tests")
    print("=" * 60)
    
    tests = [
        test_normalise_merge_url,
        test_match_by_recommendation_id,
        test_match_by_normalised_url,
        test_match_by_normalised_url_with_www_stripping,
        test_match_by_linked_query_ids,
        test_match_priority_rec_id_first,
        test_overwrite_all_weak_fields,
        test_copy_modules_created_from_flat_fields,
        test_existing_copy_modules_preserved,
        test_unmerged_modules_tracked,
        test_empty_llm_values_not_overwritten,
        test_cms_llm_merged_flag,
        test_primary_query_metadata_merged,
        test_real_world_scenario,
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
