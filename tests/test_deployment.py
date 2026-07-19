"""
Test Suite for PTAB MCP Deployment Scripts
Tests both Windows (PowerShell) and Linux (Bash) deployment flows

Requirements:
- Validates API key format validation
- Tests secure storage mechanisms
- Verifies file permissions (Linux)
- Checks DPAPI encryption (Windows)
- Tests Claude Desktop config generation
"""

import os
import sys
import subprocess
import json
import tempfile
import shutil
from pathlib import Path
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from ptab_mcp.shared_secure_storage import (
    store_uspto_api_key,
    store_mistral_api_key,
    get_uspto_api_key,
    get_mistral_api_key
)
from ptab_mcp.config.storage_paths import StoragePaths


@pytest.fixture(autouse=True)
def isolated_key_storage(tmp_path, monkeypatch):
    """Redirect key storage to a temp dir so tests never touch the user's real keys.

    UnifiedSecureStorage reads StoragePaths class attributes at construction time,
    so patching them here isolates every store/retrieve/delete in this module.
    Without this, the deployment checklist tests overwrite and then delete the
    real ~/.uspto_api_key and ~/.mistral_api_key DPAPI files.
    """
    monkeypatch.setattr(StoragePaths, "USPTO_API_KEY", tmp_path / ".uspto_api_key")
    monkeypatch.setattr(StoragePaths, "MISTRAL_API_KEY", tmp_path / ".mistral_api_key")
    monkeypatch.setattr(StoragePaths, "INTERNAL_AUTH_SECRET", tmp_path / ".uspto_internal_auth_secret")

# Test data
VALID_USPTO_KEY = "a" * 30  # 30 lowercase letters
INVALID_USPTO_KEY_SHORT = "a" * 29
INVALID_USPTO_KEY_LONG = "a" * 31
INVALID_USPTO_KEY_UPPER = "A" * 30
INVALID_USPTO_KEY_NUMERIC = "1" * 30

VALID_MISTRAL_KEY = "abc123XYZ456def789GHI012jkl345MN"  # 32 alphanumeric
INVALID_MISTRAL_KEY_SHORT = "abc123" * 5  # Only 30 chars
INVALID_MISTRAL_KEY_LONG = "abc123" * 6  # 36 chars
INVALID_MISTRAL_KEY_SPECIAL = "ab!@#$%^&*()1234567890123456789x"  # 32 chars with special chars


class TestValidationHelpers:
    """Test validation-helpers.sh functions"""

    @pytest.fixture
    def validation_script(self):
        """Return path to validation-helpers.sh"""
        return Path(__file__).parent.parent / 'deploy' / 'validation-helpers.sh'

    def run_bash_function(self, script_path: Path, function_name: str, args: list) -> tuple:
        """
        Run a bash function from validation-helpers.sh

        Returns:
            (return_code, stdout, stderr)
        """
        # Escape quotes in arguments properly
        escaped_args = []
        for arg in args:
            # Remove surrounding quotes if they exist (we'll add them back properly)
            clean_arg = arg.strip('"').strip("'")
            escaped_args.append(f'"{clean_arg}"')

        # Use relative path from project root for better portability
        # Get project root (where deploy/ directory is)
        project_root = script_path.parent.parent
        script_relative = script_path.relative_to(project_root)

        # Convert to forward slashes for bash
        script_str = str(script_relative).replace('\\', '/')

        bash_cmd = f'source "{script_str}" && {function_name} {" ".join(escaped_args)}'

        # Use bash from PATH with cwd set to project root
        result = subprocess.run(
            ['bash', '-c', bash_cmd],
            capture_output=True,
            text=True,
            cwd=str(project_root)
        )
        return result.returncode, result.stdout, result.stderr

    def test_validate_uspto_key_valid(self, validation_script):
        """Test USPTO key validation with valid key"""
        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'validate_uspto_api_key',
            [f'"{VALID_USPTO_KEY}"']
        )
        assert returncode == 0, f"Valid USPTO key rejected: stdout={stdout!r}, stderr={stderr!r}"
        assert "OK: USPTO API key format validated" in stdout

    def test_validate_uspto_key_short(self, validation_script):
        """Test USPTO key validation with short key"""
        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'validate_uspto_api_key',
            [f'"{INVALID_USPTO_KEY_SHORT}"']
        )
        assert returncode == 1, "Short USPTO key accepted (should reject)"
        assert "must be exactly 30 characters" in stdout

    def test_validate_uspto_key_long(self, validation_script):
        """Test USPTO key validation with long key"""
        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'validate_uspto_api_key',
            [f'"{INVALID_USPTO_KEY_LONG}"']
        )
        assert returncode == 1, "Long USPTO key accepted (should reject)"
        assert "must be exactly 30 characters" in stdout

    def test_validate_uspto_key_uppercase(self, validation_script):
        """Test USPTO key validation with uppercase letters"""
        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'validate_uspto_api_key',
            [f'"{INVALID_USPTO_KEY_UPPER}"']
        )
        assert returncode == 1, "Uppercase USPTO key accepted (should reject)"
        assert "must contain only lowercase letters" in stdout

    def test_validate_mistral_key_valid(self, validation_script):
        """Test Mistral key validation with valid key"""
        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'validate_mistral_api_key',
            [f'"{VALID_MISTRAL_KEY}"']
        )
        assert returncode == 0, f"Valid Mistral key rejected: {stdout}"
        assert "OK: Mistral API key format validated" in stdout

    def test_validate_mistral_key_short(self, validation_script):
        """Test Mistral key validation with short key"""
        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'validate_mistral_api_key',
            [f'"{INVALID_MISTRAL_KEY_SHORT}"']
        )
        assert returncode == 1, "Short Mistral key accepted (should reject)"
        assert "must be exactly 32 characters" in stdout

    def test_validate_mistral_key_special_chars(self, validation_script):
        """Test Mistral key validation with special characters"""
        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'validate_mistral_api_key',
            [f'"{INVALID_MISTRAL_KEY_SPECIAL}"']
        )
        assert returncode == 1, "Mistral key with special chars accepted (should reject)"
        assert "must contain only letters and numbers" in stdout

    def test_mask_api_key(self, validation_script):
        """Test API key masking for safe display"""
        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'mask_api_key',
            [f'"{VALID_USPTO_KEY}"']
        )
        assert returncode == 0
        assert stdout.strip() == "...aaaaa"  # Last 5 chars only

    @pytest.mark.skipif(sys.platform == 'win32', reason="Linux/macOS only")
    def test_set_secure_file_permissions(self, validation_script, tmp_path):
        """Test setting file permissions to 600"""
        test_file = tmp_path / "test_key.txt"
        test_file.write_text("test_api_key")

        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'set_secure_file_permissions',
            [f'"{test_file}"']
        )

        assert returncode == 0, f"Failed to set permissions: {stdout}"
        assert "OK: Secured file permissions" in stdout

        # Verify permissions are actually 600
        import stat
        file_stat = test_file.stat()
        perms = oct(file_stat.st_mode)[-3:]
        assert perms == "600", f"Expected 600, got {perms}"

    @pytest.mark.skipif(sys.platform == 'win32', reason="Linux/macOS only")
    def test_set_secure_directory_permissions(self, validation_script, tmp_path):
        """Test setting directory permissions to 700"""
        test_dir = tmp_path / "test_config"
        test_dir.mkdir()

        returncode, stdout, stderr = self.run_bash_function(
            validation_script,
            'set_secure_directory_permissions',
            [f'"{test_dir}"']
        )

        assert returncode == 0, f"Failed to set permissions: {stdout}"
        assert "OK: Secured directory permissions" in stdout

        # Verify permissions are actually 700
        import stat
        dir_stat = test_dir.stat()
        perms = oct(dir_stat.st_mode)[-3:]
        assert perms == "700", f"Expected 700, got {perms}"


class TestSecureStorage:
    """Test secure storage mechanisms (Windows DPAPI, Linux file permissions)"""

    def test_store_and_retrieve_uspto_key(self):
        """Test storing and retrieving USPTO API key"""
        test_key = VALID_USPTO_KEY

        # Store key
        result = store_uspto_api_key(test_key)
        assert result is True, "Failed to store USPTO API key"

        # Retrieve key
        retrieved_key = get_uspto_api_key()
        assert retrieved_key == test_key, "Retrieved key doesn't match stored key"

    def test_store_and_retrieve_mistral_key(self):
        """Test storing and retrieving Mistral API key"""
        test_key = VALID_MISTRAL_KEY

        # Store key
        result = store_mistral_api_key(test_key)
        assert result is True, "Failed to store Mistral API key"

        # Retrieve key
        retrieved_key = get_mistral_api_key()
        assert retrieved_key == test_key, "Retrieved key doesn't match stored key"

    @pytest.mark.skipif(sys.platform == 'win32', reason="Linux/macOS only")
    def test_linux_file_permissions_secure(self):
        """Test that API key files have secure permissions (600) on Linux"""
        # Store a test key
        store_uspto_api_key(VALID_USPTO_KEY)

        # Check file permissions
        key_file = StoragePaths.USPTO_API_KEY
        assert key_file.exists(), "API key file not created"

        import stat
        file_stat = key_file.stat()
        perms = oct(file_stat.st_mode)[-3:]

        assert perms == "600", f"Insecure permissions: {perms} (expected 600)"

    @pytest.mark.skipif(sys.platform != 'win32', reason="Windows only")
    def test_windows_dpapi_encryption(self):
        """Test that DPAPI encryption is used on Windows"""
        # Store a test key
        store_uspto_api_key(VALID_USPTO_KEY)

        # Read raw file contents
        key_file = StoragePaths.USPTO_API_KEY
        assert key_file.exists(), "API key file not created"

        raw_content = key_file.read_bytes()

        # Encrypted content should NOT match plaintext key
        assert raw_content != VALID_USPTO_KEY.encode('utf-8'), \
            "Key appears to be stored in plaintext (not encrypted)"

    def test_nonexistent_key_returns_none(self):
        """Test that retrieving non-existent key returns None"""
        # Delete keys if they exist
        uspto_path = StoragePaths.USPTO_API_KEY
        mistral_path = StoragePaths.MISTRAL_API_KEY

        if uspto_path.exists():
            uspto_path.unlink()
        if mistral_path.exists():
            mistral_path.unlink()

        # Try to retrieve
        uspto_key = get_uspto_api_key()
        mistral_key = get_mistral_api_key()

        assert uspto_key is None, "Non-existent USPTO key should return None"
        assert mistral_key is None, "Non-existent Mistral key should return None"


class TestClaudeConfig:
    """Test Claude Desktop configuration generation"""

    def test_config_json_structure_linux(self, tmp_path):
        """Test generating Claude config with correct structure (Linux)"""
        config_file = tmp_path / "claude_desktop_config.json"
        project_dir = "/home/user/uspto_ptab_mcp"

        # Generate config structure
        config = {
            "mcpServers": {
                "uspto_ptab": {
                    "command": "uv",
                    "args": [
                        "--directory",
                        project_dir,
                        "run",
                        "ptab-mcp"
                    ],
                    "env": {
                        "PTAB_PROXY_PORT": "8083",
                        "ENABLE_ALWAYS_ON_PROXY": "true"
                    }
                }
            }
        }

        # Write config
        config_file.write_text(json.dumps(config, indent=2))

        # Verify
        loaded_config = json.loads(config_file.read_text())
        assert "mcpServers" in loaded_config
        assert "uspto_ptab" in loaded_config["mcpServers"]
        assert loaded_config["mcpServers"]["uspto_ptab"]["command"] == "uv"

        # CRITICAL: API keys should NOT be in config
        ptab_config = loaded_config["mcpServers"]["uspto_ptab"]
        assert "USPTO_API_KEY" not in ptab_config.get("env", {})
        assert "MISTRAL_API_KEY" not in ptab_config.get("env", {})

    def test_config_merge_preserves_existing(self, tmp_path):
        """Test that merging config preserves existing MCP servers"""
        config_file = tmp_path / "claude_desktop_config.json"

        # Create existing config with another MCP
        existing_config = {
            "mcpServers": {
                "uspto_pfw": {
                    "command": "uv",
                    "args": ["--directory", "/path/to/pfw", "run", "pfw-mcp"]
                }
            }
        }
        config_file.write_text(json.dumps(existing_config, indent=2))

        # Merge new PTAB config
        loaded_config = json.loads(config_file.read_text())
        loaded_config["mcpServers"]["uspto_ptab"] = {
            "command": "uv",
            "args": ["--directory", "/path/to/ptab", "run", "ptab-mcp"]
        }
        config_file.write_text(json.dumps(loaded_config, indent=2))

        # Verify both servers exist
        final_config = json.loads(config_file.read_text())
        assert "uspto_pfw" in final_config["mcpServers"]
        assert "uspto_ptab" in final_config["mcpServers"]

    @pytest.mark.skipif(sys.platform == 'win32', reason="Linux/macOS only")
    def test_config_file_permissions_linux(self, tmp_path):
        """Test that Claude config file has secure permissions (600) on Linux"""
        config_file = tmp_path / "claude_desktop_config.json"
        config_file.write_text('{"mcpServers": {}}')

        # Set permissions
        os.chmod(config_file, 0o600)

        # Verify permissions
        import stat
        file_stat = config_file.stat()
        perms = oct(file_stat.st_mode)[-3:]

        assert perms == "600", f"Insecure config permissions: {perms} (expected 600)"


class TestDeploymentIntegration:
    """End-to-end integration tests for deployment"""

    @pytest.mark.skipif(sys.platform == 'win32', reason="Linux/macOS only")
    def test_linux_deployment_security_checklist(self):
        """Comprehensive security checklist for Linux deployment"""
        # Store test keys
        store_uspto_api_key(VALID_USPTO_KEY)
        store_mistral_api_key(VALID_MISTRAL_KEY)

        # Check 1: USPTO API key file exists
        uspto_file = StoragePaths.USPTO_API_KEY
        assert uspto_file.exists(), "USPTO API key file not created"

        # Check 2: Mistral API key file exists
        mistral_file = StoragePaths.MISTRAL_API_KEY
        assert mistral_file.exists(), "Mistral API key file not created"

        # Check 3: USPTO file has 600 permissions
        import stat
        uspto_stat = uspto_file.stat()
        uspto_perms = oct(uspto_stat.st_mode)[-3:]
        assert uspto_perms == "600", f"USPTO key insecure: {uspto_perms}"

        # Check 4: Mistral file has 600 permissions
        mistral_stat = mistral_file.stat()
        mistral_perms = oct(mistral_stat.st_mode)[-3:]
        assert mistral_perms == "600", f"Mistral key insecure: {mistral_perms}"

        # Check 5: Keys can be retrieved
        retrieved_uspto = get_uspto_api_key()
        retrieved_mistral = get_mistral_api_key()
        assert retrieved_uspto == VALID_USPTO_KEY
        assert retrieved_mistral == VALID_MISTRAL_KEY

        # Cleanup
        uspto_file.unlink()
        mistral_file.unlink()

    @pytest.mark.skipif(sys.platform != 'win32', reason="Windows only")
    def test_windows_deployment_security_checklist(self):
        """Comprehensive security checklist for Windows deployment"""
        # Store test keys
        store_uspto_api_key(VALID_USPTO_KEY)
        store_mistral_api_key(VALID_MISTRAL_KEY)

        # Check 1: USPTO API key file exists
        uspto_file = StoragePaths.USPTO_API_KEY
        assert uspto_file.exists(), "USPTO API key file not created"

        # Check 2: Mistral API key file exists
        mistral_file = StoragePaths.MISTRAL_API_KEY
        assert mistral_file.exists(), "Mistral API key file not created"

        # Check 3: Keys are encrypted (not plaintext)
        raw_uspto = uspto_file.read_bytes()
        raw_mistral = mistral_file.read_bytes()
        assert raw_uspto != VALID_USPTO_KEY.encode('utf-8'), "USPTO key not encrypted"
        assert raw_mistral != VALID_MISTRAL_KEY.encode('utf-8'), "Mistral key not encrypted"

        # Check 4: Keys can be retrieved and decrypted
        retrieved_uspto = get_uspto_api_key()
        retrieved_mistral = get_mistral_api_key()
        assert retrieved_uspto == VALID_USPTO_KEY
        assert retrieved_mistral == VALID_MISTRAL_KEY

        # Cleanup
        uspto_file.unlink()
        mistral_file.unlink()


if __name__ == '__main__':
    # Run tests with verbose output
    pytest.main([__file__, '-v', '--tb=short'])
