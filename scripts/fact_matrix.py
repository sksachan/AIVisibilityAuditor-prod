"""Fact Matrix — Two-Pass Generation Architecture (Pass 1: Fact Mining).

For each target owned URL, isolates that page's crawl record and extracts:
- Visible numeric facts, specs, prices, dates, units
- Feature labels, FAQ-like claims
- Existing JSON-LD nodes, schema types
- Canonical URL, page title/meta

Builds a fact_matrix per URL that is the SINGLE SOURCE OF TRUTH for all claims.
No fact matrix source = no claim.
"""
from __future__ import annotations

import json
import re
from typing import Any
from advanced_geo_contracts import make_fact_entry, validate_fact_snippet_contains_claim


# ---------------------------------------------------------------------------
# JSON-LD Fact Extraction
# ---------------------------------------------------------------------------

def extract_json_ld_facts(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract facts from existing JSON-LD on the page.

    Walks JSON-LD blocks and extracts property/value pairs that contain
    verifiable data (numbers, dates, specifications).
    """
    facts: list[dict[str, Any]] = []
    url = str(page.get("url") or page.get("page_url") or page.get("resolved_url") or "")
    tech = page.get("technical_signals") if isinstance(page.get("technical_signals"), dict) else {}

    # Try to get JSON-LD content from various locations.
    json_ld_raw = (
        page.get("json_ld_content")
        or page.get("json_ld_blocks")
        or page.get("json_ld")
        or tech.get("json_ld_content")
        or tech.get("json_ld_blocks")
        or tech.get("json_ld")
    )

    blocks: list[dict[str, Any]] = []
    if isinstance(json_ld_raw, list):
        blocks = [b for b in json_ld_raw if isinstance(b, dict)]
    elif isinstance(json_ld_raw, dict):
        blocks = [json_ld_raw]
    elif isinstance(json_ld_raw, str):
        try:
            parsed = json.loads(json_ld_raw)
            if isinstance(parsed, list):
                blocks = [b for b in parsed if isinstance(b, dict)]
            elif isinstance(parsed, dict):
                blocks = [parsed]
        except (json.JSONDecodeError, TypeError):
            pass

    for block in blocks:
        _walk_json_ld_node(block, facts, url, depth=0)

    return facts


def _walk_json_ld_node(
    node: dict[str, Any],
    facts: list[dict[str, Any]],
    source_url: str,
    depth: int = 0,
    max_depth: int = 5,
) -> None:
    """Recursively walk a JSON-LD node and extract fact entries."""
    if depth > max_depth:
        return

    skip_keys = {"@context", "@type", "@id", "url", "image", "logo", "sameAs", "mainEntityOfPage"}

    for key, value in node.items():
        if key in skip_keys:
            continue

        if isinstance(value, dict):
            _walk_json_ld_node(value, facts, source_url, depth + 1, max_depth)
            continue

        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _walk_json_ld_node(item, facts, source_url, depth + 1, max_depth)
            continue

        str_value = str(value).strip()
        if not str_value or len(str_value) > 500:
            continue

        # Extract numeric values with units.
        numeric_match = re.match(r'^([\d,.]+)\s*(.*)$', str_value)
        if numeric_match:
            num_val = numeric_match.group(1)
            unit_val = numeric_match.group(2).strip() or None
            snippet = json.dumps({key: str_value}, ensure_ascii=False)
            facts.append(make_fact_entry(
                fact=key,
                value=num_val,
                unit=unit_val,
                source="existing_json_ld",
                source_context_snippet=snippet,
                source_url=source_url,
            ))
        elif _is_factual_value(str_value):
            snippet = json.dumps({key: str_value}, ensure_ascii=False)
            facts.append(make_fact_entry(
                fact=key,
                value=str_value,
                source="existing_json_ld",
                source_context_snippet=snippet,
                source_url=source_url,
            ))


def _is_factual_value(value: str) -> bool:
    """Check if a string value contains factual/verifiable data."""
    if re.search(r'\d', value):
        return True
    factual_patterns = [
        r'\d{4}[-/]\d{2}',  # Dates
        r'\d+\s*(?:km|kwh|kw|mm|kg|L|cc|ps|hp|mph|mpg)',  # Units
        r'\d+\s*(?:円|万円|年|％|\$|\u20ac|\u00a3)',  # Currency/Japanese
    ]
    return any(re.search(p, value, re.I) for p in factual_patterns)


# ---------------------------------------------------------------------------
# Visible Numeric Fact Extraction from Crawl Text
# ---------------------------------------------------------------------------

# Patterns for extracting structured facts from visible page text.
_NUMERIC_PATTERNS = [
    # Distance/range
    (r'(\d[\d,.]*\s*(?:km|miles?|mi))', 'distance'),
    # Energy/power
    (r'(\d[\d,.]*\s*(?:kWh|kW|Wh|PS|hp|bhp|CV))', 'power_energy'),
    # Weight/mass
    (r'(\d[\d,.]*\s*(?:kg|tons?|t|lbs?))', 'weight'),
    # Volume/capacity
    (r'(\d[\d,.]*\s*(?:L|liters?|litres?|cc|ml))', 'volume'),
    # Dimensions
    (r'(\d[\d,.]*\s*(?:mm|cm|m|inches?|in))', 'dimension'),
    # Time/duration
    (r'(\d[\d,.]*\s*(?:minutes?|mins?|hours?|hrs?|seconds?|secs?))', 'duration'),
    # Currency (Japanese)
    (r'(\d[\d,.]*\s*円)', 'price_jpy'),
    (r'(\d[\d,.]*\s*万円)', 'price_jpy_man'),
    # Currency (Western)
    (r'(?:\$|\u20ac|\u00a3)(\d[\d,.]*)', 'price'),
    # Percentage
    (r'(\d[\d,.]*\s*(?:%|％))', 'percentage'),
    # Year
    (r'(20[2-3]\d)', 'year'),
    # Seats/passengers
    (r'(\d+\s*(?:人|席|seats?|passengers?))', 'capacity'),
    # Safety rating
    (r'(\d+\s*(?:stars?|★|星))', 'rating'),
    # Warranty
    (r'(\d+\s*(?:years?|months?|年|ヶ月|か月))', 'warranty_period'),
]


def extract_visible_numeric_facts(
    text: str,
    source_url: str = "",
    context_window: int = 80,
) -> list[dict[str, Any]]:
    """Extract visible numeric facts from crawl text/markdown.

    For each match, captures surrounding context as the source_context_snippet.
    """
    facts: list[dict[str, Any]] = []
    if not text or len(text) < 10:
        return facts

    seen_values: set[str] = set()

    for pattern, fact_type in _NUMERIC_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            matched_text = match.group(0).strip()
            if matched_text in seen_values:
                continue
            seen_values.add(matched_text)

            # Extract context window around the match.
            start = max(0, match.start() - context_window)
            end = min(len(text), match.end() + context_window)
            snippet = text[start:end].strip()
            # Clean up snippet.
            snippet = re.sub(r'\s+', ' ', snippet)

            # Parse value and unit.
            num_match = re.match(r'([\d,.]+)\s*(.*)', matched_text)
            if num_match:
                value = num_match.group(1)
                unit = num_match.group(2).strip() or None
            else:
                value = matched_text
                unit = None

            facts.append(make_fact_entry(
                fact=fact_type,
                value=value,
                unit=unit,
                source="owned_page",
                source_context_snippet=snippet,
                source_url=source_url,
            ))

    return facts


# ---------------------------------------------------------------------------
# Crawl Metadata Fact Extraction
# ---------------------------------------------------------------------------

def extract_crawl_metadata_facts(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract facts from crawl metadata (title, description, canonical, etc.)."""
    facts: list[dict[str, Any]] = []
    url = str(page.get("url") or page.get("page_url") or page.get("resolved_url") or "")
    tech = page.get("technical_signals") if isinstance(page.get("technical_signals"), dict) else {}

    title = str(page.get("title") or page.get("page_title") or tech.get("title") or "")
    description = str(page.get("meta_description") or page.get("description") or tech.get("meta_description") or "")
    canonical = str(page.get("canonical_url") or tech.get("canonical_url") or tech.get("canonicalUrl") or "")

    if title:
        facts.append(make_fact_entry(
            fact="page_title",
            value=title,
            source="crawl_metadata",
            source_context_snippet=f'title: "{title}"',
            source_url=url,
        ))

    if description:
        facts.append(make_fact_entry(
            fact="meta_description",
            value=description,
            source="crawl_metadata",
            source_context_snippet=f'description: "{description}"',
            source_url=url,
        ))

    if canonical:
        facts.append(make_fact_entry(
            fact="canonical_url",
            value=canonical,
            source="crawl_metadata",
            source_context_snippet=f'canonical: "{canonical}"',
            source_url=url,
        ))

    # Schema types.
    schema_types = (
        page.get("schema_types")
        or page.get("schema_types_detected")
        or tech.get("schema_types")
        or tech.get("schemaTypes")
        or []
    )
    if isinstance(schema_types, list) and schema_types:
        facts.append(make_fact_entry(
            fact="schema_types",
            value=", ".join(str(s) for s in schema_types),
            source="crawl_metadata",
            source_context_snippet=f'schema_types: {json.dumps(schema_types)}',
            source_url=url,
        ))

    return facts


# ---------------------------------------------------------------------------
# Fact Matrix Builder (combines all extraction methods)
# ---------------------------------------------------------------------------

def extract_fact_matrix_for_owned_url(page: dict[str, Any]) -> dict[str, Any]:
    """Build a complete fact_matrix for a single owned URL.

    This is Pass 1 of the Two-Pass Generation Architecture.
    The fact_matrix is the SINGLE SOURCE OF TRUTH for all claims.

    Combines:
    1. JSON-LD facts from existing structured data
    2. Visible numeric facts from crawl text
    3. Crawl metadata facts (title, description, canonical)
    """
    url = str(page.get("url") or page.get("page_url") or page.get("resolved_url") or "")
    tech = page.get("technical_signals") if isinstance(page.get("technical_signals"), dict) else {}

    # Get crawl text for visible fact extraction.
    crawl_text = str(
        page.get("markdown")
        or page.get("text")
        or page.get("content_extract")
        or page.get("main_text")
        or tech.get("markdown")
        or tech.get("text")
        or ""
    )

    # Extract facts from all sources.
    json_ld_facts = extract_json_ld_facts(page)
    visible_facts = extract_visible_numeric_facts(crawl_text, source_url=url)
    metadata_facts = extract_crawl_metadata_facts(page)

    # Combine all facts.
    all_facts = json_ld_facts + visible_facts + metadata_facts

    # Validate each fact.
    validated_facts: list[dict[str, Any]] = []
    validation_flags: list[str] = []

    for fact in all_facts:
        if validate_fact_snippet_contains_claim(fact):
            validated_facts.append(fact)
        else:
            validation_flags.append(
                f"Fact '{fact.get('fact')}' with value '{fact.get('value')}' "
                f"could not be validated against snippet"
            )

    # Build the matrix.
    matrix: dict[str, Any] = {
        "url": url,
        "title": str(page.get("title") or page.get("page_title") or ""),
        "facts_count": len(validated_facts),
        "json_ld_facts_count": len(json_ld_facts),
        "visible_facts_count": len(visible_facts),
        "metadata_facts_count": len(metadata_facts),
        "validated_facts": validated_facts,
        "validation_flags": validation_flags,
        "has_json_ld": bool(json_ld_facts),
        "has_crawl_text": bool(crawl_text and len(crawl_text) > 100),
        "crawl_text_length": len(crawl_text),
        "schema_types": (
            page.get("schema_types")
            or page.get("schema_types_detected")
            or tech.get("schema_types")
            or tech.get("schemaTypes")
            or []
        ),
        "json_ld_present": bool(
            page.get("json_ld_present")
            or page.get("jsonLdPresent")
            or tech.get("json_ld_present")
            or tech.get("jsonLdPresent")
        ),
    }

    return matrix


def build_fact_matrices_for_bundle(
    owned_pages: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build fact matrices for all owned pages in a bundle.

    Returns a dict keyed by URL for fast lookup during asset generation.
    """
    matrices: dict[str, dict[str, Any]] = {}
    for page in owned_pages:
        if not isinstance(page, dict):
            continue
        url = str(
            page.get("url")
            or page.get("page_url")
            or page.get("resolved_url")
            or ""
        ).strip().rstrip("/").lower()
        if not url:
            continue
        matrices[url] = extract_fact_matrix_for_owned_url(page)
    return matrices
