"""Tests for Advanced GEO/AEO Recommendation Generator.

Covers:
- Epic 1: Contract & Schema validation
- Epic 2: Fact Matrix extraction
- Epic 3: CMS Asset Generation
- Epic 4: PR Asset Pack Generation
- Epic 5: Storage pass-through
- Acceptance criteria enforcement
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# Add scripts dir to path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from advanced_geo_contracts import (
    make_fact_entry,
    make_advanced_geo_asset,
    make_advanced_pr_asset_pack,
    validate_fact_snippet_contains_claim,
    validate_direct_answer_word_count,
    validate_html_component,
    validate_json_ld_script,
    validate_advanced_geo_asset,
    validate_advanced_pr_asset_pack,
    ADVANCED_GEO_ASSET_SCHEMA_VERSION,
    ADVANCED_PR_ASSET_PACK_SCHEMA_VERSION,
)
from fact_matrix import (
    extract_json_ld_facts,
    extract_visible_numeric_facts,
    extract_crawl_metadata_facts,
    extract_fact_matrix_for_owned_url,
    build_fact_matrices_for_bundle,
)
from advanced_cms_generator import (
    build_advanced_geo_asset,
    attach_advanced_geo_assets_to_bundle,
)
from advanced_pr_generator import (
    build_advanced_pr_asset_pack,
    attach_advanced_pr_asset_packs_to_bundle,
)


class TestFactEntry(unittest.TestCase):
    def test_make_fact_entry_basic(self):
        fact = make_fact_entry("cargo_volume", value="466", unit="L", source="existing_json_ld", source_context_snippet='"cargoVolume":"466 L"')
        self.assertEqual(fact["fact"], "cargo_volume")
        self.assertEqual(fact["value"], "466")
        self.assertEqual(fact["unit"], "L")
        self.assertEqual(fact["source"], "existing_json_ld")

    def test_make_fact_entry_no_value(self):
        fact = make_fact_entry("page_title", source="crawl_metadata", source_context_snippet='title: "Test"')
        self.assertNotIn("value", fact)
        self.assertNotIn("unit", fact)


class TestFactSnippetValidation(unittest.TestCase):
    def test_good_snippet(self):
        fact = {"fact": "cargo_volume", "value": "466", "unit": "L", "source_context_snippet": '"cargoVolume":"466 L"'}
        self.assertTrue(validate_fact_snippet_contains_claim(fact))

    def test_bad_snippet(self):
        fact = {"fact": "cargo_volume", "value": "466", "unit": "L", "source_context_snippet": '"price":"6675900.0","width":"1850"'}
        self.assertFalse(validate_fact_snippet_contains_claim(fact))

    def test_empty_snippet(self):
        fact = {"fact": "test", "value": "100", "source_context_snippet": ""}
        self.assertFalse(validate_fact_snippet_contains_claim(fact))

    def test_no_value_but_fact_name_present(self):
        fact = {"fact": "warranty", "source_context_snippet": "warranty coverage for 5 years"}
        self.assertTrue(validate_fact_snippet_contains_claim(fact))


class TestDirectAnswerWordCount(unittest.TestCase):
    def test_under_40(self):
        self.assertTrue(validate_direct_answer_word_count("This is a short answer."))

    def test_exactly_40(self):
        text = " ".join(["word"] * 40)
        self.assertTrue(validate_direct_answer_word_count(text))

    def test_over_40(self):
        text = " ".join(["word"] * 41)
        self.assertFalse(validate_direct_answer_word_count(text))


class TestHtmlComponentValidation(unittest.TestCase):
    def test_valid_html(self):
        html = '<section class="geo-lead-answer"><h2>Test</h2><p>Content</p></section>'
        self.assertEqual(validate_html_component(html), [])

    def test_missing_class(self):
        html = '<section><h2>Test</h2></section>'
        issues = validate_html_component(html)
        self.assertTrue(any('geo-lead-answer' in i for i in issues))

    def test_empty_html(self):
        issues = validate_html_component("")
        self.assertTrue(any('empty' in i for i in issues))


class TestJsonLdValidation(unittest.TestCase):
    def test_valid_json_ld(self):
        script = json.dumps({"@context": "https://schema.org", "@type": "Product"})
        self.assertEqual(validate_json_ld_script(script), [])

    def test_invalid_json(self):
        issues = validate_json_ld_script("{not valid json}")
        self.assertTrue(any('not valid JSON' in i for i in issues))

    def test_empty_is_ok(self):
        self.assertEqual(validate_json_ld_script(""), [])


class TestAdvancedGeoAssetValidation(unittest.TestCase):
    def test_valid_asset(self):
        asset = make_advanced_geo_asset(
            expected_impact_score_10=7,
            direct_answer_40_words="This is a short answer.",
            html_component='<section class="geo-lead-answer"><p>Test</p></section>',
            json_ld_script=json.dumps({"@context": "https://schema.org", "@type": "WebPage"}),
            facts_used=[make_fact_entry("test", value="100", source="owned_page", source_context_snippet="test 100 units")],
        )
        issues = validate_advanced_geo_asset(asset)
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_no_invented_facts(self):
        """AC: No numeric claim appears unless listed in facts_used."""
        asset = make_advanced_geo_asset(
            facts_used=[{"fact": "price", "value": "999", "source": "owned_page", "source_context_snippet": "wrong snippet"}],
        )
        issues = validate_advanced_geo_asset(asset)
        self.assertTrue(any('snippet does not contain' in i for i in issues))


class TestAdvancedPrAssetPackValidation(unittest.TestCase):
    def test_valid_pack(self):
        pack = make_advanced_pr_asset_pack(
            asset_name="Test Pack",
            asset_type="data_study",
            information_gain_trigger="New data",
            target_publisher_types=["automotive_review_sites"],
            semantic_triggers=["comparison"],
        )
        issues = validate_advanced_pr_asset_pack(pack)
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_missing_fields(self):
        pack = make_advanced_pr_asset_pack()
        issues = validate_advanced_pr_asset_pack(pack)
        self.assertTrue(len(issues) > 0)


class TestFactMatrixExtraction(unittest.TestCase):
    def test_extract_json_ld_facts(self):
        page = {
            "url": "https://example.com/product",
            "json_ld_content": [{"@context": "https://schema.org", "@type": "Product", "name": "Test", "weight": "1500 kg", "price": "35000"}],
        }
        facts = extract_json_ld_facts(page)
        self.assertTrue(len(facts) > 0)
        self.assertTrue(any(f["source"] == "existing_json_ld" for f in facts))

    def test_extract_visible_numeric_facts(self):
        text = "The vehicle has a range of 450 km and weighs 1800 kg. Battery capacity is 75 kWh. Price starts at 5000000 yen."
        facts = extract_visible_numeric_facts(text, source_url="https://example.com")
        self.assertTrue(len(facts) >= 3)
        values = [f["value"] for f in facts]
        self.assertTrue(any("450" in v for v in values))

    def test_extract_crawl_metadata_facts(self):
        page = {"url": "https://example.com", "title": "Test Page", "meta_description": "A test page", "schema_types": ["Product", "WebPage"]}
        facts = extract_crawl_metadata_facts(page)
        self.assertTrue(any(f["fact"] == "page_title" for f in facts))
        self.assertTrue(any(f["fact"] == "schema_types" for f in facts))

    def test_full_fact_matrix(self):
        page = {
            "url": "https://example.com/product",
            "title": "Test Product",
            "markdown": "This product weighs 1500 kg and costs 3500000 yen. Range is 400 km.",
            "json_ld_content": [{"@type": "Product", "weight": "1500 kg"}],
            "schema_types": ["Product"],
        }
        matrix = extract_fact_matrix_for_owned_url(page)
        self.assertEqual(matrix["url"], "https://example.com/product")
        self.assertTrue(matrix["facts_count"] > 0)
        self.assertTrue(len(matrix["validated_facts"]) > 0)


class TestCmsAssetGeneration(unittest.TestCase):
    def test_build_advanced_geo_asset(self):
        cms_rec = {
            "target_url": "https://example.com/product",
            "page_title": "Test Product",
            "module_type": "answer_first_summary_plus_faq",
            "query_coverage_count": 5,
            "current_geo_score_120": 60,
            "linked_queries": [{"query_id": "q1", "query": "best product 2025"}],
            "geo_gaps_addressed": ["content_clarity", "faq_readiness"],
        }
        matrix = {
            "url": "https://example.com/product",
            "title": "Test Product",
            "facts_count": 3,
            "validated_facts": [
                make_fact_entry("weight", value="1500", unit="kg", source="owned_page", source_context_snippet="weighs 1500 kg"),
                make_fact_entry("price", value="35000", unit="USD", source="owned_page", source_context_snippet="price 35000 USD"),
            ],
            "validation_flags": [],
            "has_json_ld": True,
            "has_crawl_text": True,
            "crawl_text_length": 5000,
            "schema_types": ["Product"],
            "json_ld_present": True,
            "json_ld_facts_count": 1,
            "visible_facts_count": 2,
            "metadata_facts_count": 0,
        }
        asset = build_advanced_geo_asset(cms_rec, matrix, brand="TestBrand")
        self.assertEqual(asset["schema_version"], "advanced_geo_asset.v1")
        self.assertTrue(asset["expected_impact_score_10"] > 0)
        self.assertTrue('geo-lead-answer' in asset["html_component"])
        self.assertTrue(len(asset["facts_used"]) > 0)


class TestPrAssetPackGeneration(unittest.TestCase):
    def test_build_pr_asset_pack(self):
        pr_opp = {
            "source_type": "publisher_review",
            "opportunity_type": "publisher_and_comparison_coverage",
            "query_coverage_count": 8,
            "grouped_queries": [
                {"query_id": "q1", "query": "best electric SUV 2025"},
                {"query_id": "q2", "query": "EV range comparison"},
            ],
            "observed_external_domains": [
                {"domain": "carwow.co.uk", "count": 5},
                {"domain": "autoexpress.co.uk", "count": 3},
            ],
        }
        pack = build_advanced_pr_asset_pack(pr_opp, brand="TestBrand")
        self.assertEqual(pack["schema_version"], "advanced_pr_asset_pack.v1")
        self.assertTrue(pack["asset_name"])
        self.assertTrue(pack["information_gain_trigger"])
        self.assertTrue(len(pack["target_publisher_types"]) > 0)
        self.assertTrue(len(pack["semantic_triggers"]) > 0)


class TestBundleAttachment(unittest.TestCase):
    def test_attach_to_bundle_preserves_existing(self):
        """AC: CMS recommendations still render without advanced_geo_asset."""
        bundle = {
            "brand": "Test",
            "page_level_cms_recommendations": [
                {"target_url": "https://example.com/page1", "title": "Test CMS", "priority": "High"},
            ],
            "grouped_pr_opportunities": [
                {"source_type": "publisher_review", "title": "Test PR", "query_coverage_count": 3, "grouped_queries": [{"query_id": "q1", "query": "test"}], "observed_external_domains": [{"domain": "test.com"}]},
            ],
        }
        attach_advanced_geo_assets_to_bundle(bundle, owned_pages=[], brand="Test")
        attach_advanced_pr_asset_packs_to_bundle(bundle, brand="Test")
        self.assertIn("advanced_geo_asset", bundle["page_level_cms_recommendations"][0])
        self.assertIn("advanced_pr_asset_pack", bundle["grouped_pr_opportunities"][0])
        self.assertEqual(bundle["page_level_cms_recommendations"][0]["title"], "Test CMS")

    def test_backward_compatibility(self):
        """AC: Existing reports continue to parse and render."""
        bundle = {
            "brand": "Test",
            "page_level_cms_recommendations": [{"target_url": "https://example.com", "title": "Old CMS"}],
            "grouped_pr_opportunities": [],
        }
        # Should not crash even with empty data.
        attach_advanced_geo_assets_to_bundle(bundle, owned_pages=[], brand="Test")
        attach_advanced_pr_asset_packs_to_bundle(bundle, brand="Test")
        self.assertEqual(bundle["page_level_cms_recommendations"][0]["title"], "Old CMS")


if __name__ == "__main__":
    unittest.main()
