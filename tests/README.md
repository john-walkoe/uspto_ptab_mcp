# Test Suite

This directory contains the test scripts for the USPTO PTAB MCP Server.

## ⭐ Start Here: TEST_SUITE.md

**[`TEST_SUITE.md`](TEST_SUITE.md)** is the manual end-to-end suite — 18 tests
covering the 14 tools registered by default against the live USPTO API, including the MCP Apps views,
persistent download links, the downloads page, the Docling OCR tier, and HTTP
transport mode. Run it via Claude Desktop after any significant change.

The pytest files below are the automated developer tests.

## Test Organization

The test suite is organized into:
- **Manual End-to-End Suite** (`TEST_SUITE.md`) - 18 tests, run via Claude Desktop
- **Core Production Tests** (13 files listed below) - pytest-based, run in CI
- **Debug/Development Scripts** - Manual inspection utilities (see `scripts/debug/`)

## Core Production Tests (Essential)

| Test File | Purpose | Coverage |
|-----------|---------|----------|
| `test_workflow.py` | End-to-end integration tests (Phase 9) | Complete workflows (minimal→balanced→documents) |
| `test_trials.py` | Trials API endpoint tests | IPR, PGR, CBM proceedings |
| `test_appeals.py` | Appeals API endpoint tests | Ex parte appeals |
| `test_interferences.py` | Interferences API endpoint tests | Interference proceedings |
| `test_proxy_integration.py` | Proxy integration tests | Standalone/centralized modes, CENTRALIZED_PROXY_URL |
| `test_proxy_server.py` | Proxy server functionality | Token auth, persistent links, downloads page, registry |
| `test_ui_views.py` | MCP App view sanity checks | HTML patterns, resource registration, defer_loading contract |
| `test_field_manager.py` | YAML field configuration | Field filtering, progressive disclosure |
| `test_deployment.py` | Deployment script validation | Windows/Linux setup scripts (key storage isolated to tmp) |
| `test_validation.py` | Input validation tests | Trial numbers, dates, parameters |
| `test_document_tools.py` | Document tool behaviour | Listing, download links, extraction tiers |
| `test_response_bounds.py` | Response-size guard | `_bounds` / `_window` markers, registration proxy |
| `test_auth_provider.py` | OAuth 2.1 provider | Sign-in, scopes, token handling |

**Run core tests only:**
```bash
uv run pytest tests/test_workflow.py tests/test_trials.py tests/test_appeals.py tests/test_interferences.py tests/test_proxy_integration.py tests/test_field_manager.py tests/test_validation.py -v
```

## Available MCP Tools (14 Total)

The server provides these tools for PTAB research:

### Search Tools (Trials)
- **`PTAB_search_trials_minimal`** - Minimal fields (95-99% context reduction)
- **`PTAB_search_trials_balanced`** - Balanced fields (85-95% context reduction)
- **`PTAB_search_trials_complete`** - Complete data (all fields, 80-90% context reduction)

### Document Tools (Shared for Trials/Appeals/Interferences)
- **`PTAB_get_documents`** - List all documents for identifier
- **`PTAB_get_document_download`** - Secure browser-accessible download URLs
- **`PTAB_get_document_content`** - Extract text with hybrid pypdf/OCR approach

### Guidance Tool
- **`PTAB_get_guidance`** - **RECOMMENDED**: Context-efficient selective guidance (95-99% reduction per section)

### Utility Tools
- **`PTAB_get_field_configs`** - View current field configuration

> Note: legacy scripts (`test_server.py`, `test_documents.py`, `test_security.py`,
> `test_rate_limiting.py`, `test_ocr.py`) referenced in older revisions of this
> README were archived to `scripts/debug/` or removed — the table above is the
> authoritative list.

## API Key Setup

**Option 1: Unified Secure Storage (Recommended)**

API keys can be stored in unified secure storage (shared across USPTO MCPs) which is encrypted and persistent:

```bash
# Store USPTO API key
uv run python -m ptab_mcp.shared_secure_storage --store-uspto

# Store Mistral API key (optional)
uv run python -m ptab_mcp.shared_secure_storage --store-mistral

# Verify stored keys (shows metadata only, not actual values)
uv run python -c "from ptab_mcp.shared_secure_storage import get_uspto_api_key, get_mistral_api_key; print('USPTO:', 'OK' if get_uspto_api_key() else 'NOT FOUND'); print('Mistral:', 'OK' if get_mistral_api_key() else 'NOT FOUND')"
```

Keys are automatically loaded from secure storage with environment variable fallback. See `SECURITY_GUIDELINES.md` for setup instructions.

**Option 2: Environment Variables**
```bash
# Windows Command Prompt
set USPTO_API_KEY=your_api_key_here
set MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL

# Windows PowerShell
$env:USPTO_API_KEY="your_api_key_here"
$env:MISTRAL_API_KEY="your_mistral_api_key_here_OPTIONAL"

# Linux/macOS
export USPTO_API_KEY=your_api_key_here
export MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL
```

**Option 3: Testing Without Real API Key**
If you don't have a USPTO API key yet, the test files will automatically use a test key for basic functionality testing. However, actual API calls will fail without a real key.

**Note:** The MISTRAL_API_KEY is optional. Without it, document extraction reads the PDF's native text layer with pypdf, which covers text-based PDFs. With it, scanned pages that carry no text layer can be OCR'd. A self-hosted Docling backend (`DOCLING_SERVE_URL`) can serve the same role.

## Running Tests

### With pytest
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_trials.py

# Run with verbose output
uv run pytest -v

# Run with coverage
uv run pytest --cov=src/ptab_mcp --cov-report=html
```

## Test Organization

### Test Levels

1. **Unit Tests** (`test_field_manager.py`, `test_validation.py`)
   - Test individual components in isolation
   - No network calls
   - Fast execution

2. **Integration Tests** (`test_trials.py`, `test_appeals.py`, `test_interferences.py`,
   `test_document_tools.py`)
   - Test API client interactions
   - Live-API paths are gated off by default
   - Network dependent when enabled

3. **End-to-End Tests** (`test_workflow.py`)
   - Test complete user workflows
   - Progressive disclosure patterns
   - Cross-tool integration

4. **Security Tests** (`test_medium_security_fixes.py`, `test_low_security_fixes.py`,
   `test_injection_scan.py`, `test_logging_hardening.py`,
   `test_client_transport_hardening.py`)
   - Input validation
   - Error handling
   - Log sanitization and prompt-injection detection

## Test Data

### Known Proceedings for Testing

These resolve against the live USPTO ODP API (verified 2026-09-03):

| Trial Number | Type | Patent Number | Status | Notes |
|--------------|------|---------------|--------|-------|
| `IPR2024-01353` | IPR | 7883848 | Final Written Decision - Appealed | 108-document docket; Petition doc `170873668`, FWD doc `171303338` |
| `IPR2023-01035` | IPR | 10995048 | Final Written Decision | Petition doc `170603095`, 75 pages, pypdf-extractable |
| `IPR2024-00070` | IPR | 8207363 | Institution Denied | Denial 2024-04-18 |
| `IPR2023-01234` | IPR | 6588260 | Terminated-Settled | Settled 2024-07-01 |
| `PGR2025-00009` | PGR | 12123035 | Final Written Decision | Post-grant review example |
| `CBM2020-00029` | CBM | 10467585 | Final Written Decision | The CBM program has sunset; CBM2020 is the last series |

Appeal example: application `17/888,602` (appeal 2026002482, TC 3900 / AU 3992,
Affirmed 2026-08-12). Interference example: `106,130`.

## Troubleshooting

### Common Issues

**Issue: `ModuleNotFoundError: No module named 'ptab_mcp'`**
```bash
# Solution: Install package in editable mode
uv pip install -e .
```

**Issue: `API key not found` error**
```bash
# Solution: Set environment variable or use secure storage
export USPTO_API_KEY=your_key_here

# Or store in secure storage
uv run python -m ptab_mcp.shared_secure_storage --store-uspto
```

**Issue: Tests fail with `ConnectionError`**
```bash
# Possible causes:
# 1. Invalid USPTO API key
# 2. Network connectivity issues
# 3. USPTO API rate limits reached

# Solution: Verify API key and check network
uv run python -c "from ptab_mcp.shared_secure_storage import get_uspto_api_key; print(get_uspto_api_key()[:4] + '***' if get_uspto_api_key() else 'NOT FOUND')"
```

**Issue: Document extraction fails**
```bash
# Possible causes:
# 1. Missing MISTRAL_API_KEY (for OCR)
# 2. Scanned PDF requiring OCR

# Solution: Set Mistral API key or use text-based PDFs
export MISTRAL_API_KEY=your_mistral_key_here
```

### Test Debugging

```bash
# Run with verbose output
uv run pytest -v tests/test_trials.py

# Run specific test
uv run pytest tests/test_trials.py::test_search_minimal

# Run with print statements visible
uv run pytest -s tests/test_trials.py

# Generate coverage report
uv run pytest --cov=src/ptab_mcp --cov-report=html tests/
# Open htmlcov/index.html in browser
```

## Test Coverage

### Coverage Goals

- **Overall**: 80%+ code coverage
- **Core modules**: 90%+ coverage (main.py, ptab_client.py, field_manager.py)
- **Security**: 100% coverage for validation and error handling
- **Integration**: All API endpoints tested

### Generate Coverage Report

```bash
# Generate HTML coverage report
uv run pytest --cov=src/ptab_mcp --cov-report=html tests/

# View report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

## Continuous Integration

### GitHub Actions

Tests run automatically on:
- Push to main branch
- Pull requests
- Manual workflow dispatch

**Workflow files**: `.github/workflows/tests.yaml` and `.github/workflows/secret-scan.yaml`

**Tests run**:
- All unit tests
- Integration tests (with API key from secrets)
- Security scanning
- Coverage reporting

## Best Practices

### Writing New Tests

1. **Use descriptive test names**:
   ```python
   def test_search_trials_minimal_returns_expected_field_count():
       pass
   ```

2. **Test one thing per test**:
   ```python
   # ✅ Good
   def test_trial_number_validation_accepts_valid_format():
       pass

   def test_trial_number_validation_rejects_invalid_format():
       pass

   # ❌ Bad
   def test_trial_number_validation():
       # Tests too many things
       pass
   ```

3. **Use fixtures for setup**:
   ```python
   @pytest.fixture
   def api_client():
       return PTABClient(api_key="test_key")
   ```

4. **Mock external dependencies**:
   ```python
   @pytest.mark.asyncio
   async def test_search_with_mock(mocker):
       mock_response = {"count": 10, "results": []}
       mocker.patch("ptab_mcp.api.ptab_client.PTABClient.search_trials", return_value=mock_response)
   ```

### Test Documentation

- **Document test purpose** in docstrings
- **Include expected behavior** in comments
- **Reference requirements** where applicable

## Test File Inventory

The pytest suite is 41 `tests/test_*.py` files. `uv run pytest --collect-only -q`
lists the current inventory; the table under **Core Production Tests** above names
the ones worth running first.

### Debug/Development Scripts (5 files - Utilities)
These are manual execution scripts for development/debugging (not pytest), and
live in `scripts/debug/`:
- 🔧 `test_server.py` - Component initialization verification
- 🔧 `check_all_fields.py` - Inspect API field structure
- 🔧 `debug_raw_response.py` - Inspect raw API responses
- 🔧 `check_documentbag_size.py` - Check documentBag token size
- 🔧 `check_petitioner_structure.py` - Inspect petitioner data structure

## Other Utilities

### Root Directory Scripts
- 📋 `scripts/verify_proxy.py` - Manual proxy verification script (**MOVED**)
  - Tests: Safe port parsing, PFW detection, health checks, enhanced filenames
  - Run: `uv run python scripts/verify_proxy.py`

### Debug/Development Utilities
- 📁 `scripts/debug/` - Manual execution scripts for development (**NEW DIRECTORY**)
  - `test_server.py` - Component initialization verification
  - `check_all_fields.py` - Inspect API field structure
  - `debug_raw_response.py` - Inspect raw API responses
  - `check_documentbag_size.py` - Check documentBag token size
  - `check_petitioner_structure.py` - Inspect petitioner data structure
  - See `scripts/debug/README.md` for usage

## Related Documentation

- **[SECURITY_GUIDELINES.md](../SECURITY_GUIDELINES.md)** - Security best practices
- **[SECURITY_SCANNING.md](../SECURITY_SCANNING.md)** - Automated security scanning
- **[USAGE_EXAMPLES.md](../USAGE_EXAMPLES.md)** - Example workflows and usage patterns
- **[INSTALL.md](../INSTALL.md)** - Installation and setup instructions

---

**Last Updated**: 2026-09-03
**Status**: Production Ready ✅
**Pytest files**: 41 (`tests/test_*.py`)
**Debug Scripts**: 5 files (in `scripts/debug/`)
