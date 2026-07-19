"""Shared runtime singletons (DP-1/SOLID-5 — AppContext-lite).

Settings bootstrap, logging init, secure-storage key loading, and the four
service singletons (PTAB client, field manager, OCR service, Docling client)
live here so tool modules depend on ONE stable module instead of the
composition root. `_client()` is the lazy-init seam every tool uses — tests
patch `runtime.api_client` (or `runtime.get_api_client`) to inject fakes.
"""

import sys
from pathlib import Path

from .api.ptab_client import PTABClient
from .config.field_manager import FieldManager
from .config.settings import Settings
from .services.ocr_service import OCRService
from .shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

settings = Settings()

from .config.log_config import setup_logging  # noqa: E402 — must run after Settings()
setup_logging(
    log_level=settings.log_level,
    log_dir=settings.ptab_log_dir,
    max_bytes=settings.ptab_log_max_bytes,
    backup_count=settings.ptab_log_backup_count,
)

# Load API keys from secure storage if not in environment variables (DPAPI mode)
if not settings.uspto_api_key:
    from .shared_secure_storage import get_uspto_api_key
    settings.uspto_api_key = get_uspto_api_key()
    if settings.uspto_api_key:
        logger.info("Loaded USPTO API key from DPAPI secure storage")

if not settings.mistral_api_key:
    from .shared_secure_storage import get_mistral_api_key
    settings.mistral_api_key = get_mistral_api_key()
    if settings.mistral_api_key:
        logger.info("Loaded Mistral API key from DPAPI secure storage")

# Validate that we have the required USPTO API key
if not settings.uspto_api_key:
    logger.error("USPTO API key not found in environment variables or secure storage!")
    logger.error("Please run: ./deploy/windows_setup.ps1 to configure API keys")
    sys.exit(1)

api_client = PTABClient(api_key=settings.uspto_api_key)


def get_api_client() -> PTABClient:
    """
    Lazily initialize and return the API client.

    This ensures the client is properly initialized even in complex async contexts
    where the event loop lifecycle may vary between MCP clients.

    Returns:
        PTABClient instance
    """
    global api_client
    if api_client is None:
        logger.info("Initializing PTAB API client")
        api_client = PTABClient(api_key=settings.uspto_api_key)
    return api_client


# Initialize field manager with config path
config_path = Path(__file__).parent.parent.parent / "field_configs.yaml"
field_manager = FieldManager(config_path=config_path)

# Initialize OCR service for document content extraction
ocr_service = OCRService()

# Docling third extraction tier (PyPDF2 -> Mistral -> Docling); disabled
# unless DOCLING_SERVE_URL is set. Gated to DOCLING_MAX_PAGES (default 20)
# because EasyOCR runs ~10-30s/page — large PTAB docs belong on Mistral.
from .api.docling_client import DoclingClient
docling_client = DoclingClient()

logger.info("PTAB MCP Server initialized with FastMCP")
logger.info(f"Field configuration loaded from: {config_path.name}")
if ocr_service.mistral_api_key:
    logger.info("Mistral OCR service configured and ready")
else:
    logger.warning("Mistral API key not configured - OCR extraction unavailable")


def _client() -> PTABClient:
    """The shared PTABClient, lazily (re)initialized (SOLID-5 seam)."""
    global api_client
    if api_client is None:
        api_client = get_api_client()
    return api_client
