# Test Suite

This directory contains the test scripts for the USPTO PTAB MCP Server.

## Test Organization

The test suite is organized into:
- **Core Production Tests** (9 essential files) - pytest-based, required for CI/CD
- **Debug/Development Scripts** (5 files) - Manual inspection utilities (see `scripts/debug/`)

## Core Production Tests (Essential)

| Test File | Purpose | Coverage |
|-----------|---------|----------|
| `test_workflow.py` | End-to-end integration tests (Phase 9) | Complete workflows (minimal→balanced→documents) |
| `test_trials.py` | Trials API endpoint tests | IPR, PGR, CBM proceedings |
| `test_appeals.py` | Appeals API endpoint tests | Ex parte appeals |
| `test_interferences.py` | Interferences API endpoint tests | Interference proceedings |
| `test_proxy_integration.py` | Proxy integration tests | Standalone/centralized modes, fallback |
| `test_proxy_server.py` | Proxy server functionality | Health checks, downloads, filenames |
| `test_field_manager.py` | YAML field configuration | Field filtering, progressive disclosure |
| `test_deployment.py` | Deployment script validation | Windows/Linux setup scripts |
| `test_validation.py` | Input validation tests | Trial numbers, dates, parameters |

**Run core tests only:**
```bash
uv run pytest tests/test_workflow.py tests/test_trials.py tests/test_appeals.py tests/test_interferences.py tests/test_proxy_integration.py tests/test_field_manager.py tests/test_validation.py -v
```

## Available MCP Tools (15 Total)

The server provides these tools for PTAB research:

### Search Tools (Trials)
- **`search_trials_minimal`** - Minimal fields (95-99% context reduction)
- **`search_trials_balanced`** - Balanced fields (85-95% context reduction)
- **`search_trials_complete`** - Complete data (all fields, 80-90% context reduction)

### Document Tools (Shared for Trials/Appeals/Interferences)
- **`ptab_get_documents`** - List all documents for identifier
- **`ptab_get_document_download`** - Secure browser-accessible download URLs
- **`ptab_get_document_content`** - Extract text with hybrid PyPDF2/OCR approach

### Guidance Tool
- **`ptab_get_guidance`** - **RECOMMENDED**: Context-efficient selective guidance (95-99% reduction per section)

### Utility Tools
- **`ptab_get_field_configs`** - View current field configuration
- **`ptab_validate_identifiers`** - Validate trial/appeal/interference numbers

## Essential Tests

### Core Functionality Tests
- **`test_server.py`** - Tests basic MCP server startup and configuration
- **`test_trials.py`** - Tests trial endpoint searches (minimal/balanced/complete tiers)
- **`test_documents.py`** - Tests document retrieval and download functionality
- **`test_field_manager.py`** - Tests YAML-based field configuration system

### Integration Tests
- **`test_proxy_integration.py`** - Tests centralized proxy integration with PFW MCP
- **`test_workflow.py`** - Tests end-to-end progressive disclosure workflows

### Security Tests
- **`test_security.py`** - Comprehensive security validation (17+ tests covering OWASP Top 10 and CWE patterns)

### Additional Tests
- **`test_validation.py`** - Tests input validation for all parameters
- **`test_rate_limiting.py`** - Tests rate limiting and circuit breaker functionality
- **`test_ocr.py`** - Tests optional Mistral OCR integration

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

**Note:** The MISTRAL_API_KEY is optional. Without it, document extraction uses free PyPDF2 (works for text-based PDFs). With it, OCR capabilities are available for scanned documents (~$0.001/page cost).

## Running Tests

### With uv (Recommended)
```bash
# Core functionality tests
uv run python tests/test_server.py
uv run python tests/test_trials.py
uv run python tests/test_documents.py
uv run python tests/test_field_manager.py

# Integration tests
uv run python tests/test_proxy_integration.py
uv run python tests/test_workflow.py

# Security tests
uv run python tests/test_security.py

# Additional functionality tests
uv run python tests/test_validation.py
uv run python tests/test_rate_limiting.py
uv run python tests/test_ocr.py
```

### With pytest (Comprehensive)
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

### With traditional Python
```bash
# Core functionality tests
python tests/test_server.py
python tests/test_trials.py
python tests/test_documents.py

# Integration tests
python tests/test_proxy_integration.py
python tests/test_workflow.py
```

## Test Organization

### Test Levels

1. **Unit Tests** (`test_field_manager.py`, `test_validation.py`)
   - Test individual components in isolation
   - No network calls
   - Fast execution

2. **Integration Tests** (`test_trials.py`, `test_documents.py`)
   - Test API client interactions
   - Requires valid USPTO API key
   - Network dependent

3. **End-to-End Tests** (`test_workflow.py`)
   - Test complete user workflows
   - Progressive disclosure patterns
   - Cross-tool integration

4. **Security Tests** (`test_security.py`)
   - Vulnerability scanning (OWASP Top 10)
   - Input validation
   - Error handling
   - CWE pattern detection

## Expected Test Results

### Success Criteria

```bash
# test_server.py
✅ MCP server starts successfully
✅ All 15 tools registered
✅ Configuration loaded correctly

# test_trials.py
✅ Minimal search returns 10-15 fields
✅ Balanced search returns 30-50 fields
✅ Complete search returns all fields
✅ Field filtering working correctly

# test_documents.py
✅ Document list retrieval successful
✅ Download URLs generated correctly
✅ Content extraction working

# test_security.py
✅ All 17+ security checks passing
✅ Input validation working
✅ No critical vulnerabilities detected
```

## Test Data

### Known Trials for Testing

Use these real trial numbers for testing:

| Trial Number | Type | Patent Number | Status | Description |
|--------------|------|---------------|--------|-------------|
| `IPR2024-00070` | IPR | 10701173 | Active | Recent IPR for testing |
| `IPR2023-01234` | IPR | 9876543 | Completed | Example with FWD |
| `PGR2024-00001` | PGR | 11234567 | Active | Post Grant Review example |

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

**Workflow file**: `.github/workflows/test.yaml`

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

### Core Production Tests (9 files - Essential)
- ✅ `test_workflow.py` - 37 end-to-end integration tests
- ✅ `test_trials.py` - Trials API endpoint tests
- ✅ `test_appeals.py` - Appeals API endpoint tests
- ✅ `test_interferences.py` - Interferences API endpoint tests
- ✅ `test_proxy_integration.py` - 19 proxy integration tests
- ✅ `test_proxy_server.py` - Proxy server functionality tests
- ✅ `test_field_manager.py` - 20 field configuration tests
- ✅ `test_deployment.py` - 24 deployment script tests
- ✅ `test_validation.py` - Input validation tests

### Debug/Development Scripts (5 files - Utilities)
These are manual execution scripts for development/debugging (not pytest):
- 🔧 `test_server.py` - Component initialization verification
- 🔧 `check_all_fields.py` - Inspect API field structure
- 🔧 `debug_raw_response.py` - Inspect raw API responses
- 🔧 `check_documentbag_size.py` - Check documentBag token size
- 🔧 `check_petitioner_structure.py` - Inspect petitioner data structure

**Status**: ✅ **COMPLETED** - All debug scripts moved to `scripts/debug/`

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

**Last Updated**: 2026-01-17
**Version**: 1.0.2
**Status**: Production Ready ✅ (**Reorganized**)
**Test Coverage**: 80%+ (core tests)
**Core Tests**: 9 essential files (~3100 LOC)
**Archived Tests**: 10 files (in tests/archive/)
**Debug Scripts**: 5 files (in scripts/debug/)
