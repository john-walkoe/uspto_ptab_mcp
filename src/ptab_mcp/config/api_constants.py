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
USPTO_REQUESTS_PER_SECOND = 4  # Conservative rate limit (4-15 range)

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
DEFAULT_CACHE_SIZE = 100
DEFAULT_CACHE_TTL_SECONDS = 600  # 10 minutes

# Search Limits
MIN_SEARCH_LIMIT = 1
MAX_SEARCH_LIMIT = 200
DEFAULT_MINIMAL_SEARCH_LIMIT = 50
DEFAULT_BALANCED_SEARCH_LIMIT = 10

# Timeouts
OCR_TIMEOUT_MULTIPLIER = 2  # 2x download_timeout for OCR operations

# Security & Cryptography Constants
DPAPI_ENTROPY_BYTES = 32  # Cryptographically secure entropy size for DPAPI encryption (256 bits)

# Validation Constants
TRIAL_NUMBER_PATTERN = r'^(IPR|PGR|CBM|DER)\d{4}-\d{5}$'
APPEAL_NUMBER_PATTERN = r'^\d{8}$'  # 8-digit appeal numbers
PATENT_NUMBER_PATTERN = r'^\d{7,8}$'  # 7-8 digit patent numbers
