# Debug and Development Utilities

This directory contains manual execution scripts for debugging and development purposes.

## Purpose

These scripts are **not** pytest tests. They are standalone utilities for:
- Inspecting API responses
- Debugging field structures
- Verifying component initialization
- Exploring PTAB data structures

## Available Scripts

### Component Verification
- **`test_server.py`** (renamed from tests/) - Verify basic component initialization
  ```bash
  uv run python scripts/debug/test_server.py
  ```
  Checks: Settings, FieldManager, CircuitBreaker initialization

### API Response Inspection
- **`check_all_fields.py`** - Inspect complete API field structure
  ```bash
  uv run python scripts/debug/check_all_fields.py
  ```
  Shows all fields returned by PTAB API for a trial

- **`debug_raw_response.py`** - Inspect raw API responses before filtering
  ```bash
  uv run python scripts/debug/debug_raw_response.py
  ```
  Useful for understanding API response structure

### Data Structure Analysis
- **`check_documentbag_size.py`** - Check documentBag token size
  ```bash
  uv run python scripts/debug/check_documentbag_size.py
  ```
  Demonstrates why documentBag is excluded from minimal/balanced tiers

- **`check_petitioner_structure.py`** - Inspect petitioner data structure
  ```bash
  uv run python scripts/debug/check_petitioner_structure.py
  ```
  Useful for understanding party information fields

## Usage Notes

### API Key Required
All API inspection scripts require a valid USPTO API key:
```bash
# Windows PowerShell
$env:USPTO_API_KEY="your_key_here"

# Linux/macOS
export USPTO_API_KEY="your_key_here"

# Or use secure storage
uv run python -m ptab_mcp.shared_secure_storage --store-uspto
```

### When to Use These Scripts

**Use these debug scripts when:**
- Exploring new API endpoints
- Debugging field configuration issues
- Understanding response structures
- Investigating token explosion issues
- Verifying component initialization

**Don't use these for:**
- Automated testing (use pytest tests in `tests/`)
- CI/CD pipelines (use core test suite)
- Production validation (use integration tests)

## Proxy Verification

For proxy-specific debugging, use:
```bash
uv run python scripts/verify_proxy.py
```

This script tests:
- Safe port parsing
- PFW proxy detection
- Health checks
- Enhanced filename generation

## Related Documentation

- **[tests/README.md](../../tests/README.md)** - Core test suite documentation
- **[USAGE_EXAMPLES.md](../../USAGE_EXAMPLES.md)** - API usage examples
- **[INSTALL.md](../../INSTALL.md)** - Setup and installation

---
**Last Updated**: 2026-01-17
**Status**: Development utilities (not production tests)
