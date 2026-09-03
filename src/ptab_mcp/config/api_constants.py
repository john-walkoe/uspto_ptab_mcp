"""API configuration constants for PTAB MCP."""

# Connection Pool Settings
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_KEEPALIVE_EXPIRY_SECONDS = 5.0

# Rate Limiting (Official USPTO ODP Limits - https://data.uspto.gov/apis/api-rate-limits)
# Document Downloads: 5 files per 10 seconds from same IP address
USPTO_MAX_DOWNLOADS_PER_WINDOW = 5
USPTO_RATE_LIMIT_WINDOW_SECONDS = 10

# API Request Threshold:
# - Burst: 1 (no parallel requests with same API key)
# - Rate: 4-15 requests per second depending on API call type
USPTO_MAX_CONCURRENT_REQUESTS = 1  # Burst limit per API key (official limit)
# ENFORCED IN-PROCESS: only the concurrency half, via asyncio.Semaphore(1) in
# PTABClient. USPTO_REQUESTS_PER_SECOND is a transcription of the vendor's
# published rate, NOT a limiter — nothing reads it (RF-8). The rate half is
# enforced only when the cross-process limiter is switched on, by its own
# USPTO_SHARED_RATE_LIMIT_RPS (default 4.0, same number). Semaphore(1) plus
# network latency keeps the effective search rate near or under 4/s in
# practice, but a cached-fast upstream or a run of 404s can exceed it.
USPTO_REQUESTS_PER_SECOND = 4  # Conservative rate limit (4-15 range); see above

# Weekly Quotas (reset Sunday midnight UTC):
# - Meta data retrieval APIs: 5 million calls per week
# - Patent File Wrapper Documents API: 1.2 million calls per week
USPTO_META_DATA_WEEKLY_QUOTA = 5_000_000
USPTO_DOCUMENTS_WEEKLY_QUOTA = 1_200_000

# OCR Rate Limiting
MISTRAL_MAX_CONCURRENT_REQUESTS = 2  # OCR is expensive, limit concurrency

# Circuit Breaker Settings
USPTO_CIRCUIT_BREAKER_THRESHOLD = 5  # Failures before opening
USPTO_CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60  # Seconds before retry

# Cache Settings
# The LRU that backs the circuit breaker's stale-response fallback. At 100
# entries with a 600s TTL a busy server turns the cache over well inside the
# TTL, so the fallback was likeliest to be EMPTY exactly when traffic — and
# therefore breaker-opening risk — was highest (RF-10). Entries are small
# JSON dicts.
DEFAULT_CACHE_SIZE = 500
DEFAULT_CACHE_TTL_SECONDS = 600  # 10 minutes

# Search Limits
MIN_SEARCH_LIMIT = 1
MAX_SEARCH_LIMIT = 200
DEFAULT_MINIMAL_SEARCH_LIMIT = 50
DEFAULT_BALANCED_SEARCH_LIMIT = 10

# Timeouts
OCR_TIMEOUT_MULTIPLIER = 2  # 2x download_timeout for OCR operations

# Document download ceiling. A PTAB exhibit is party-authored, so the buffered
# download that feeds the extraction tiers is capped rather than unbounded.
# Override with PTAB_MAX_PDF_BYTES.
DEFAULT_MAX_PDF_BYTES = 100 * 1024 * 1024  # 100 MB

# Security & Cryptography Constants
DPAPI_ENTROPY_BYTES = 32  # Cryptographically secure entropy size for DPAPI encryption (256 bits)

# Validation Constants
TRIAL_NUMBER_PATTERN = r'^(IPR|PGR|CBM|DER)\d{4}-\d{5}$'
APPEAL_NUMBER_PATTERN = r'^\d{8}$'  # 8-digit appeal numbers
PATENT_NUMBER_PATTERN = r'^\d{7,8}$'  # 7-8 digit patent numbers


# The prose the USPTO PTAB API puts in the body of the 404 it returns for an
# empty result set. Lives here because BOTH the API layer (which tags the
# envelope) and util/search_runner (which maps the tag to an empty result with
# guidance) need it, and matching a vendor's English in nine downstream places
# was the fragility the tag removes. See util/search_runner for the rationale.
USPTO_NO_MATCH_MARKER = "No matching records found"
