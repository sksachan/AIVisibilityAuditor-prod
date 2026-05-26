"""Tests for build_competitor_visibility_matrix.py.

Covers:
- Non-branded query extraction
- Competitor detection using configurable dictionary
- Weighted citation score computation
- Source type influence percentage calculation
- AI visibility score computation (0-100 range)
- Edge cases: empty data, missing fields, no competitors
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Add scripts directory to path
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from build_competitor_visibility_matrix import (
    build_competitor_visibility_matrix,
    is_non_branded_query,
    default_brand_exclusion_terms,
    default_competitor_dictionary,
    classify_source_type,
    rank_weight,
    compute_framing_score,
    _extract_domain,
    _detect_competitors_in_citation,
    _allocate_citation_credit,
)


class TestNonBrandedQueryFiltering(unittest.TestCase):
    """Test non-branded query identification."""

    def test_explicit_non_branded_type(self):
        row = {"query": "best electric SUV 2025", "query_type": "non_branded"}
        self.assertTrue(is_non_branded_query(row, "Nissan", default_brand_exclusion_terms("Nissan")))

    def test_explicit_branded_type(self):
        row = {"query": "nissan leaf range", "query_type": "branded"}
        self.assertFalse(is_non_branded_query(row, "Nissan", default_brand_exclusion_terms("Nissan")))

    def test_query_text_contains_brand(self):
        row = {"query": "nissan ariya vs toyota bz4x"}
        self.assertFalse(is_non_branded_query(row, "Nissan", default_brand_exclusion_terms("Nissan")))

    def test_query_text_contains_model(self):
        row = {"query": "leaf battery warranty japan"}
        self.assertFalse(is_non_branded_query(row, "Nissan", default_brand_exclusion_terms("Nissan")))

    def test_query_text_no_brand_terms(self):
        row = {"query": "best family car japan 2025"}
        self.assertTrue(is_non_branded_query(row, "Nissan", default_brand_exclusion_terms("Nissan")))

    def test_empty_query(self):
        row = {"query": ""}
        self.assertFalse(is_non_branded_query(row, "Nissan", default_brand_exclusion_terms("Nissan")))

    def test_epower_without_nissan_context(self):
        """e-power alone without Nissan context should still be non-branded."""
        row = {"query": "e-power hybrid technology explained"}
        # e-power is in exclusion terms but the special handling allows it
        # when the brand name is not in the query
        self.assertTrue(is_non_branded_query(row, "Nissan", default_brand_exclusion_terms("Nissan")))

    def test_configurable_brand_terms(self):
        """Custom brand terms should work for non-Nissan brands."""
        row = {"query": "corolla vs civic comparison"}
        self.assertFalse(is_non_branded_query(row, "Toyota", default_brand_exclusion_terms("Toyota")))

    def test_unknown_brand_uses_brand_name(self):
        """Unknown brand should use brand name as exclusion term."""
        row = {"query": "bmw x5 review"}
        self.assertFalse(is_non_branded_query(row, "BMW", ["bmw"]))


class TestCompetitorDetection(unittest.TestCase):
    """Test competitor detection in citations."""

    def setUp(self):
        self.comp_dict = default_competitor_dictionary()
        self.all_domains = {}
        for name, data in self.comp_dict.items():
            for d in data.get("domains", []):
                self.all_domains[d.lower()] = name

    def test_domain_match(self):
        citation = {"url": "https://toyota.co.jp/vehicles/prius", "title": "Prius"}
        matches = _detect_competitors_in_citation(citation, self.comp_dict, self.all_domains)
        self.assertTrue(any(name == "Toyota" for name, _ in matches))

    def test_text_alias_match(self):
        citation = {"url": "https://example.com/review", "title": "Toyota Prius vs Honda Fit comparison"}
        matches = _detect_competitors_in_citation(citation, self.comp_dict, self.all_domains)
        names = {name for name, _ in matches}
        self.assertIn("Toyota", names)
        self.assertIn("Honda", names)

    def test_ambiguous_alias_requires_domain(self):
        """Ambiguous aliases like 'crown' should only match with domain evidence."""
        citation = {"url": "https://example.com/crown-hotel", "title": "Crown Hotel Review"}
        matches = _detect_competitors_in_citation(citation, self.comp_dict, self.all_domains)
        # 'crown' is ambiguous for Toyota, should not match without toyota domain
        toyota_matches = [m for m in matches if m[0] == "Toyota"]
        self.assertEqual(len(toyota_matches), 0)

    def test_no_matches(self):
        citation = {"url": "https://example.com/generic", "title": "Generic car review"}
        matches = _detect_competitors_in_citation(citation, self.comp_dict, self.all_domains)
        self.assertEqual(len(matches), 0)

    def test_japanese_alias_match(self):
        citation = {"url": "https://example.com/review", "title": "\u30c8\u30e8\u30bf\u306e\u65b0\u578b\u8eca"}
        matches = _detect_competitors_in_citation(citation, self.comp_dict, self.all_domains)
        names = {name for name, _ in matches}
        self.assertIn("Toyota", names)


class TestCitationCreditAllocation(unittest.TestCase):
    """Test fractional citation credit allocation."""

    def setUp(self):
        self.all_domains = {
            "toyota.co.jp": "Toyota",
            "honda.co.jp": "Honda",
        }

    def test_domain_owner_gets_full_credit(self):
        competitors = [("Toyota", True), ("Honda", False)]
        credit = _allocate_citation_credit(competitors, "toyota.co.jp", self.all_domains)
        self.assertEqual(credit.get("Toyota"), 1.0)
        self.assertNotIn("Honda", credit)

    def test_split_credit_for_publisher(self):
        competitors = [("Toyota", False), ("Honda", False)]
        credit = _allocate_citation_credit(competitors, "carwow.com", self.all_domains)
        self.assertAlmostEqual(credit.get("Toyota", 0), 0.5)
        self.assertAlmostEqual(credit.get("Honda", 0), 0.5)

    def test_single_competitor_full_credit(self):
        competitors = [("Mazda", False)]
        credit = _allocate_citation_credit(competitors, "example.com", self.all_domains)
        self.assertEqual(credit.get("Mazda"), 1.0)

    def test_empty_competitors(self):
        credit = _allocate_citation_credit([], "example.com", self.all_domains)
        self.assertEqual(len(credit), 0)


class TestRankWeighting(unittest.TestCase):
    """Test citation rank weighting."""

    def test_rank_1(self):
        self.assertEqual(rank_weight(1), 1.0)

    def test_rank_2(self):
        self.assertEqual(rank_weight(2), 0.75)

    def test_rank_3(self):
        self.assertEqual(rank_weight(3), 0.55)

    def test_rank_4(self):
        self.assertEqual(rank_weight(4), 0.35)

    def test_rank_5_plus(self):
        self.assertEqual(rank_weight(5), 0.20)
        self.assertEqual(rank_weight(10), 0.20)

    def test_no_rank(self):
        self.assertEqual(rank_weight(None), 0.35)

    def test_invalid_rank(self):
        self.assertEqual(rank_weight(0), 0.35)
        self.assertEqual(rank_weight(-1), 0.35)


class TestSourceTypeClassification(unittest.TestCase):
    """Test source type classification."""

    def test_competitor_owned_domain(self):
        result = classify_source_type(
            "https://toyota.co.jp/vehicles",
            {"toyota.co.jp"},
        )
        self.assertEqual(result, "competitor_owned_domain")

    def test_forum_social(self):
        result = classify_source_type("https://reddit.com/r/cars", set())
        self.assertEqual(result, "forum_social_video")

    def test_authority_body(self):
        result = classify_source_type("https://www.mlit.go.jp/safety", set())
        self.assertEqual(result, "authority_body")

    def test_publisher_review(self):
        result = classify_source_type("https://carwow.com/review", set(), "publisher_review")
        self.assertEqual(result, "publisher_review")

    def test_existing_source_type_mapping(self):
        result = classify_source_type("https://example.com", set(), "competitor_owned")
        self.assertEqual(result, "competitor_owned_domain")

    def test_fallback_other_external(self):
        result = classify_source_type("https://random-site.com", set())
        self.assertEqual(result, "other_external")


class TestFramingScore(unittest.TestCase):
    """Test framing signal score computation."""

    def test_no_texts(self):
        self.assertEqual(compute_framing_score([]), 3)

    def test_positive_framing(self):
        score = compute_framing_score(["This is the best and most reliable car"])
        self.assertGreater(score, 3)

    def test_no_framing_terms(self):
        score = compute_framing_score(["This car has four wheels and an engine"])
        self.assertEqual(score, 3)  # Neutral

    def test_max_score_cap(self):
        score = compute_framing_score(["best top reliable popular trusted award recommended safer better efficient"])
        self.assertLessEqual(score, 10)


class TestDomainExtraction(unittest.TestCase):
    """Test URL domain extraction."""

    def test_standard_url(self):
        self.assertEqual(_extract_domain("https://www.toyota.co.jp/vehicles"), "toyota.co.jp")

    def test_no_www(self):
        self.assertEqual(_extract_domain("https://honda.co.jp/fit"), "honda.co.jp")

    def test_empty_url(self):
        self.assertEqual(_extract_domain(""), "")

    def test_none_url(self):
        self.assertEqual(_extract_domain(None), "")


class TestBuildCompetitorVisibilityMatrix(unittest.TestCase):
    """Integration tests for the full matrix builder."""

    def _make_bundle(self, queries: list[dict]) -> dict:
        return {
            "brand": "Nissan",
            "market": "Japan",
            "query_workbench": queries,
        }

    def test_empty_bundle(self):
        bundle = self._make_bundle([])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        self.assertEqual(matrix["schema_version"], "competitor_visibility_matrix.v1")
        self.assertEqual(matrix["brand"], "Nissan")
        self.assertEqual(matrix["market"], "Japan")
        self.assertEqual(matrix["query_count_non_branded"], 0)
        self.assertEqual(len(matrix["competitors"]), 0)

    def test_branded_queries_excluded(self):
        bundle = self._make_bundle([
            {"query_id": "q001", "query": "nissan leaf range", "query_type": "branded",
             "current_ai_visibility": {"top_citations": [
                 {"url": "https://toyota.co.jp/prius", "title": "Toyota Prius", "rank": 1}
             ]}},
        ])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        self.assertEqual(matrix["query_count_non_branded"], 0)
        self.assertEqual(len(matrix["competitors"]), 0)

    def test_non_branded_with_competitor_citations(self):
        bundle = self._make_bundle([
            {
                "query_id": "q001",
                "query": "best family car japan 2025",
                "query_type": "non_branded",
                "journey_category": "Use case fit",
                "current_ai_visibility": {
                    "top_citations": [
                        {"url": "https://toyota.co.jp/alphard", "title": "Toyota Alphard", "rank": 1, "source_type": "competitor_owned"},
                        {"url": "https://honda.co.jp/freed", "title": "Honda Freed", "rank": 2, "source_type": "competitor_owned"},
                        {"url": "https://carwow.com/comparison", "title": "Toyota vs Honda family cars", "rank": 3},
                    ],
                },
            },
            {
                "query_id": "q002",
                "query": "safest car japan rating",
                "query_type": "non_branded",
                "journey_category": "Safety",
                "current_ai_visibility": {
                    "top_citations": [
                        {"url": "https://toyota.co.jp/safety", "title": "Toyota Safety", "rank": 1},
                    ],
                },
            },
        ])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        self.assertEqual(matrix["query_count_non_branded"], 2)
        self.assertGreater(len(matrix["competitors"]), 0)

        # Toyota should be the top competitor
        toyota = next((c for c in matrix["competitors"] if c["competitor"] == "Toyota"), None)
        self.assertIsNotNone(toyota)
        self.assertGreater(toyota["ai_visibility_score"], 0)
        self.assertEqual(toyota["queries_present"], 2)
        self.assertIn("competitor_owned_domain", toyota["source_type_influence_pct"])

        # Honda should also be present
        honda = next((c for c in matrix["competitors"] if c["competitor"] == "Honda"), None)
        self.assertIsNotNone(honda)

    def test_audited_brand_excluded_from_competitors(self):
        bundle = self._make_bundle([
            {
                "query_id": "q001",
                "query": "best electric car japan",
                "query_type": "non_branded",
                "current_ai_visibility": {
                    "top_citations": [
                        {"url": "https://nissan.co.jp/leaf", "title": "Nissan Leaf", "rank": 1},
                        {"url": "https://toyota.co.jp/bz4x", "title": "Toyota bZ4X", "rank": 2},
                    ],
                },
            },
        ])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        competitor_names = [c["competitor"] for c in matrix["competitors"]]
        self.assertNotIn("Nissan", competitor_names)

    def test_score_components_present(self):
        bundle = self._make_bundle([
            {
                "query_id": "q001",
                "query": "best SUV japan",
                "query_type": "non_branded",
                "journey_category": "Research",
                "current_ai_visibility": {
                    "top_citations": [
                        {"url": "https://toyota.co.jp/rav4", "title": "Toyota RAV4", "rank": 1},
                    ],
                },
            },
        ])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        toyota = next((c for c in matrix["competitors"] if c["competitor"] == "Toyota"), None)
        self.assertIsNotNone(toyota)
        sc = toyota["score_components"]
        self.assertIn("query_presence", sc)
        self.assertIn("citation_presence", sc)
        self.assertIn("citation_rank", sc)
        self.assertIn("topic_breadth", sc)
        self.assertIn("source_diversity", sc)
        self.assertIn("framing_signal", sc)

    def test_ai_visibility_score_range(self):
        bundle = self._make_bundle([
            {
                "query_id": f"q{i:03d}",
                "query": f"query {i}",
                "query_type": "non_branded",
                "current_ai_visibility": {
                    "top_citations": [
                        {"url": "https://toyota.co.jp/page", "title": "Toyota", "rank": 1},
                    ],
                },
            }
            for i in range(10)
        ])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        for comp in matrix["competitors"]:
            self.assertGreaterEqual(comp["ai_visibility_score"], 0)
            self.assertLessEqual(comp["ai_visibility_score"], 100)

    def test_source_type_influence_sums_approximately_100(self):
        bundle = self._make_bundle([
            {
                "query_id": "q001",
                "query": "best car japan",
                "query_type": "non_branded",
                "current_ai_visibility": {
                    "top_citations": [
                        {"url": "https://toyota.co.jp/page", "title": "Toyota", "rank": 1},
                        {"url": "https://carwow.com/toyota-review", "title": "Toyota review", "rank": 2, "source_type": "publisher_review"},
                    ],
                },
            },
        ])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        for comp in matrix["competitors"]:
            total = sum(comp["source_type_influence_pct"].values())
            # Allow small rounding tolerance
            self.assertAlmostEqual(total, 100.0, delta=1.0,
                                   msg=f"{comp['competitor']} source type influence sums to {total}")

    def test_methodology_present(self):
        bundle = self._make_bundle([])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        self.assertIn("methodology", matrix)
        self.assertEqual(matrix["methodology"]["score_type"], "observed_competitor_visibility_index")
        self.assertEqual(matrix["methodology"]["score_scale"], "0-100")
        self.assertIn("scoring_components", matrix["methodology"])
        self.assertIn("citation_rank_weights", matrix["methodology"])

    def test_top_domains_present(self):
        bundle = self._make_bundle([
            {
                "query_id": "q001",
                "query": "best car japan",
                "query_type": "non_branded",
                "current_ai_visibility": {
                    "top_citations": [
                        {"url": "https://toyota.co.jp/page1", "title": "Toyota 1", "rank": 1},
                        {"url": "https://toyota.co.jp/page2", "title": "Toyota 2", "rank": 2},
                    ],
                },
            },
        ])
        matrix = build_competitor_visibility_matrix(bundle, brand="Nissan", market="Japan")
        toyota = next((c for c in matrix["competitors"] if c["competitor"] == "Toyota"), None)
        self.assertIsNotNone(toyota)
        self.assertGreater(len(toyota["top_domains"]), 0)
        self.assertIn("domain", toyota["top_domains"][0])
        self.assertIn("citation_count", toyota["top_domains"][0])

    def test_custom_competitor_dict(self):
        """Custom competitor dictionary should override defaults."""
        custom = {
            "BMW": {
                "aliases": ["bmw"],
                "domains": ["bmw.com"],
                "ambiguous_aliases": [],
            },
        }
        bundle = self._make_bundle([
            {
                "query_id": "q001",
                "query": "best luxury car",
                "query_type": "non_branded",
                "current_ai_visibility": {
                    "top_citations": [
                        {"url": "https://bmw.com/x5", "title": "BMW X5", "rank": 1},
                    ],
                },
            },
        ])
        matrix = build_competitor_visibility_matrix(
            bundle, brand="Nissan", market="Japan", competitor_dict=custom
        )
        names = [c["competitor"] for c in matrix["competitors"]]
        self.assertIn("BMW", names)
        # Default competitors should NOT be present
        self.assertNotIn("Toyota", names)


if __name__ == "__main__":
    unittest.main()
