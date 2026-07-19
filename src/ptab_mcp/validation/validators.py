"""
Input Validation Functions for PTAB MCP Tools

Provides validation for trial numbers, patent numbers, dates, party names,
and other user inputs to prevent invalid API requests and security issues.
"""

import re
from datetime import datetime
from typing import Optional, Tuple, List


# ==========================================
# TRIAL NUMBER VALIDATION
# ==========================================

TRIAL_NUMBER_PATTERN = r'^(IPR|PGR|CBM|DER)\d{4}-\d{5}$'


def validate_trial_number(trial_number: str) -> str:
    """
    Validate trial number format (IPR2024-00123, PGR2025-00045, etc.).

    Args:
        trial_number: Trial number to validate

    Returns:
        Validated trial number (uppercase, stripped)

    Raises:
        ValueError: If format invalid or empty

    Examples:
        >>> validate_trial_number("IPR2024-00123")
        'IPR2024-00123'
        >>> validate_trial_number("ipr2024-00123")
        'IPR2024-00123'
        >>> validate_trial_number("IPR2024-123")
        ValueError: Invalid trial number format
    """
    if not trial_number:
        raise ValueError("Trial number is required")

    trial_number = trial_number.strip().upper()

    if not re.match(TRIAL_NUMBER_PATTERN, trial_number):
        raise ValueError(
            f"Invalid trial number format: '{trial_number}'. "
            f"Expected format: IPR2024-00123, PGR2025-00045, CBM2023-00001, DER2024-00001"
        )

    return trial_number


# ==========================================
# APPEAL NUMBER VALIDATION
# ==========================================

def validate_appeal_number(appeal_number: str) -> str:
    """
    Validate appeal number format.

    Appeal numbers are 10 digits (YYYYYYNNNNN) without hyphens for API calls.
    User input may include hyphens (YYYY-NNNNNN), which will be removed.

    Args:
        appeal_number: Appeal number to validate

    Returns:
        Validated appeal number WITHOUT hyphens (API format)

    Raises:
        ValueError: If format invalid

    Examples:
        >>> validate_appeal_number("2025000943")
        '2025000943'
        >>> validate_appeal_number("2025-000943")
        '2025000943'
        >>> validate_appeal_number("invalid")
        ValueError: Invalid appeal number format
    """
    if not appeal_number:
        raise ValueError("Appeal number is required")

    appeal_number = appeal_number.strip()

    # Remove any existing hyphens (API expects format without hyphens)
    appeal_number = appeal_number.replace("-", "")

    # Validate format: YYYYYYNNNNN (10 digits, no hyphens)
    if len(appeal_number) != 10 or not appeal_number.isdigit():
        raise ValueError(
            f"Invalid appeal number format: '{appeal_number}'. "
            f"Expected format: 2025000943 (10 digits, no hyphens)"
        )

    # Validate year is reasonable (2000-2100)
    year = int(appeal_number[:4])
    if year < 2000 or year > 2100:
        raise ValueError(
            f"Invalid year in appeal number: {year}. "
            f"Year must be between 2000 and 2100"
        )

    return appeal_number


# ==========================================
# INTERFERENCE NUMBER VALIDATION
# ==========================================

def validate_interference_number(interference_number: str) -> str:
    """
    Validate interference number format.

    Interference numbers can be input as NNN,NNN or NNNNNN
    API expects format WITHOUT comma (e.g., 106087)

    Args:
        interference_number: Interference number to validate

    Returns:
        Validated interference number WITHOUT comma (for API search)

    Raises:
        ValueError: If format invalid

    Examples:
        >>> validate_interference_number("106,123")
        '106123'
        >>> validate_interference_number("106123")
        '106123'
        >>> validate_interference_number("invalid")
        ValueError: Invalid interference number format
    """
    if not interference_number:
        raise ValueError("Interference number is required")

    interference_number = interference_number.strip()

    # Remove comma if present (user may input with comma, but API expects without)
    interference_number_no_comma = interference_number.replace(",", "")

    # Validate format: 6 digits
    if not interference_number_no_comma.isdigit() or len(interference_number_no_comma) != 6:
        raise ValueError(
            f"Invalid interference number format: '{interference_number}'. "
            f"Expected format: 106087 or 106,087 (6 digits)"
        )

    # Return WITHOUT comma (API expects this format)
    return interference_number_no_comma


# ==========================================
# PATENT NUMBER VALIDATION
# ==========================================

def validate_patent_number(patent_number: str) -> str:
    """
    Validate and normalize patent number.

    Accepts:
    - 7-8 digit numbers: 8524787
    - US prefix: US8524787
    - Comma formatting: 8,524,787

    Returns:
        Normalized patent number (digits only)

    Raises:
        ValueError: If format invalid

    Examples:
        >>> validate_patent_number("8524787")
        '8524787'
        >>> validate_patent_number("US8524787")
        '8524787'
        >>> validate_patent_number("8,524,787")
        '8524787'
    """
    if not patent_number:
        raise ValueError("Patent number is required")

    # Remove common prefixes and formatting
    patent_number = patent_number.strip().upper()
    patent_number = patent_number.replace("US", "").replace(",", "").replace(" ", "")

    # Validate digits
    if not patent_number.isdigit():
        raise ValueError(
            f"Invalid patent number: '{patent_number}'. "
            f"Must contain only digits after removing 'US' prefix and commas"
        )

    if len(patent_number) < 7 or len(patent_number) > 8:
        raise ValueError(
            f"Invalid patent number length: '{patent_number}'. "
            f"Must be 7-8 digits (e.g., 8524787)"
        )

    return patent_number


# ==========================================
# DATE VALIDATION
# ==========================================

def validate_date_range(
    date_from: Optional[str],
    date_to: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """
    Validate date range (YYYY-MM-DD format).

    Args:
        date_from: Start date (YYYY-MM-DD) or None
        date_to: End date (YYYY-MM-DD) or None

    Returns:
        Tuple of validated dates (may contain None)

    Raises:
        ValueError: If format invalid or date_to < date_from

    Examples:
        >>> validate_date_range("2024-01-01", "2024-12-31")
        ('2024-01-01', '2024-12-31')
        >>> validate_date_range(None, "2024-12-31")
        (None, '2024-12-31')
        >>> validate_date_range("2024-12-31", "2024-01-01")
        ValueError: date_to must be >= date_from
    """
    if date_from:
        date_from = date_from.strip()
        try:
            datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"Invalid date_from format: '{date_from}'. "
                f"Expected YYYY-MM-DD (e.g., 2024-01-15)"
            )

    if date_to:
        date_to = date_to.strip()
        try:
            datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"Invalid date_to format: '{date_to}'. "
                f"Expected YYYY-MM-DD (e.g., 2024-12-31)"
            )

    # Validate range logic
    if date_from and date_to:
        from_dt = datetime.strptime(date_from, "%Y-%m-%d")
        to_dt = datetime.strptime(date_to, "%Y-%m-%d")

        if to_dt < from_dt:
            raise ValueError(
                f"Invalid date range: date_to ({date_to}) must be >= date_from ({date_from})"
            )

    return date_from, date_to


# ==========================================
# PARTY NAME VALIDATION
# ==========================================

def validate_party_name(party_name: str) -> str:
    """
    Validate party name (petitioner, patent owner, etc.).

    Security: Uses allowlist approach (CWE-20 compliant) to prevent injection attacks.

    Rules:
    - Must be non-empty after stripping
    - Length 2-200 characters
    - Only alphanumeric, spaces, and safe punctuation: . - & , ' ( )
    - Blocks all other characters (prevents SQL injection, XSS, command injection)

    Args:
        party_name: Party name to validate

    Returns:
        Validated party name (stripped)

    Raises:
        ValueError: If invalid

    Examples:
        >>> validate_party_name("Apple Inc")
        'Apple Inc'
        >>> validate_party_name("Samsung Electronics Co., Ltd.")
        'Samsung Electronics Co., Ltd.'
        >>> validate_party_name("O'Reilly & Associates")
        "O'Reilly & Associates"
        >>> validate_party_name("A")
        ValueError: Party name must be at least 2 characters
        >>> validate_party_name("Foo<script>alert('xss')</script>")
        ValueError: Invalid characters in party name
    """
    if not party_name:
        raise ValueError("Party name is required")

    party_name = party_name.strip()

    if len(party_name) < 2:
        raise ValueError(
            f"Party name must be at least 2 characters (got: '{party_name}')"
        )

    if len(party_name) > 200:
        raise ValueError(
            f"Party name must be <= 200 characters (got {len(party_name)} characters)"
        )

    # Allowlist approach: Only allow safe characters (CWE-20 compliant)
    # Allows: letters, numbers, spaces, period, hyphen, ampersand, comma, apostrophe, parentheses
    import re
    if not re.match(r'^[a-zA-Z0-9\s\.\-&,\'()]+$', party_name):
        raise ValueError(
            "Invalid characters in party name. Only letters, numbers, spaces, and "
            "punctuation (. - & , ' ( )) are allowed"
        )

    return party_name


def build_and_query(text: str) -> str:
    """
    Convert a multi-word filter value into an AND-joined query for the
    trials/proceedings/search endpoint.

    The trials endpoint tokenizes unquoted multi-word filter values with OR
    semantics: petitioner_name="Apple Inc." matches every petitioner containing
    "Inc." (~12,600 records). Joining tokens with AND restores intersection
    semantics ("Apple AND Inc." → 1,048 Apple Inc. records, verified live
    2026-07-02) while staying order- and punctuation-insensitive.

    ⚠️ Trials endpoint ONLY. The appeals and interferences decisions/search
    endpoints AND multi-word values natively and return 404 when the value
    contains the AND operator — do not apply this transform there.

    Args:
        text: Validated filter value (e.g., from validate_party_name)

    Returns:
        AND-joined query string, or the original value if single-token

    Examples:
        >>> build_and_query("Apple Inc.")
        'Apple AND Inc.'
        >>> build_and_query("Samsung")
        'Samsung'
        >>> build_and_query("Johnson and Johnson")  # existing operators dropped
        'Johnson AND Johnson'
    """
    tokens = [t for t in text.split() if t.upper() not in ("AND", "OR", "NOT")]
    if len(tokens) <= 1:
        return text
    return " AND ".join(tokens)


# ==========================================
# TRIAL TYPE VALIDATION
# ==========================================

def validate_trial_type(trial_type: str) -> str:
    """
    Validate trial type code.

    Valid types:
    - IPR: Inter Partes Review
    - PGR: Post-Grant Review
    - CBM: Covered Business Method
    - DER: Derivation Proceeding

    Args:
        trial_type: Trial type code

    Returns:
        Validated trial type (uppercase)

    Raises:
        ValueError: If invalid type

    Examples:
        >>> validate_trial_type("IPR")
        'IPR'
        >>> validate_trial_type("pgr")
        'PGR'
        >>> validate_trial_type("XYZ")
        ValueError: Invalid trial type
    """
    if not trial_type:
        raise ValueError("Trial type is required")

    trial_type = trial_type.strip().upper()

    valid_types = ["IPR", "PGR", "CBM", "DER"]
    if trial_type not in valid_types:
        raise ValueError(
            f"Invalid trial type: '{trial_type}'. "
            f"Valid types: {', '.join(valid_types)}"
        )

    return trial_type


# ==========================================
# LIMIT VALIDATION
# ==========================================

def validate_limit(limit: int, max_limit: int = 100) -> int:
    """
    Validate result limit.

    Args:
        limit: Requested limit
        max_limit: Maximum allowed (default 100)

    Returns:
        Validated limit

    Raises:
        ValueError: If limit out of range

    Examples:
        >>> validate_limit(50)
        50
        >>> validate_limit(0)
        ValueError: Limit must be >= 1
        >>> validate_limit(200)
        ValueError: Limit must be <= 100
    """
    if limit < 1:
        raise ValueError(f"Limit must be >= 1 (got: {limit})")

    if limit > max_limit:
        raise ValueError(f"Limit must be <= {max_limit} (got: {limit})")

    return limit


# ==========================================
# IDENTIFIER TYPE VALIDATION
# ==========================================

def validate_identifier_type(identifier_type: str) -> str:
    """
    Validate identifier type for document tools.

    Valid types:
    - trial: Trial proceeding (IPR, PGR, CBM, DER)
    - appeal: Ex parte appeal
    - interference: Interference proceeding

    Args:
        identifier_type: Identifier type

    Returns:
        Validated identifier type (lowercase)

    Raises:
        ValueError: If invalid type

    Examples:
        >>> validate_identifier_type("trial")
        'trial'
        >>> validate_identifier_type("APPEAL")
        'appeal'
        >>> validate_identifier_type("xyz")
        ValueError: Invalid identifier type
    """
    if not identifier_type:
        raise ValueError("Identifier type is required")

    identifier_type = identifier_type.strip().lower()

    valid_types = ["trial", "appeal", "interference"]
    if identifier_type not in valid_types:
        raise ValueError(
            f"Invalid identifier type: '{identifier_type}'. "
            f"Valid types: {', '.join(valid_types)}"
        )

    return identifier_type


def validate_custom_fields(fields: List[str]) -> List[str]:
    """
    Validate custom field list for dynamic field selection.

    Prevents performance issues from including massive fields like documentBag.

    Args:
        fields: List of field names (may include dot notation and wildcards)

    Returns:
        Validated field list

    Raises:
        ValueError: If fields is empty or contains forbidden fields
    """
    if not fields:
        raise ValueError("Custom fields list cannot be empty")

    if not isinstance(fields, list):
        raise ValueError("Custom fields must be a list of strings")

    # Check for forbidden fields that cause massive context usage
    FORBIDDEN_FIELDS = [
        "documentBag",
        "patentTrialDocumentBag",
        "patentAppealDocumentBag",
        "patentInterferenceDocumentBag",
        "trialDocumentBag",
        "appealDocumentBag",
        "interferenceDocumentBag"
    ]

    for field in fields:
        if not isinstance(field, str):
            raise ValueError(f"Field must be a string: {field}")

        # Check for forbidden fields
        field_lower = field.lower()
        for forbidden in FORBIDDEN_FIELDS:
            if forbidden.lower() in field_lower:
                raise ValueError(
                    f"Field '{field}' is forbidden. DocumentBag fields cause 40x context increase. "
                    f"Use ptab_get_documents() tool instead for document metadata."
                )

    return fields


# ==========================================
# TIMEOUT VALIDATION
# ==========================================

def validate_timeout(timeout: float, min_timeout: float = 5.0, max_timeout: float = 120.0) -> float:
    """
    Validate timeout value with bounds checking.

    Security: Prevents denial-of-service and resource exhaustion attacks (CWE-400).

    Rules:
    - Must be a positive number
    - Must be within reasonable bounds (default: 5.0 to 120.0 seconds)
    - Prevents excessively long timeouts (DoS) and too-short timeouts (service failure)

    Args:
        timeout: Timeout value in seconds
        min_timeout: Minimum allowed timeout (default: 5.0 seconds)
        max_timeout: Maximum allowed timeout (default: 120.0 seconds)

    Returns:
        Validated timeout value

    Raises:
        ValueError: If timeout is out of bounds

    Examples:
        >>> validate_timeout(30.0)
        30.0
        >>> validate_timeout(2.0)
        ValueError: Timeout must be >= 5.0 seconds
        >>> validate_timeout(200.0)
        ValueError: Timeout must be <= 120.0 seconds
    """
    if not isinstance(timeout, (int, float)):
        raise ValueError(f"Timeout must be a number (got: {type(timeout).__name__})")

    if timeout < min_timeout:
        raise ValueError(
            f"Timeout must be >= {min_timeout} seconds (got: {timeout}s). "
            f"Very short timeouts can cause legitimate requests to fail."
        )

    if timeout > max_timeout:
        raise ValueError(
            f"Timeout must be <= {max_timeout} seconds (got: {timeout}s). "
            f"Excessively long timeouts can cause resource exhaustion."
        )

    return float(timeout)


DOCUMENT_ID_PATTERN = re.compile(r'^[A-Za-z0-9_\-]{1,64}$')


def validate_document_id(document_id: str) -> str:
    """
    Validate a PTAB document identifier's shape (L-10).

    Document IDs come back from the PTAB API as numeric strings (e.g.
    "171141394"); accept a conservative superset so future formats don't
    break, while rejecting anything that could smuggle header/URL
    metacharacters.

    Raises:
        ValueError: If empty or containing characters outside [A-Za-z0-9_-]
    """
    if not document_id:
        raise ValueError("Document ID is required")
    document_id = document_id.strip()
    if not DOCUMENT_ID_PATTERN.fullmatch(document_id):
        raise ValueError(
            "Invalid document ID - expected 1-64 alphanumeric, underscore, "
            "or hyphen characters"
        )
    return document_id
