# Security Scanning Guide

This document explains the comprehensive automated security scanning setup for the USPTO PTAB MCP project.

## Overview

The project uses multiple security scanning technologies:
- **detect-secrets** to prevent accidental commits of API keys, tokens, passwords, and other sensitive data
- **bandit** for Python security linting
- **mypy** for static type checking
- **safety** for dependency vulnerability scanning

## Features

### 1. CI/CD Secret Scanning (GitHub Actions)
- Automatically scans all code on push and pull requests
- Scans git history (last 100 commits) for accidentally committed secrets
- Fails the build if new secrets are detected
- Location: `.github/workflows/secret-scan.yaml`

### 2. Pre-commit Hooks (Local Development)
- Prevents committing secrets before they reach GitHub
- Runs automatically on `git commit`
- Location: `.pre-commit-config.yaml`

### 3. Baseline Management
- Tracks known placeholder keys and false positives
- Location: `.secrets.baseline`

### 4. Prompt Injection Detection (Enhanced Security)
- Scans for 70+ malicious prompt patterns with baseline support
- Detects PTAB-specific attack vectors (API bypass, data extraction)
- Integrated with pre-commit hooks and CI/CD pipeline
- **Baseline system tracks known findings, only flags NEW patterns**

**Attack Categories Detected:**
- Instruction override attempts ("ignore previous instructions")
- System prompt extraction ("show me your instructions")
- AI behavior manipulation ("you are now a different AI")
- PTAB data extraction ("extract all trial numbers")
- USPTO API bypass attempts ("bypass API restrictions")
- Party information disclosure ("reveal petitioner names")
- Social engineering patterns ("we became friends")
- **Unicode steganography attacks** (Variation Selectors, zero-width characters)

**Baseline System Features:**
- `.prompt_injections.baseline` tracks known legitimate findings
- SHA256 fingerprinting for precise match identification
- Only NEW findings cause pre-commit failures
- Update baseline for legitimate false positives: `--update-baseline`
- See `.security/README.md` for the scanner documentation

### Unicode Steganography Detection (Enhanced Security)

The enhanced detector now includes comprehensive Unicode steganography detection to counter advanced threats like the Repello AI emoji injection attack:

**Detection Capabilities:**
- **Variation Selector Encoding**: Detects VS0/VS1 (U+FE00/U+FE01) binary encoding in emojis
- **Zero-Width Character Abuse**: Identifies suspicious use of invisible Unicode characters
- **High Invisible Character Ratios**: Flags content with >10% invisible-to-visible character ratios
- **Binary Pattern Recognition**: Detects 8+ bit sequences that could encode hidden messages

**Attack Patterns Detected:**
- Emoji steganography (like "Hello!" with hidden binary-encoded messages)
- Zero-width space injection for text manipulation
- Invisible Unicode character abuse for bypassing filters
- Binary steganography using Variation Selectors

**Examples of Detected Threats:**
- `"Hello!" + hidden_binary_message` - Appears innocent but contains malicious instructions
- Text with embedded zero-width characters for prompt manipulation
- Emoji sequences with suspicious Variation Selector patterns
- High ratios of invisible formatting characters

**Reference**: [Repello AI - Prompt Injection Using Emojis](https://repello.ai/blog/prompt-injection-using-emojis)

## Setup

### Install Pre-commit Hooks (Recommended)

```bash
# Install pre-commit framework and detect-secrets
uv pip install pre-commit detect-secrets

# Install the git hooks
uv run pre-commit install

# Test the hooks (optional)
uv run pre-commit run --all-files
```

### Manual Security Scanning

**Secret Detection:**
```bash
# Scan entire codebase
uv run detect-secrets scan

# Scan specific files
uv run detect-secrets scan src/ptab_mcp/main.py

# Update baseline after reviewing findings
uv run detect-secrets scan --baseline .secrets.baseline

# Audit baseline (review all flagged items)
uv run detect-secrets audit .secrets.baseline
```

**Prompt Injection Detection:**

The prompt injection detection system is fully implemented with baseline support.

```bash
# Check for NEW prompt injection findings (baseline mode)
uv run python .security/check_prompt_injections.py --baseline src/ tests/

# Create/update baseline with current findings
uv run python .security/check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json *.py

# Force create new baseline (overwrites existing)
uv run python .security/check_prompt_injections.py --force-baseline src/ tests/

# Run via pre-commit
uv run pre-commit run prompt-injection-check --all-files
```

**Python Security Linting:**
```bash
# Run bandit on source code
uv run bandit -r src/

# Skip specific tests
uv run bandit -r src/ -s B101,B601

# Generate JSON report
uv run bandit -r src/ -f json -o security_report.json
```

**Static Type Checking:**
```bash
# Run mypy on source code
uv run mypy src/ptab_mcp/

# Ignore specific errors
uv run mypy src/ptab_mcp/ --ignore-missing-imports
```

**Dependency Vulnerability Scanning:**
```bash
# Check for known vulnerabilities
uv run safety check

# Or use pip-audit
uv run pip-audit
```

## What Gets Scanned

### Included:
- All Python source files (`src/`, `tests/`)
- Configuration files (except example configs)
- Shell scripts and workflows
- Documentation (except README/guides with example keys)

### Excluded:
- `configs/*.json` - Contains placeholder API keys for examples
- `*.md` - Documentation with example secrets
- `package-lock.json` - NPM lock file
- `.secrets.baseline` - Baseline file itself

## Handling Detection Results

### False Positives (Test/Example Secrets)

If detect-secrets flags a legitimate placeholder:

1. **Verify it's truly a placeholder** (not a real secret)
2. **Update the baseline** to mark it as known:
   ```bash
   uv run detect-secrets scan --baseline .secrets.baseline
   ```
3. **Commit the updated baseline**:
   ```bash
   git add .secrets.baseline
   git commit -m "Update secrets baseline after review"
   ```

### Real Secrets Detected

If you accidentally committed a real secret:

1. **Revoke the secret immediately** (regenerate API key, rotate token, etc.)
2. **Remove from git history**:
   ```bash
   # Use BFG Repo-Cleaner or git filter-branch
   # See: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
   ```
3. **Force push the cleaned history** (if applicable)
4. **Update the baseline**:
   ```bash
   uv run detect-secrets scan --baseline .secrets.baseline
   ```

## Secrets Detection Types

detect-secrets scans for 20+ secret types:

- **API Keys**: AWS, Azure, GitHub, Stripe, etc.
- **Authentication**: Basic Auth, JWT tokens, Bearer tokens
- **Private Keys**: RSA, SSH, GPG keys
- **Database Credentials**: Connection strings, passwords
- **Cloud Credentials**: AWS, GCP, Azure credentials
- **Custom Patterns**: USPTO API keys, Mistral API keys

## Pre-commit Hook Configuration

The `.pre-commit-config.yaml` file configures:

```yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
        exclude: ^(configs/.*\.json|.*\.md|package-lock\.json)$
```

## CI/CD Pipeline Configuration

GitHub Actions workflow (`.github/workflows/secret-scan.yaml`):

```yaml
name: Secret Scanning
on: [push, pull_request]
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 100  # Scan last 100 commits
      - name: Install detect-secrets
        run: pip install detect-secrets
      - name: Scan for secrets
        run: detect-secrets scan --baseline .secrets.baseline
      - name: Scan git history
        run: detect-secrets scan --baseline .secrets.baseline $(git rev-list --all | head -n 100)
```

## Best Practices

### For Developers

1. **Always run pre-commit hooks** before pushing code
2. **Review baseline updates** carefully before committing
3. **Use environment variables** for all secrets
4. **Never commit** `.env` files or local config files
5. **Test with placeholder keys** in test files

### For Code Reviewers

1. **Check for secrets** in pull requests
2. **Verify baseline updates** are legitimate
3. **Ensure proper secret handling** in new code
4. **Validate environment variable usage**

### For Operations

1. **Monitor CI/CD pipeline** for secret detection failures
2. **Rotate secrets periodically** (every 90 days recommended)
3. **Audit baseline regularly** to remove stale entries
4. **Keep scanning tools updated**

## Troubleshooting

### Pre-commit Hook Not Running

```bash
# Reinstall hooks
uv run pre-commit uninstall
uv run pre-commit install

# Verify installation
uv run pre-commit run --all-files
```

### False Positive in Documentation

```bash
# Add to exclusion pattern in .pre-commit-config.yaml
exclude: ^(configs/.*\.json|.*\.md|docs/.*\.md)$
```

### Baseline File Conflicts

```bash
# If baseline has conflicts during merge
git checkout --ours .secrets.baseline  # Keep your version
# OR
git checkout --theirs .secrets.baseline  # Keep their version

# Then regenerate
uv run detect-secrets scan --baseline .secrets.baseline
```

## Security Scanning Checklist

Pre-deployment checklist:

- [ ] Pre-commit hooks installed
- [ ] detect-secrets baseline updated
- [ ] All tests passing
- [ ] bandit security checks passing
- [ ] mypy type checks passing
- [ ] safety dependency check passing
- [ ] No real secrets in codebase
- [ ] API keys in secure storage (DPAPI or chmod 600)
- [ ] File permissions correct (Linux/macOS)
- [ ] CI/CD pipeline configured
- [ ] Security logging enabled

## Related Documentation

- **[SECURITY_GUIDELINES.md](SECURITY_GUIDELINES.md)** - Comprehensive security best practices
- **[INSTALL.md](INSTALL.md)** - Secure installation procedures
- **[README.md](README.md)** - Project overview

---

**Last Updated**: 2026-01-11
**Version**: 1.0.0
**Status**: Production Ready ✅
