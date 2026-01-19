# Windows Deployment Script for USPTO PTAB MCP
# PowerShell version - Unified API Key Management

Write-Host "=== USPTO PTAB MCP - Windows Setup ===" -ForegroundColor Green

# Get project directory
$ProjectDir = Get-Location

# Import validation helpers module
$ValidationModulePath = Join-Path $PSScriptRoot "Validation-Helpers.psm1"
Import-Module $ValidationModulePath -Force -ErrorAction Stop

# Unified secure storage functions
function Set-UnifiedUsptoKey {
    param([string]$ApiKey)

    try {
        Set-Location $ProjectDir
        $pythonExe = "$ProjectDir/.venv/Scripts/python.exe"
        $result = & $pythonExe -c "
import sys
sys.path.insert(0, 'src')
from ptab_mcp.shared_secure_storage import store_uspto_api_key
success = store_uspto_api_key('$ApiKey')
print('SUCCESS' if success else 'FAILED')
" 2>&1 | Out-String

        if (([string]$result).Trim() -eq "SUCCESS") {
            Write-Host "[OK] USPTO API key stored in unified secure storage" -ForegroundColor Green
            Write-Host "     Location: ~/.uspto_api_key (DPAPI encrypted)" -ForegroundColor Yellow
            return $true
        } else {
            Write-Host "[ERROR] Failed to store USPTO API key" -ForegroundColor Red
            return $false
        }
    }
    catch {
        Write-Host "[ERROR] Failed to store USPTO API key: $_" -ForegroundColor Red
        return $false
    }
}

function Set-UnifiedMistralKey {
    param([string]$ApiKey)

    try {
        Set-Location $ProjectDir
        $pythonExe = "$ProjectDir/.venv/Scripts/python.exe"
        $result = & $pythonExe -c "
import sys
sys.path.insert(0, 'src')
from ptab_mcp.shared_secure_storage import store_mistral_api_key
success = store_mistral_api_key('$ApiKey')
print('SUCCESS' if success else 'FAILED')
" 2>&1 | Out-String

        if (([string]$result).Trim() -eq "SUCCESS") {
            Write-Host "[OK] Mistral API key stored in unified secure storage" -ForegroundColor Green
            Write-Host "     Location: ~/.mistral_api_key (DPAPI encrypted)" -ForegroundColor Yellow
            return $true
        } else {
            Write-Host "[ERROR] Failed to store Mistral API key" -ForegroundColor Red
            return $false
        }
    }
    catch {
        Write-Host "[ERROR] Failed to store Mistral API key: $_" -ForegroundColor Red
        return $false
    }
}

function Test-UnifiedKeys {
    try {
        Set-Location $ProjectDir
        # Use here-string for proper Python code formatting
        $pythonCode = @'
import sys
sys.path.insert(0, 'src')
from ptab_mcp.shared_secure_storage import get_uspto_api_key, get_mistral_api_key
uspto_key = get_uspto_api_key()
mistral_key = get_mistral_api_key()
print('USPTO:YES' if uspto_key and len(uspto_key) >= 10 else 'USPTO:NO')
print('MISTRAL:YES' if mistral_key and len(mistral_key) >= 10 else 'MISTRAL:NO')
'@

        $result = uv run python -c $pythonCode 2>&1 | Out-String

        $lines = $result -split "`n" | Where-Object { $_.Trim() -ne "" }
        $usptoFound = $false
        $mistralFound = $false

        foreach ($line in $lines) {
            if ($line -match "USPTO:(YES|NO)") {
                $usptoFound = ($matches[1] -eq "YES")
            }
            if ($line -match "MISTRAL:(YES|NO)") {
                $mistralFound = ($matches[1] -eq "YES")
            }
        }

        return @{
            "USPTO" = $usptoFound
            "MISTRAL" = $mistralFound
        }
    }
    catch {
        return @{
            "USPTO" = $false
            "MISTRAL" = $false
        }
    }
}

# Check if uv is installed, install if not
Write-Host "[INFO] Python NOT required - uv will manage Python automatically" -ForegroundColor Cyan
Write-Host ""
try {
    $uvVersion = uv --version 2>$null
    Write-Host "[OK] uv found: $uvVersion" -ForegroundColor Green
} catch {
    Write-Host "[INFO] uv not found. Installing uv..." -ForegroundColor Yellow

    # Try winget first (preferred method)
    try {
        winget install --id=astral-sh.uv -e
        Write-Host "[OK] uv installed via winget" -ForegroundColor Green
    } catch {
        Write-Host "[INFO] winget failed, trying PowerShell install method..." -ForegroundColor Yellow
        try {
            powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
            Write-Host "[OK] uv installed via PowerShell script" -ForegroundColor Green
        } catch {
            Write-Host "[ERROR] Failed to install uv. Please install manually:" -ForegroundColor Red
            Write-Host "   winget install --id=astral-sh.uv -e" -ForegroundColor Yellow
            Write-Host "   OR visit: https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Yellow
            exit 1
        }
    }

    # Refresh PATH for current session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")

    # Add uv's typical installation paths if not already in PATH
    $uvPaths = @(
        "$env:USERPROFILE\.cargo\bin",           # cargo install location
        "$env:LOCALAPPDATA\Programs\uv\bin",      # winget install location
        "$env:APPDATA\uv\bin"                     # alternative location
    )

    foreach ($uvPath in $uvPaths) {
        if (Test-Path $uvPath) {
            if ($env:PATH -notlike "*$uvPath*") {
                $env:PATH = "$uvPath;$env:PATH"
                Write-Host "[INFO] Added $uvPath to PATH" -ForegroundColor Yellow
            }
        }
    }

    # Verify uv is now accessible
    try {
        $uvVersion = uv --version 2>$null
        Write-Host "[OK] uv is now accessible: $uvVersion" -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] uv installed but not accessible. Please restart PowerShell and run script again." -ForegroundColor Red
        Write-Host "[INFO] Or manually add uv to PATH and continue." -ForegroundColor Yellow
        exit 1
    }
}

# Install dependencies with uv
Write-Host "[INFO] Installing dependencies with uv..." -ForegroundColor Yellow

# Create virtual environment if it doesn't exist or is incomplete
$pythonExePath = ".venv/Scripts/python.exe"
if (-not (Test-Path $pythonExePath)) {
    Write-Host "[INFO] Creating virtual environment..." -ForegroundColor Yellow
    # Remove incomplete .venv if it exists
    if (Test-Path ".venv") {
        Write-Host "[INFO] Removing incomplete virtual environment..." -ForegroundColor Yellow
        Remove-Item -Path ".venv" -Recurse -Force
    }
    try {
        uv venv .venv --python 3.12
        Write-Host "[OK] Virtual environment created at .venv" -ForegroundColor Green

        # Fix: Ensure pyvenv.cfg exists (required for secure storage on older uv versions)
        $pyvenvCfgPath = ".venv\pyvenv.cfg"
        if (-not (Test-Path $pyvenvCfgPath)) {
            Write-Host "[INFO] Creating missing pyvenv.cfg file (older uv version)..." -ForegroundColor Yellow
            try {
                # Get the Python path that uv is using
                $uvPythonInfo = uv python list --only-managed 2>$null | Select-String "cpython-3\.1[2-4].*-windows" | Select-Object -First 1
                if ($uvPythonInfo) {
                    $pythonVersion = ($uvPythonInfo.Line -split '\s+')[1]  # Extract version like "3.12.8"
                    $pythonPath = ($uvPythonInfo.Line -split '\s+')[2]    # Extract path

                    # Create pyvenv.cfg content
                    $pyvenvContent = @"
home = $pythonPath
implementation = CPython
uv = 0.9.11
version_info = $pythonVersion
include-system-site-packages = false
prompt = ptab-mcp
"@
                    Set-Content -Path $pyvenvCfgPath -Value $pyvenvContent -Encoding UTF8
                    Write-Host "[OK] Created pyvenv.cfg file" -ForegroundColor Green
                } else {
                    # Fallback: Create minimal pyvenv.cfg
                    Write-Host "[WARN] Could not detect uv Python path, creating minimal pyvenv.cfg" -ForegroundColor Yellow
                    $fallbackContent = @"
implementation = CPython
version_info = 3.12.8
include-system-site-packages = false
prompt = ptab-mcp
"@
                    Set-Content -Path $pyvenvCfgPath -Value $fallbackContent -Encoding UTF8
                    Write-Host "[OK] Created minimal pyvenv.cfg file" -ForegroundColor Green
                }
            } catch {
                Write-Host "[WARN] Could not create pyvenv.cfg, but continuing..." -ForegroundColor Yellow
            }
        } else {
            Write-Host "[OK] pyvenv.cfg already exists (newer uv version)" -ForegroundColor Green
        }
    } catch {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[OK] Virtual environment already exists at .venv" -ForegroundColor Green
}

# Force uv to use prebuilt wheels (avoid Rust compilation)
Write-Host "[INFO] Installing dependencies with prebuilt wheels (Python 3.12)..." -ForegroundColor Yellow

try {
    # Use Python 3.12 which has guaranteed prebuilt wheels for all dependencies
    # Python 3.14 is too new and doesn't have wheels yet
    uv sync --python 3.12
    Write-Host "[OK] Dependencies installed" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Verify installation and secure storage
Write-Host "[INFO] Verifying installation..." -ForegroundColor Yellow

# Storage test will be performed later, after checking for existing keys

# Test MCP server command
try {
    $commandCheck = Get-Command ptab-mcp -ErrorAction SilentlyContinue
    if ($commandCheck) {
        Write-Host "[OK] Command available: $($commandCheck.Source)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Warning: Command verification failed - check PATH" -ForegroundColor Yellow
        Write-Host "[INFO] You can run the server with: uv run ptab-mcp" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[WARN] Warning: Command verification failed - check PATH" -ForegroundColor Yellow
    Write-Host "[INFO] You can run the server with: uv run ptab-mcp" -ForegroundColor Yellow
}

# API Key Configuration with Unified Storage
Write-Host ""
Write-Host "Unified API Key Configuration" -ForegroundColor Cyan
Write-Host ""

# Check for existing keys first
Write-Host "[INFO] Checking for existing API keys in unified storage..." -ForegroundColor Yellow
$existingKeys = Test-UnifiedKeys

# Test secure storage system ONLY if no keys exist yet (avoids deleting existing keys)
if (-not $existingKeys.USPTO -and -not $existingKeys.MISTRAL) {
    Write-Host "[INFO] Testing secure storage system..." -ForegroundColor Yellow
    try {
        $pythonExe = ".venv/Scripts/python.exe"
        $testCode = @"
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))

try:
    from ptab_mcp.shared_secure_storage import UnifiedSecureStorage
    storage = UnifiedSecureStorage()
    test_result = storage.store_uspto_key('testkey12345678901234567890')
    storage.uspto_key_path.unlink(missing_ok=True)  # Clean up test
    print('SUCCESS' if test_result else 'FAILED')
except Exception as e:
    print(f'ERROR: {e}')
"@

        $storageResult = & $pythonExe -c $testCode 2>$null | Out-String
        if ($storageResult -match "SUCCESS") {
            Write-Host "[OK] Secure storage system working" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Secure storage test failed - API key storage may not work properly" -ForegroundColor Yellow
            Write-Host "[INFO] Error details: $storageResult" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[WARN] Could not test secure storage system" -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] Secure storage system verified (existing keys found)" -ForegroundColor Green
}

# Flags for tracking configuration path
$usingPreexistingDPAPI = $false
$newKeyAsEnv = $false
$finalConfigMethod = "none"  # Track final config method: "dpapi", "traditional", or "none"

if ($existingKeys.USPTO -and $existingKeys.MISTRAL) {
    Write-Host "[OK] Both USPTO and Mistral API keys found in unified storage" -ForegroundColor Green
    Write-Host "[INFO] Configuration: [1] Use existing keys [2] Update keys" -ForegroundColor Cyan
    $keyChoice = Read-Host "Enter choice (1 or 2, default is 1)"

    if ($keyChoice -eq "2") {
        $updateKeys = $true
    } else {
        $updateKeys = $false
        $usingPreexistingDPAPI = $true  # Flag: Using existing DPAPI keys
        Write-Host "[OK] Using existing unified API keys" -ForegroundColor Green
    }
} elseif ($existingKeys.USPTO) {
    Write-Host "[OK] USPTO API key found in unified storage" -ForegroundColor Green
    Write-Host "[INFO] Mistral API key not found" -ForegroundColor Yellow
    Write-Host "[INFO] Configuration: [1] Add Mistral key [2] Use USPTO key only [3] Update both keys" -ForegroundColor Cyan
    $keyChoice = Read-Host "Enter choice (1, 2, or 3, default is 1)"

    if ($keyChoice -eq "2") {
        $updateKeys = $false
        $usingPreexistingDPAPI = $true  # Flag: Using existing USPTO DPAPI key
        Write-Host "[OK] Using existing USPTO key, skipping Mistral" -ForegroundColor Green
    } elseif ($keyChoice -eq "3") {
        $updateKeys = $true
    } else {
        $updateKeys = "mistral_only"
        # Note: Don't set $usingPreexistingDPAPI here because adding new Mistral key
    }
} elseif ($existingKeys.MISTRAL) {
    Write-Host "[WARN] Only Mistral API key found, USPTO key missing (required for PTAB)" -ForegroundColor Yellow
    $updateKeys = "uspto_only"
} else {
    Write-Host "[INFO] No API keys found in unified storage" -ForegroundColor Yellow
    $updateKeys = $true
}

# Collect and store keys if needed
if ($updateKeys -eq $true -or $updateKeys -eq "mistral_only" -or $updateKeys -eq "uspto_only") {
    # Show API key requirements
    Show-ApiKeyRequirements

    if ($updateKeys -eq $true -or $updateKeys -eq "uspto_only") {
        # Collect and validate USPTO API key (REQUIRED for PTAB ODP API)
        $usptoApiKey = Read-UsptoApiKeyWithValidation
        if (-not $usptoApiKey) {
            Write-Host "[ERROR] Failed to obtain valid USPTO API key (REQUIRED for PTAB)" -ForegroundColor Red
            exit 1
        }
    }

    # Collect and validate Mistral API key (optional) - skip for uspto_only
    $mistralApiKey = ""
    if ($updateKeys -eq $true -or $updateKeys -eq "mistral_only") {
        $mistralApiKey = Read-MistralApiKeyWithValidation
        if ($mistralApiKey -eq $null) {
            Write-Host "[ERROR] Failed to obtain valid Mistral API key" -ForegroundColor Red
            exit 1
        }
    }

    # Store keys in unified storage
    Write-Host ""
    Write-Host "[INFO] Storing API keys in unified secure storage..." -ForegroundColor Yellow

    if ($updateKeys -eq $true -and -not [string]::IsNullOrWhiteSpace($usptoApiKey)) {
        if (Set-UnifiedUsptoKey -ApiKey $usptoApiKey) {
            Write-Host "[OK] USPTO API key stored in unified storage" -ForegroundColor Green
            $newKeyAsEnv = $true  # Flag: New key was entered and stored
        } else {
            Write-Host "[ERROR] Failed to store USPTO API key" -ForegroundColor Red
            exit 1
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($mistralApiKey)) {
        if (Set-UnifiedMistralKey -ApiKey $mistralApiKey) {
            Write-Host "[OK] Mistral API key stored in unified storage" -ForegroundColor Green
            $newKeyAsEnv = $true  # Flag: New key was entered and stored
        } else {
            Write-Host "[WARN] Failed to store Mistral API key" -ForegroundColor Yellow
        }
    }

    if ($newKeyAsEnv) {
        Write-Host ""
        Write-Host "[OK] Unified storage benefits:" -ForegroundColor Cyan
        Write-Host "     - Single-key-per-file architecture" -ForegroundColor White
        Write-Host "     - DPAPI encryption (user + machine specific)" -ForegroundColor White
        Write-Host "     - Shared across all USPTO MCPs (FPD/PFW/PTAB/Citations)" -ForegroundColor White
        Write-Host "     - Files: ~/.uspto_api_key, ~/.mistral_api_key" -ForegroundColor White
    }
}

# Get current directory and convert backslashes to forward slashes
$CurrentDir = (Get-Location).Path -replace "\\","/"

# Get or generate shared INTERNAL_AUTH_SECRET using unified storage
Write-Host ""
Write-Host "[INFO] Configuring shared INTERNAL_AUTH_SECRET..." -ForegroundColor Yellow

try {
    Set-Location $ProjectDir

    # Use uv run python (not direct python.exe) to avoid stderr diagnostic messages
    $result = uv run python -c @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from ptab_mcp.shared_secure_storage import ensure_internal_auth_secret

# Get or create shared secret
secret = ensure_internal_auth_secret()
if secret:
    print(secret)
else:
    sys.exit(1)
'@ 2>&1 | Out-String

    $lines = $result -split "`n" | Where-Object { $_.Trim() -ne "" }

    # Filter to find the secret (base64 pattern, 40+ chars, ignoring diagnostic/error messages)
    $internalSecret = ""
    foreach ($line in $lines) {
        $trimmed = ([string]$line).Trim()
        # Match base64 pattern: alphanumeric+/= characters, ends with =, length 40+
        if ($trimmed -match '^[A-Za-z0-9+/]+=*$' -and $trimmed.Length -ge 40) {
            $internalSecret = $trimmed
            break
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($internalSecret)) {
        # Check if this was a newly generated secret or existing one
        if ($result -match "Generating new internal auth secret") {
            Write-Host "[OK] Generated new INTERNAL_AUTH_SECRET (first USPTO MCP installation)" -ForegroundColor Green
            Write-Host "     Location: ~/.uspto_internal_auth_secret (DPAPI encrypted)" -ForegroundColor Yellow
            Write-Host "     This secret will be SHARED across all USPTO MCPs (FPD/PFW/PTAB/Citations)" -ForegroundColor Yellow
        } else {
            Write-Host "[OK] Using existing INTERNAL_AUTH_SECRET from unified storage" -ForegroundColor Green
            Write-Host "     Location: ~/.uspto_internal_auth_secret (DPAPI encrypted)" -ForegroundColor Yellow
            Write-Host "     Shared with other installed USPTO MCPs" -ForegroundColor Yellow
        }
        Write-Host "     This secret authenticates internal MCP communication" -ForegroundColor Yellow
    } else {
        Write-Host "[ERROR] Failed to get or generate INTERNAL_AUTH_SECRET" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "[ERROR] Failed to configure INTERNAL_AUTH_SECRET: $_" -ForegroundColor Red
    exit 1
}

# Ask about Claude Desktop configuration
Write-Host ""
Write-Host "Claude Desktop Configuration" -ForegroundColor Cyan
Write-Host ""

$configureClaudeDesktop = Read-Host "Would you like to configure Claude Desktop integration? (Y/n)"
if ($configureClaudeDesktop -eq "" -or $configureClaudeDesktop -eq "Y" -or $configureClaudeDesktop -eq "y") {

    # Step 5 & 6: Determine configuration method based on flags
    $useSecureStorage = $false
    $configUsptoApiKey = ""
    $configureMistralApiKey = ""

    if ($usingPreexistingDPAPI -and -not $newKeyAsEnv) {
        # Step 5: User is using existing DPAPI keys → Auto-configure as DPAPI (no choice)
        Write-Host ""
        Write-Host "[OK] Using unified secure storage (no API keys in config file)" -ForegroundColor Green
        Write-Host "     API keys loaded automatically from ~/.uspto_api_key and ~/.mistral_api_key" -ForegroundColor Yellow
        Write-Host "     This configuration works with all USPTO MCPs sharing the same keys" -ForegroundColor Yellow
        Write-Host ""
        $useSecureStorage = $true
        $finalConfigMethod = "dpapi"
    } elseif ($newKeyAsEnv) {
        # Step 6: User just entered a new key → Give choice between Secure and Traditional
        Write-Host ""
        Write-Host "Claude Desktop Configuration Method:" -ForegroundColor Cyan
        Write-Host "  [1] Secure Python DPAPI (recommended) - API keys loaded from secure storage" -ForegroundColor White
        Write-Host "  [2] Traditional - API keys stored in Claude Desktop config file" -ForegroundColor White
        Write-Host ""
        $configChoice = Read-Host "Enter choice (1 or 2, default is 1)"

        if ($configChoice -eq "2") {
            # Step 8: Traditional configuration
            Write-Host "[INFO] Using traditional method (API keys in config file)" -ForegroundColor Yellow
            $useSecureStorage = $false
            $finalConfigMethod = "traditional"

            # Retrieve USPTO key from DPAPI storage for config file
            Write-Host "[INFO] Retrieving USPTO API key from DPAPI storage..." -ForegroundColor Yellow
            try {
                Set-Location $ProjectDir
                $pythonExe = "$ProjectDir/.venv/Scripts/python.exe"
                $pythonCode = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from ptab_mcp.shared_secure_storage import get_uspto_api_key
key = get_uspto_api_key()
if key:
    print(key)
else:
    sys.exit(1)
'@
                $result = & $pythonExe -c $pythonCode 2>$null
                if ($LASTEXITCODE -eq 0 -and $result) {
                    $configUsptoApiKey = ([string]$result).Trim()
                    # Validate it looks like a USPTO key (30 chars, lowercase)
                    if ($configUsptoApiKey.Length -eq 30 -and $configUsptoApiKey -cmatch '^[a-z]+$') {
                        Write-Host "[OK] Retrieved USPTO API key from DPAPI storage (30 chars)" -ForegroundColor Green
                    } else {
                        Write-Host "[WARN] Retrieved USPTO key but format looks wrong (length: $($configUsptoApiKey.Length))" -ForegroundColor Yellow
                    }
                } else {
                    $configUsptoApiKey = ""
                    Write-Host "[ERROR] Could not retrieve USPTO API key from DPAPI storage" -ForegroundColor Red
                }
            }
            catch {
                $configUsptoApiKey = ""
                Write-Host "[ERROR] Exception retrieving USPTO API key: $_" -ForegroundColor Red
            }

            # Retrieve Mistral key from DPAPI storage for config file
            Write-Host "[INFO] Retrieving Mistral API key from DPAPI storage..." -ForegroundColor Yellow
            try {
                Set-Location $ProjectDir
                $pythonExe = "$ProjectDir/.venv/Scripts/python.exe"
                $pythonCode = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from ptab_mcp.shared_secure_storage import get_mistral_api_key
key = get_mistral_api_key()
if key:
    print(key)
else:
    sys.exit(1)
'@
                $result = & $pythonExe -c $pythonCode 2>$null
                if ($LASTEXITCODE -eq 0 -and $result) {
                    $configureMistralApiKey = ([string]$result).Trim()
                    # Validate it looks like a Mistral key (32 chars, alphanumeric)
                    if ($configureMistralApiKey.Length -eq 32 -and $configureMistralApiKey -match '^[a-zA-Z0-9]+$') {
                        Write-Host "[OK] Retrieved Mistral API key from DPAPI storage (32 chars)" -ForegroundColor Green
                    } else {
                        Write-Host "[WARN] Retrieved Mistral key but format looks wrong (length: $($configureMistralApiKey.Length))" -ForegroundColor Yellow
                    }
                } else {
                    $configureMistralApiKey = ""
                    Write-Host "[INFO] Mistral API key not found in DPAPI storage (optional)" -ForegroundColor Yellow
                }
            }
            catch {
                $configureMistralApiKey = ""
                Write-Host "[WARN] Exception retrieving Mistral API key: $_" -ForegroundColor Yellow
            }

            if (-not $configUsptoApiKey) {
                Write-Host "[ERROR] Traditional mode requires USPTO API key, but retrieval failed!" -ForegroundColor Red
                Write-Host "[INFO] Falling back to DPAPI mode (keys loaded at runtime)" -ForegroundColor Yellow
                $useSecureStorage = $true
                $finalConfigMethod = "dpapi"
            }
        } else {
            # Step 7: Secure DPAPI configuration
            Write-Host "[OK] Using unified secure storage (no API keys in config file)" -ForegroundColor Green
            Write-Host "     API keys loaded automatically from ~/.uspto_api_key and ~/.mistral_api_key" -ForegroundColor Yellow
            Write-Host "     This configuration works with all USPTO MCPs sharing the same keys" -ForegroundColor Yellow
            Write-Host ""
            $useSecureStorage = $true
            $finalConfigMethod = "dpapi"
        }
    } else {
        # No key configured → Default to DPAPI (secure default, no key to store)
        Write-Host ""
        Write-Host "[OK] Using unified secure storage (no API keys in config file)" -ForegroundColor Green
        Write-Host "     No API keys configured yet" -ForegroundColor Yellow
        Write-Host ""
        $useSecureStorage = $true
        $finalConfigMethod = "dpapi"
    }

    # Function to generate env section based on configuration choice
    function Get-EnvSection {
        param($indent = "        ")

        $envItems = @()

        if ($useSecureStorage) {
            # Secure storage - no API keys in config
            # PTAB-specific: Optional local proxy port (8083) and centralized proxy detection
            $envItems += "$indent`"PTAB_PROXY_PORT`": `"8083`""
            $envItems += "$indent`"CENTRALIZED_PROXY_PORT`": `"8080`""
            $envItems += "$indent`"INTERNAL_AUTH_SECRET`": `"$internalSecret`""
            $envItems += "$indent`"ENABLE_ALWAYS_ON_PROXY`": `"false`""
        } else {
            # Traditional - API keys in config
            if ($configUsptoApiKey) { $envItems += "$indent`"USPTO_API_KEY`": `"$configUsptoApiKey`"" }
            if ($configureMistralApiKey) { $envItems += "$indent`"MISTRAL_API_KEY`": `"$configureMistralApiKey`"" }
            $envItems += "$indent`"PTAB_PROXY_PORT`": `"8083`""
            $envItems += "$indent`"CENTRALIZED_PROXY_PORT`": `"8080`""
            $envItems += "$indent`"INTERNAL_AUTH_SECRET`": `"$internalSecret`""
            $envItems += "$indent`"ENABLE_ALWAYS_ON_PROXY`": `"false`""
        }

        return $envItems -join ",`n"
    }

    # Function to generate server JSON entry
    function Get-ServerJson {
        param($indent = "    ")

        $envSection = Get-EnvSection -indent "      "

        return @"
$indent"uspto_ptab": {
$indent  "command": "$CurrentDir/.venv/Scripts/python.exe",
$indent  "args": [
$indent    "-m",
$indent    "ptab_mcp.main"
$indent  ],
$indent  "cwd": "$CurrentDir",
$indent  "env": {
$envSection
$indent  }
$indent}
"@
    }

    # Claude Desktop config location
    $ClaudeConfigDir = "$env:APPDATA\Claude"
    $ClaudeConfigFile = "$ClaudeConfigDir\claude_desktop_config.json"

    Write-Host "[INFO] Claude Desktop config location: $ClaudeConfigFile" -ForegroundColor Yellow

    if (Test-Path $ClaudeConfigFile) {
        Write-Host "[INFO] Existing Claude Desktop config found" -ForegroundColor Yellow
        Write-Host "[INFO] Merging USPTO PTAB MCP configuration with existing config..." -ForegroundColor Yellow

        try {
            # Read existing config as raw text
            $existingJsonText = Get-Content $ClaudeConfigFile -Raw

            # Backup the original file
            $backupFile = "$ClaudeConfigFile.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
            Copy-Item $ClaudeConfigFile $backupFile
            Write-Host "[INFO] Backup created: $backupFile" -ForegroundColor Yellow

            # Try to parse JSON, with better error handling for malformed JSON
            try {
                $existingConfig = $existingJsonText | ConvertFrom-Json
            } catch {
                Write-Host "[ERROR] Existing Claude Desktop config has JSON syntax errors" -ForegroundColor Red
                Write-Host "[ERROR] Common issue: Missing comma after closing braces '}' between MCP server sections" -ForegroundColor Red
                Write-Host "[INFO] Please fix the JSON syntax and run the setup script again" -ForegroundColor Yellow
                Write-Host "[INFO] Your backup is saved at: $backupFile" -ForegroundColor Yellow
                Write-Host ""
                Write-Host "Quick fix: Look for lines like this pattern and add missing commas:" -ForegroundColor Yellow
                Write-Host "    }" -ForegroundColor White
                Write-Host "    `"next_server`": {" -ForegroundColor White
                Write-Host ""
                Write-Host "Should be:" -ForegroundColor Yellow
                Write-Host "    }," -ForegroundColor Green
                Write-Host "    `"next_server`": {" -ForegroundColor White
                Write-Host ""
                exit 1
            }

            # Check if mcpServers exists, create if not
            if (-not $existingConfig.mcpServers) {
                # Empty config - create from scratch respecting user's configuration choice
                $serverJson = Get-ServerJson
                $jsonConfig = @"
{
  "mcpServers": {
$serverJson
  }
}
"@
            } else {
                # Has existing servers - need to merge manually
                # Build the uspto_ptab section respecting user's configuration choice
                $ptabJson = Get-ServerJson

                # Get all existing server names
                $existingServers = $existingConfig.mcpServers.PSObject.Properties.Name

                # Build the mcpServers object with all servers
                $serverEntries = @()

                foreach ($serverName in $existingServers) {
                    if ($serverName -ne "uspto_ptab") {
                        # Convert to JSON without compression for readability
                        $serverJson = $existingConfig.mcpServers.$serverName | ConvertTo-Json -Depth 10

                        # Split into lines and format properly
                        $jsonLines = $serverJson -split "`n"

                        # First line: "serverName": {
                        $formattedEntry = "    `"$serverName`": $($jsonLines[0])"

                        # Remaining lines: indent by 4 spaces
                        for ($i = 1; $i -lt $jsonLines.Length; $i++) {
                            $formattedEntry += "`n    $($jsonLines[$i])"
                        }

                        # Add the formatted server entry
                        $serverEntries += $formattedEntry
                    }
                }

                # Add uspto_ptab
                $serverEntries += $ptabJson.TrimEnd()

                $allServers = $serverEntries -join ",`n"

                $jsonConfig = @"
{
  "mcpServers": {
$allServers
  }
}
"@
            }

            # Write with UTF8 without BOM
            $utf8NoBom = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($ClaudeConfigFile, $jsonConfig, $utf8NoBom)

            Write-Host "[OK] Successfully merged USPTO PTAB MCP configuration!" -ForegroundColor Green
            Write-Host "[OK] Your existing MCP servers have been preserved" -ForegroundColor Green
            Write-Host "[INFO] Configuration backup saved at: $backupFile" -ForegroundColor Yellow

        } catch {
            Write-Host "[ERROR] Failed to merge configuration: $_" -ForegroundColor Red
            Write-Host "[ERROR] Details: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host ""
            Write-Host "Please manually add this configuration to: $ClaudeConfigFile" -ForegroundColor Yellow
            Write-Host ""
            Write-Host "Add this to your mcpServers section:" -ForegroundColor White

            # Manual JSON string for display respecting user's configuration choice
            $manualJson = Get-ServerJson -indent ""
            Write-Host $manualJson -ForegroundColor Cyan
            Write-Host ""
            if (Test-Path $backupFile) {
                Write-Host "Your backup is saved at: $backupFile" -ForegroundColor Yellow
            }
            exit 1
        }

    } else {
        # Create new config file
        Write-Host "[INFO] Creating new Claude Desktop config..." -ForegroundColor Yellow

        # Create directory if it doesn't exist
        if (-not (Test-Path $ClaudeConfigDir)) {
            New-Item -ItemType Directory -Path $ClaudeConfigDir -Force | Out-Null
        }

        # Create config respecting user's configuration choice
        $serverJson = Get-ServerJson
        $jsonConfig = @"
{
  "mcpServers": {
$serverJson
  }
}
"@
        # Write with UTF8 without BOM
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($ClaudeConfigFile, $jsonConfig, $utf8NoBom)

        Write-Host "[OK] Created new Claude Desktop config" -ForegroundColor Green
    }

    Write-Host "[OK] Claude Desktop configuration complete!" -ForegroundColor Green
}

# Final summary
Write-Host ""
Write-Host "Windows setup complete!" -ForegroundColor Green
Write-Host "Please restart Claude Desktop to load the MCP server" -ForegroundColor Yellow
Write-Host ""
Write-Host "Configuration Summary:" -ForegroundColor Cyan

# Check final key status
$finalKeys = Test-UnifiedKeys
if ($finalKeys.USPTO) {
    Write-Host "  [OK] USPTO API Key: Stored in unified secure storage" -ForegroundColor Green
    Write-Host "       Location: ~/.uspto_api_key (DPAPI encrypted)" -ForegroundColor Yellow
} else {
    Write-Host "  [WARN] USPTO API Key: Not found in unified storage (REQUIRED for PTAB)" -ForegroundColor Yellow
}

if ($finalKeys.MISTRAL) {
    Write-Host "  [OK] Mistral API Key: Stored in unified secure storage" -ForegroundColor Green
    Write-Host "       Location: ~/.mistral_api_key (DPAPI encrypted)" -ForegroundColor Yellow
} else {
    Write-Host "  [INFO] Mistral API Key: Not set (PyPDF2 fallback for text PDFs)" -ForegroundColor Yellow
}

Write-Host "  [OK] Storage Architecture: Single-key-per-file (shared across USPTO MCPs)" -ForegroundColor Green
Write-Host "  [OK] Local Proxy Port: 8083 (optional, auto-starts if needed)" -ForegroundColor Green
Write-Host "  [OK] Centralized Proxy: Port 8080 detection (PFW integration)" -ForegroundColor Green
Write-Host "  [OK] Installation Directory: $CurrentDir" -ForegroundColor Green
Write-Host ""
Write-Host "Available Tools (15):" -ForegroundColor Cyan
Write-Host "  Trials Search:" -ForegroundColor White
Write-Host "    - search_trials_minimal (ultra-fast discovery)" -ForegroundColor White
Write-Host "    - search_trials_balanced (detailed analysis)" -ForegroundColor White
Write-Host "    - search_trials_complete (full details)" -ForegroundColor White
Write-Host "  Appeals Search:" -ForegroundColor White
Write-Host "    - search_appeals_minimal (ex parte appeal discovery)" -ForegroundColor White
Write-Host "    - search_appeals_balanced (detailed appeal analysis)" -ForegroundColor White
Write-Host "    - search_appeals_complete (full appeal details)" -ForegroundColor White
Write-Host "  Interferences Search:" -ForegroundColor White
Write-Host "    - search_interferences_minimal (interference discovery)" -ForegroundColor White
Write-Host "    - search_interferences_balanced (interference analysis)" -ForegroundColor White
Write-Host "    - search_interferences_complete (full interference details)" -ForegroundColor White
Write-Host "  Document Operations:" -ForegroundColor White
Write-Host "    - ptab_get_documents (list all documents)" -ForegroundColor White
Write-Host "    - ptab_get_document_download (browser-accessible PDFs)" -ForegroundColor White
Write-Host "    - ptab_get_document_content (OCR text extraction)" -ForegroundColor White
Write-Host "  Utility & Guidance:" -ForegroundColor White
Write-Host "    - ptab_get_guidance (selective workflow guidance)" -ForegroundColor White
Write-Host "    - ptab_get_field_configs (view field configurations)" -ForegroundColor White
Write-Host ""
Write-Host "Proxy Architecture:" -ForegroundColor Cyan
Write-Host "  Local Proxy: Port 8083 (auto-starts when needed)" -ForegroundColor Yellow
Write-Host "  Centralized Detection: Tries PFW proxy on port 8080 first" -ForegroundColor Yellow
Write-Host "  Automatic Fallback: Uses local proxy if centralized unavailable" -ForegroundColor Yellow
Write-Host ""
Write-Host "Key Management:" -ForegroundColor Cyan
Write-Host "  Manage keys: ./deploy/manage_api_keys.ps1" -ForegroundColor Yellow
Write-Host "  Cross-MCP:   Keys shared with FPD, PFW, and Citations MCPs" -ForegroundColor White
Write-Host ""
Write-Host "Test with: search_trials_minimal" -ForegroundColor Yellow
Write-Host "Learn workflows: ptab_get_guidance(section='workflows_complete')" -ForegroundColor Yellow
Write-Host ""
