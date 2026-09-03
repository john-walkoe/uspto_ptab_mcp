"""
Tests for Validation Functions

Comprehensive tests for input validation covering:
- Trial numbers, appeal numbers, interference numbers
- Patent numbers
- Date ranges
- Party names
- Trial types
- Limits
- Identifier types
"""

import pytest
from src.ptab_mcp.validation.validators import (
    validate_trial_number,
    validate_appeal_number,
    validate_interference_number,
    validate_patent_number,
    validate_date_range,
    validate_party_name,
    build_and_query,
    validate_trial_type,
    validate_limit,
    validate_identifier_type
)


# ==========================================
# TRIAL NUMBER VALIDATION TESTS
# ==========================================

def test_validate_trial_number_valid():
    """Test valid trial number formats"""
    # Valid IPR formats
    assert validate_trial_number("IPR2024-01353") == "IPR2024-01353"
    assert validate_trial_number("PGR2025-00045") == "PGR2025-00045"
    assert validate_trial_number("CBM2020-00029") == "CBM2020-00029"
    assert validate_trial_number("DER2024-00010") == "DER2024-00010"

    # Lowercase should be normalized to uppercase
    assert validate_trial_number("ipr2024-01353") == "IPR2024-01353"
    assert validate_trial_number("pgr2025-00045") == "PGR2025-00045"

    # Whitespace should be stripped
    assert validate_trial_number("  IPR2024-01353  ") == "IPR2024-01353"


def test_validate_trial_number_invalid():
    """Test invalid trial number formats"""
    # Too short
    with pytest.raises(ValueError, match="Invalid trial number format"):
        validate_trial_number("IPR2024-123")

    # Too long
    with pytest.raises(ValueError, match="Invalid trial number format"):
        validate_trial_number("IPR2024-0135345")

    # Invalid type prefix
    with pytest.raises(ValueError, match="Invalid trial number format"):
        validate_trial_number("XYZ2024-00123")

    # Missing hyphen
    with pytest.raises(ValueError, match="Invalid trial number format"):
        validate_trial_number("IPR202400123")

    # Wrong year format
    with pytest.raises(ValueError, match="Invalid trial number format"):
        validate_trial_number("IPR24-00123")

    # Empty string
    with pytest.raises(ValueError, match="required"):
        validate_trial_number("")

    # None (will raise ValueError, not AttributeError)
    with pytest.raises(ValueError, match="required"):
        validate_trial_number(None)


# ==========================================
# APPEAL NUMBER VALIDATION TESTS
# ==========================================

def test_validate_appeal_number_valid():
    """Test valid appeal number formats"""
    # Standard format with dash (dash will be removed to match API format)
    assert validate_appeal_number("2024-001234") == "2024001234"
    assert validate_appeal_number("2025-000001") == "2025000001"

    # Format without dash (no change needed)
    assert validate_appeal_number("2024001234") == "2024001234"
    assert validate_appeal_number("2025000001") == "2025000001"

    # Whitespace should be stripped and dash removed
    assert validate_appeal_number("  2024-001234  ") == "2024001234"


def test_validate_appeal_number_invalid():
    """Test invalid appeal number formats"""
    # Too short
    with pytest.raises(ValueError, match="Invalid appeal number format"):
        validate_appeal_number("2024-12")

    # Too long
    with pytest.raises(ValueError, match="Invalid appeal number format"):
        validate_appeal_number("2024-0012345")

    # Non-numeric
    with pytest.raises(ValueError, match="Invalid appeal number format"):
        validate_appeal_number("ABC-123456")

    # Invalid format
    with pytest.raises(ValueError, match="Invalid appeal number format"):
        validate_appeal_number("2024/001234")

    # Empty
    with pytest.raises(ValueError, match="required"):
        validate_appeal_number("")


def test_validate_appeal_number_edge_cases():
    """Test appeal number edge cases"""
    # Year 2000 should pass (dash will be removed)
    assert validate_appeal_number("2000-001234") == "2000001234"

    # Year 2100 should pass (dash will be removed)
    assert validate_appeal_number("2100-001234") == "2100001234"

    # Year 1999 should fail
    with pytest.raises(ValueError, match="Invalid year"):
        validate_appeal_number("1999-001234")

    # Year 2101 should fail
    with pytest.raises(ValueError, match="Invalid year"):
        validate_appeal_number("2101-001234")


# ==========================================
# PATENT NUMBER VALIDATION TESTS
# ==========================================

def test_validate_patent_number_valid():
    """Test valid patent number formats"""
    # Re-baselined to 7883848 (the patent at issue in IPR2024-01353) so the
    # fixture matches the example identifier the docstrings now carry.
    # Plain 7-8 digit numbers
    assert validate_patent_number("7883848") == "7883848"
    assert validate_patent_number("10123456") == "10123456"

    # US prefix
    assert validate_patent_number("US7883848") == "7883848"
    assert validate_patent_number("US10123456") == "10123456"

    # Comma formatting
    assert validate_patent_number("7,883,848") == "7883848"
    assert validate_patent_number("10,123,456") == "10123456"

    # Combined formatting
    assert validate_patent_number("US 7,883,848") == "7883848"

    # Lowercase prefix
    assert validate_patent_number("us7883848") == "7883848"

    # Whitespace
    assert validate_patent_number("  7883848  ") == "7883848"


def test_validate_patent_number_invalid():
    """Test invalid patent number formats"""
    # Non-digits (after removing US and commas)
    with pytest.raises(ValueError, match="Invalid patent number"):
        validate_patent_number("ABC12345")

    # Too short
    with pytest.raises(ValueError, match="Invalid patent number length"):
        validate_patent_number("123456")

    # Too long
    with pytest.raises(ValueError, match="Invalid patent number length"):
        validate_patent_number("123456789")

    # Empty
    with pytest.raises(ValueError, match="required"):
        validate_patent_number("")


# ==========================================
# DATE RANGE VALIDATION TESTS
# ==========================================

def test_validate_date_range_valid():
    """Test valid date ranges"""
    # Valid range
    from_date, to_date = validate_date_range("2024-01-01", "2024-12-31")
    assert from_date == "2024-01-01"
    assert to_date == "2024-12-31"

    # Same date
    from_date, to_date = validate_date_range("2024-06-15", "2024-06-15")
    assert from_date == "2024-06-15"
    assert to_date == "2024-06-15"

    # None values allowed
    from_date, to_date = validate_date_range(None, "2024-12-31")
    assert from_date is None
    assert to_date == "2024-12-31"

    from_date, to_date = validate_date_range("2024-01-01", None)
    assert from_date == "2024-01-01"
    assert to_date is None

    from_date, to_date = validate_date_range(None, None)
    assert from_date is None
    assert to_date is None

    # Whitespace should be stripped
    from_date, to_date = validate_date_range("  2024-01-01  ", "  2024-12-31  ")
    assert from_date == "2024-01-01"
    assert to_date == "2024-12-31"


def test_validate_date_range_invalid():
    """Test invalid date ranges"""
    # Invalid month
    with pytest.raises(ValueError, match="Invalid date_from format"):
        validate_date_range("2024-13-01", None)

    # Invalid day
    with pytest.raises(ValueError, match="Invalid date_to format"):
        validate_date_range(None, "2024-02-30")

    # Wrong format (missing leading zeros) - Note: strptime actually accepts this
    # with pytest.raises(ValueError, match="Invalid date_from format"):
    #     validate_date_range("2024-1-1", None)

    # Wrong format (slashes instead of hyphens)
    with pytest.raises(ValueError, match="Invalid date_from format"):
        validate_date_range("2024/01/01", None)

    # Reversed range
    with pytest.raises(ValueError, match="must be >="):
        validate_date_range("2024-12-31", "2024-01-01")


# ==========================================
# PARTY NAME VALIDATION TESTS
# ==========================================

def test_validate_party_name_valid():
    """Test valid party names"""
    assert validate_party_name("Apple Inc") == "Apple Inc"
    assert validate_party_name("Samsung Electronics Co., Ltd.") == "Samsung Electronics Co., Ltd."

    # Whitespace should be stripped
    assert validate_party_name("  Samsung  ") == "Samsung"

    # Numbers and special chars (except forbidden) are OK
    assert validate_party_name("3M Company") == "3M Company"
    assert validate_party_name("AT&T Inc.") == "AT&T Inc."


def test_validate_party_name_invalid():
    """Test invalid party names"""
    # Too short
    with pytest.raises(ValueError, match="at least 2 characters"):
        validate_party_name("A")

    # Too long (> 200 chars)
    long_name = "A" * 201
    with pytest.raises(ValueError, match="<= 200 characters"):
        validate_party_name(long_name)

    # SQL injection patterns
    with pytest.raises(ValueError, match="Invalid characters"):
        validate_party_name("Apple; DROP TABLE users--")

    with pytest.raises(ValueError, match="Invalid characters"):
        validate_party_name("Apple /* comment */ Inc")

    with pytest.raises(ValueError, match="Invalid characters"):
        validate_party_name("Apple;-- Inc")

    with pytest.raises(ValueError, match="Invalid characters"):
        validate_party_name("xp_cmdshell")

    # Note: "DROP DATABASE" contains only valid characters (letters + space)
    # and could theoretically be a real company name. The validator uses
    # allowlist approach (more secure) rather than keyword blocking.
    # Therefore, we don't test for keyword rejection here.

    # Empty
    with pytest.raises(ValueError, match="required"):
        validate_party_name("")

    # Only whitespace (becomes empty after strip, so "at least 2 characters" error)
    with pytest.raises(ValueError, match="at least 2 characters"):
        validate_party_name("   ")


def test_build_and_query():
    """AND-join multi-word values for the trials search endpoint (OR-matching fix)"""
    # Single token unchanged
    assert build_and_query("Samsung") == "Samsung"

    # Multi-word gets AND-joined (trials endpoint OR-matches raw multi-word values)
    assert build_and_query("Apple Inc.") == "Apple AND Inc."
    assert build_and_query("Shenzhen Tuoshi Technology") == "Shenzhen AND Tuoshi AND Technology"

    # Existing boolean operators are dropped, not doubled (idempotent)
    assert build_and_query("Apple AND Inc.") == "Apple AND Inc."
    assert build_and_query("Johnson and Johnson") == "Johnson AND Johnson"


# ==========================================
# TRIAL TYPE VALIDATION TESTS
# ==========================================

def test_validate_trial_type_valid():
    """Test valid trial types"""
    assert validate_trial_type("IPR") == "IPR"
    assert validate_trial_type("PGR") == "PGR"
    assert validate_trial_type("CBM") == "CBM"
    assert validate_trial_type("DER") == "DER"

    # Lowercase should be normalized
    assert validate_trial_type("ipr") == "IPR"
    assert validate_trial_type("pgr") == "PGR"

    # Whitespace should be stripped
    assert validate_trial_type("  IPR  ") == "IPR"


def test_validate_trial_type_invalid():
    """Test invalid trial types"""
    with pytest.raises(ValueError, match="Invalid trial type"):
        validate_trial_type("XYZ")

    with pytest.raises(ValueError, match="Invalid trial type"):
        validate_trial_type("ABC")

    with pytest.raises(ValueError, match="required"):
        validate_trial_type("")


# ==========================================
# LIMIT VALIDATION TESTS
# ==========================================

def test_validate_limit_valid():
    """Test valid limits"""
    assert validate_limit(1) == 1
    assert validate_limit(50) == 50
    assert validate_limit(100) == 100

    # Custom max_limit
    assert validate_limit(200, max_limit=500) == 200


def test_validate_limit_invalid():
    """Test invalid limits"""
    # Below minimum
    with pytest.raises(ValueError, match="must be >= 1"):
        validate_limit(0)

    with pytest.raises(ValueError, match="must be >= 1"):
        validate_limit(-5)

    # Above maximum
    with pytest.raises(ValueError, match="must be <= 100"):
        validate_limit(101)

    with pytest.raises(ValueError, match="must be <= 100"):
        validate_limit(200)

    # Custom max_limit
    with pytest.raises(ValueError, match="must be <= 50"):
        validate_limit(51, max_limit=50)


# ==========================================
# IDENTIFIER TYPE VALIDATION TESTS
# ==========================================

def test_validate_identifier_type_valid():
    """Test valid identifier types"""
    assert validate_identifier_type("trial") == "trial"
    assert validate_identifier_type("appeal") == "appeal"
    assert validate_identifier_type("interference") == "interference"

    # Uppercase should be normalized
    assert validate_identifier_type("TRIAL") == "trial"
    assert validate_identifier_type("APPEAL") == "appeal"

    # Whitespace should be stripped
    assert validate_identifier_type("  trial  ") == "trial"


def test_validate_identifier_type_invalid():
    """Test invalid identifier types"""
    with pytest.raises(ValueError, match="Invalid identifier type"):
        validate_identifier_type("xyz")

    with pytest.raises(ValueError, match="Invalid identifier type"):
        validate_identifier_type("patent")

    with pytest.raises(ValueError, match="required"):
        validate_identifier_type("")


# ==========================================
# INTERFERENCE NUMBER VALIDATION TESTS
# ==========================================

def test_validate_interference_number_valid():
    """Test valid interference number formats"""
    # Standard format with comma (comma will be removed to match API format)
    assert validate_interference_number("106,123") == "106123"
    assert validate_interference_number("105,000") == "105000"

    # Format without comma (no change needed)
    assert validate_interference_number("106123") == "106123"
    assert validate_interference_number("105000") == "105000"

    # Whitespace should be stripped and comma removed
    assert validate_interference_number("  106,123  ") == "106123"


def test_validate_interference_number_invalid():
    """Test invalid interference number formats"""
    # Too short
    with pytest.raises(ValueError, match="Invalid interference number format"):
        validate_interference_number("10,123")

    # Too long
    with pytest.raises(ValueError, match="Invalid interference number format"):
        validate_interference_number("1061,234")

    # Non-numeric
    with pytest.raises(ValueError, match="Invalid interference number format"):
        validate_interference_number("ABC,123")

    # Invalid format
    with pytest.raises(ValueError, match="Invalid interference number format"):
        validate_interference_number("106-123")

    # Empty
    with pytest.raises(ValueError, match="required"):
        validate_interference_number("")


def test_validate_interference_number_edge_cases():
    """Test interference number edge cases"""
    # All zeros should pass (comma will be removed)
    assert validate_interference_number("000,000") == "000000"

    # All nines should pass (comma will be removed)
    assert validate_interference_number("999,999") == "999999"

    # Without comma at edges
    assert validate_interference_number("000000") == "000000"
    assert validate_interference_number("999999") == "999999"


def test_validate_patent_number_anchors_the_us_prefix_strip():
    """An unanchored `US` strip turned "8US524787" into the valid but DIFFERENT
    patent number 8524787 and searched for that instead of erroring (PT-43).

    These digits are NOT example identifiers and are deliberately left on the
    old value: the bug only reproduces for this exact "8US524787"/"8524787"
    pair, so re-baselining them would erase what the test pins.
    """
    from src.ptab_mcp.validation.validators import validate_patent_number

    assert validate_patent_number("US8524787") == "8524787"
    assert validate_patent_number("8,524,787") == "8524787"

    with pytest.raises(ValueError, match="Invalid patent number"):
        validate_patent_number("8US524787")


def test_validate_party_name_accepts_real_ptab_party_names():
    """The ASCII-only class rejected legitimate filers: joint ventures with a
    slash, names with a plus, and any non-ASCII letter. Availability, not
    security — query-language injection is closed by util/party_scope.py, which
    quotes every token (PT-44)."""
    from src.ptab_mcp.validation.validators import validate_party_name

    for name in ("A/B Joint Venture", "Bosch GmbH + Co. KG", "Télécom SA",
                 "株式会社東芝", "O'Brien & Sons (US)"):
        assert validate_party_name(name) == name


def test_validate_party_name_still_rejects_injection_shapes():
    from src.ptab_mcp.validation.validators import validate_party_name

    for bad in ("Apple; DROP TABLE users--", "Apple /* comment */ Inc",
                "Apple;-- Inc", "xp_cmdshell"):
        with pytest.raises(ValueError, match="Invalid characters"):
            validate_party_name(bad)
