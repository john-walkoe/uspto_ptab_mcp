# Security Guidelines

## Overview

This document provides comprehensive security guidelines for developing, deploying, and maintaining the USPTO PTAB MCP Server. Following these guidelines helps ensure the security of API keys, user data, system integrity, and protection against AI-specific attacks.

## API Key Management

### Environment Variables (Required)

**Always use environment variables for API keys:**

```python
# ✅ Correct - Environment variable
api_key = os.getenv("USPTO_API_KEY")
if not api_key:
    raise ValueError("USPTO_API_KEY environment variable is required")

# ❌ Never do this - Hardcoded key
api_key = "your_actual_api_key_here"
```

### API Key Storage

**Windows (DPAPI Encryption):**
```powershell
# Keys encrypted by Windows and stored in:
# ~/.uspto_api_key
# ~/.mistral_api_key

# Only current Windows user can decrypt
```

**Linux/macOS (File Permissions):**
```bash
# Keys stored with restrictive permissions
chmod 600 ~/.uspto_api_key
chmod 600 ~/.mistral_api_key
chmod 600 ~/.config/Claude/claude_desktop_config.json
chmod 700 ~/.config/Claude/
```

**Claude Desktop Configuration:**
```json
{
  "mcpServers": {
    "uspto_ptab": {
      "env": {
        "PTAB_PROXY_PORT": "8083",
        "ENABLE_ALWAYS_ON_PROXY": "true"
      }
    }
  }
}
```

**Note**: API keys are NOT in config - loaded from secure storage.

### What Never to Commit

- Real API keys in any form
- Configuration files with real credentials
- Test files with hardcoded keys
- `.env` files or local config files
- Backup files that might contain keys

## Code Security Patterns

### Secure Patterns

**1. Environment Variable Validation:**
```python
import os

def get_required_env_var(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"{key} environment variable is required")
    return value

# Usage
api_key = get_required_env_var("USPTO_API_KEY")
```

**2. Secure Test Setup:**
```python
# In test files
def setup_test_environment():
    """Set up test environment with fallback to test keys"""
    if not os.getenv("USPTO_API_KEY"):
        os.environ["USPTO_API_KEY"] = "test_key_for_testing"
```

**3. Request ID Tracking:**
```python
# Logging with request IDs for debugging
request_id = generate_request_id()
logger.info(f"[{request_id}] Processing request")
```

### Anti-Patterns to Avoid

**1. Hardcoded Secrets:**
```python
# Never do this
API_KEY = "example_hardcoded_key_never_do_this_12345"
```

**2. Secrets in Comments:**
```python
# Don't include real keys in comments
# My key is: example_key_in_comment_bad_practice_67890
```

**3. Logging Secrets:**
```python
# Never log API keys
logger.info(f"Using API key: {api_key}")  # ❌
logger.info(f"Using API key: {api_key[:4]}***")  # ✅ Safe
```

## Logging Security

### Automated Log Sanitization

**Always use SafeLogger for automatic sanitization:**

```python
# ✅ CORRECT - Using SafeLogger (automatically masks sensitive data)
from ptab_mcp.shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)
logger.error(f"API error: {api_response_text}")  # API keys automatically masked

# ❌ INCORRECT - Direct logging (no sanitization)
import logging
logger = logging.getLogger(__name__)
logger.error(f"API error: {api_response_text}")  # Could expose API keys
```

**SafeLogger automatically masks:**
- USPTO API keys (32-character alphanumeric)
- Mistral API keys (32-character alphanumeric)
- JWT tokens (Bearer tokens)
- IP addresses (partial masking: `192.168.[XXX].[XXX]`)
- Email addresses (username preserved, domain visible)
- Passwords and secrets

### File-Based Logging with Secure Permissions

**Application and security logs are stored with restricted permissions:**

```bash
# Log directory and files (created automatically)
~/.uspto_ptab_mcp/logs/
├── ptab_mcp.log      # Application logs (10MB, 5 backups)
└── security.log      # Security events (10MB, 10 backups)

# Secure permissions (Linux/macOS)
chmod 700 ~/.uspto_ptab_mcp/logs/        # Directory: owner only
chmod 600 ~/.uspto_ptab_mcp/logs/*.log   # Files: owner read/write only
```

**Windows:** Logs inherit user profile permissions (Windows security model)

**Features:**
- **Rotating file handlers** prevent disk space issues (10MB max per file)
- **Separate security log** for compliance (WARNING level and above)
- **Persistent audit trail** for forensic analysis
- **Automatic log rotation** maintains 5 application logs, 10 security logs

**Log retention:**
- Application logs: ~50MB total (10MB × 5 backups)
- Security logs: ~100MB total (10MB × 10 backups)
- Logs older than retention limits are automatically deleted

### Security Event Logging

**Use the security logger for sensitive operations:**

```python
import logging

# Security events go to separate log file
security_logger = logging.getLogger('security')
security_logger.warning("Failed authentication attempt from IP: 192.168.1.100")
security_logger.error("Rate limit exceeded for client: 192.168.1.200")
security_logger.critical("Circuit breaker opened for API: trials")
```

**Security log use cases:**
- Authentication failures
- Rate limit violations
- Circuit breaker state changes
- API key validation failures
- Suspicious request patterns
- Configuration changes

## Error Handling Security

### Secure Error Responses

**Do:**
- Return generic error messages to users
- Log detailed errors securely server-side
- Use request IDs for error correlation

**Don't:**
- Expose internal paths or structure
- Include API keys in error messages
- Return stack traces to users

**Example:**
```python
try:
    result = api_call()
except Exception as e:
    request_id = generate_request_id()
    logger.error(f"[{request_id}] API call failed: {str(e)}")
    return {"error": f"Request failed. Reference ID: {request_id}"}
```

## Input Validation

### Validate All User Input

**Trial Number Validation:**
```python
import re

TRIAL_NUMBER_PATTERN = r'^(IPR|PGR|CBM|DER)\d{4}-\d{5}$'

def validate_trial_number(trial_number: str) -> str:
    if not trial_number:
        raise ValidationError("Trial number required")
    if not re.match(TRIAL_NUMBER_PATTERN, trial_number):
        raise ValidationError(f"Invalid format: {trial_number}")
    return trial_number
```

**Date Range Validation:**
```python
from datetime import datetime

def validate_date_range(date_from: str, date_to: str):
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d")
        end = datetime.strptime(date_to, "%Y-%m-%d")

        if start > end:
            raise ValidationError("Start date must be before end date")

        if (end - start).days > 3650:  # 10 years max
            raise ValidationError("Date range too large (max 10 years)")

    except ValueError:
        raise ValidationError("Invalid date format (use YYYY-MM-DD)")
```

## File Security

### Secure File Permissions (Linux/macOS)

**API Key Files:**
```bash
# Owner read/write only (600)
chmod 600 ~/.uspto_api_key
chmod 600 ~/.mistral_api_key

# Verify permissions
ls -la ~/.uspto_api_key  # Should show: -rw------- 1 user group
```

**Configuration Files:**
```bash
# Claude config directory (700)
chmod 700 ~/.config/Claude/

# Claude config file (600)
chmod 600 ~/.config/Claude/claude_desktop_config.json
```

**Database Files:**
```bash
# Proxy cache (600)
chmod 600 proxy_link_cache.db
```

### Windows Security (DPAPI)

**Automatic Encryption:**
- API keys encrypted using Windows Data Protection API (DPAPI)
- Only current Windows user account can decrypt
- Keys stored in `%USERPROFILE%\.uspto_api_key` and `%USERPROFILE%\.mistral_api_key`
- File permissions managed by Windows ACLs

## Network Security

### Proxy Server Security

**Local Proxy (Port 8083):**
- Listens only on localhost (127.0.0.1)
- No external network access
- Rate limiting enforced (USPTO compliance)
- JWT authentication for inter-MCP communication

**Centralized Proxy (Port 8080):**
- Automatic detection with 3 retries
- Fallback to local proxy if unavailable
- JWT token validation for requests
- Shared secret management

### Rate Limiting

**USPTO API Rate Limits:**
- Respect USPTO's documented rate limits
- Implement token bucket algorithm
- Circuit breaker after 5 consecutive failures
- Monitor logs for 429 responses

**Example:**
```python
from circuit_breaker import CircuitBreaker

@CircuitBreaker(failure_threshold=5, timeout_duration=60)
async def call_uspto_api():
    # API call with automatic circuit breaking
    pass
```

## Dependency Security

### Regular Security Audits

**Automated Scanning:**
```bash
# Run security checks
uv run python -m pip_audit

# Or use safety
uv run safety check

# Or use bandit for code analysis
uv run bandit -r src/
```

### Update Dependencies Regularly

```bash
# Update dependencies
uv sync --upgrade

# Check for known vulnerabilities
uv run pip-audit
```

### Pre-commit Hooks

**Install and Run:**
```bash
# Install pre-commit hooks
uv run pre-commit install

# Run manually
uv run pre-commit run --all-files

# Checks include:
# - detect-secrets (API key scanning with baseline support)
# - prompt-injection-check (AI attack detection with baseline support)
# - bandit (Python security linting)
# - mypy (static type checking)
```

### Baseline Security Systems

**Two baseline systems track known legitimate findings:**

**1. API Secrets Baseline (`.secrets.baseline`):**
- Tracks placeholder API keys, test tokens, and false positives
- Only NEW secret findings cause pre-commit failures
- Automatically scans 20+ secret types (AWS, Azure, GitHub, OpenAI, etc.)
- Update with: `uv run detect-secrets scan --baseline .secrets.baseline`

**2. Prompt Injection Baseline (`.prompt_injections.baseline`):**
- Tracks legitimate code patterns that might look like attacks
- Variable names like `prompt`, `system` in code
- Documentation with attack-related examples
- Only NEW injection patterns cause failures
- Update with: `uv run python .security/check_prompt_injections.py --update-baseline`

**When to Update Baselines:**
- New legitimate code is flagged (variable names, documentation)
- Approved refactoring changes line numbers
- Baseline becomes stale with outdated entries

**When NOT to Update Baselines:**
- Actual malicious patterns detected
- Security-related findings requiring review
- Suspicious-looking additions

See `PROMPT_INJECTION_BASELINE_SYSTEM.md` in Claude_Documents for complete documentation.

## Logging Security

### Secure Logging Practices

**Do:**
- Use structured logging with request IDs
- Log security events (auth failures, rate limits)
- Sanitize sensitive data before logging
- Rotate logs regularly

**Don't:**
- Log API keys or credentials
- Log full user data
- Log detailed error traces to users

**Example:**
```python
import logging
from .util.security_logger import SecurityLogger

logger = SecurityLogger(__name__)

# Safe logging
logger.info(f"[{request_id}] Trial search initiated")
logger.warning(f"[{request_id}] Rate limit approaching")
logger.error(f"[{request_id}] Authentication failed")

# Never log keys
# logger.info(f"Using key: {api_key}")  # ❌
```

## Deployment Security

### Production Checklist

- [ ] API keys in secure storage (DPAPI or chmod 600)
- [ ] Claude config file secured (chmod 600)
- [ ] Pre-commit hooks installed
- [ ] Security scanning configured
- [ ] Logging configured and tested
- [ ] Rate limiting enabled
- [ ] Circuit breaker configured
- [ ] Error messages sanitized
- [ ] Input validation implemented
- [ ] Dependencies up to date
- [ ] Proxy server listening on localhost only

### Security Monitoring

**Key Metrics to Monitor:**
- Failed authentication attempts
- Rate limit violations
- Circuit breaker activations
- Unusual API usage patterns
- Error rate spikes

**Log Review:**
```bash
# Check security logs
tail -f logs/security.log

# Search for security events
grep "SECURITY" logs/*.log

# Monitor error rates
grep "ERROR" logs/*.log | wc -l
```

## Incident Response

### Security Incident Procedure

1. **Detect**: Monitor logs for unusual activity
2. **Assess**: Determine severity and scope
3. **Contain**: Disable compromised keys immediately
4. **Investigate**: Review logs and commit history
5. **Remediate**: Fix vulnerabilities, rotate keys
6. **Document**: Record incident for future reference

### API Key Compromise

**If API key is compromised:**

1. **Immediately revoke key** (USPTO dashboard)
2. **Generate new key** (USPTO dashboard)
3. **Update secure storage**:
   ```bash
   # Windows
   .\deploy\manage_api_keys.ps1

   # Linux/macOS
   uv run python -m ptab_mcp.shared_secure_storage --store-uspto
   ```
4. **Review recent API usage** (USPTO dashboard)
5. **Check for unauthorized access** (logs)
6. **Update deployment scripts** if needed

## Threat Model

### Assets

- USPTO API keys (high value)
- Mistral API keys (medium value)
- PTAB trial data (public, low confidentiality)
- User query patterns (medium confidentiality)

### Threats

1. **API Key Theft**: Hardcoded keys, exposed logs, compromised systems
2. **Unauthorized Access**: Bypassing authentication, privilege escalation
3. **Data Exfiltration**: Unauthorized data downloads, mass scraping
4. **Denial of Service**: API rate limit exhaustion, resource consumption
5. **Code Injection**: SQL injection, command injection, prompt injection

### Mitigations

1. **API Key Theft**: Secure storage (DPAPI/chmod 600), no hardcoding, secret scanning
2. **Unauthorized Access**: Input validation, JWT authentication, localhost-only proxy
3. **Data Exfiltration**: Rate limiting, logging, circuit breakers
4. **Denial of Service**: Rate limiting, circuit breakers, resource limits
5. **Code Injection**: Input validation, parameterized queries, sanitization

## Best Practices Summary

### Development

- ✅ Use environment variables for all secrets
- ✅ Enable pre-commit hooks for secret detection
- ✅ Validate all user input
- ✅ Use structured logging with request IDs
- ✅ Implement circuit breakers for external APIs
- ✅ Write security-focused unit tests

### Deployment

- ✅ Use secure storage (DPAPI or chmod 600)
- ✅ Verify file permissions (Linux/macOS)
- ✅ Configure rate limiting
- ✅ Enable security logging
- ✅ Monitor for suspicious activity
- ✅ Keep dependencies updated

### Operations

- ✅ Regular security audits
- ✅ Log review and monitoring
- ✅ Dependency vulnerability scanning
- ✅ Incident response procedures
- ✅ API key rotation schedule
- ✅ Backup and recovery planning

---

## Related Documentation

- **[SECURITY_SCANNING.md](SECURITY_SCANNING.md)** - Automated security scanning tools
- **[INSTALL.md](INSTALL.md)** - Secure installation procedures
- **[README.md](README.md)** - Project overview and security features

---

**Last Updated**: 2026-01-11
**Version**: 1.0.0
**Status**: Production Ready ✅
