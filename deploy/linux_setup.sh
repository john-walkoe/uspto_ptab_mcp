#!/bin/bash

set -e

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Helper functions
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }

# Load validation helpers
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/validation-helpers.sh"

echo -e "${GREEN}=== USPTO PTAB MCP - Linux Setup ===${NC}"
echo ""

# Get project directory for later use
PROJECT_DIR=$(pwd)

# Step 1: Check/Install uv
log_info "UV will handle Python installation automatically"

if ! command -v uv &> /dev/null; then
    log_info "uv not found. Installing uv package manager..."

    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        # Add uv to PATH for current session
        export PATH="$HOME/.cargo/bin:$PATH"

        # Verify installation
        if command -v uv &> /dev/null; then
            UV_VERSION=$(uv --version)
            log_success "uv installed successfully: $UV_VERSION"
        else
            log_error "Failed to install uv. Please install manually:"
            echo -e "${YELLOW}   curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
            exit 1
        fi
    else
        log_error "Failed to install uv automatically"
        log_info "Please install uv manually and re-run this script"
        exit 1
    fi
else
    UV_VERSION=$(uv --version)
    log_info "uv found: $UV_VERSION"
fi

# Step 2: Install project dependencies
log_info "Installing project dependencies with uv..."

if uv sync; then
    log_success "Dependencies installed successfully"
else
    log_error "Failed to install dependencies"
    exit 1
fi

# Step 3: Install package in editable mode
log_info "Installing USPTO PTAB MCP package..."

if uv pip install -e .; then
    log_success "Package installed successfully"
else
    log_error "Failed to install package"
    exit 1
fi

# Step 4: Verify installation
log_info "Verifying installation..."

if command -v ptab-mcp &> /dev/null; then
    log_success "Command available: $(which ptab-mcp)"
elif uv run python -c "import src.ptab_mcp; print('Import successful')" &> /dev/null; then
    log_success "Package import successful - can run with: uv run ptab-mcp"
else
    log_warning "Installation verification failed"
    log_info "You can run the server with: uv run ptab-mcp"
fi

echo ""

# Step 5: API Key Configuration
echo -e "${GREEN}[INFO] API Key Configuration${NC}"
echo ""

log_info "USPTO PTAB MCP requires two API keys:"
log_info "1. USPTO Open Data Portal API key (required)"
log_info "2. Mistral API key (optional - for OCR document extraction)"
echo ""
log_info "Get your free USPTO API key from: https://data.uspto.gov/myodp/"
log_info "Get your Mistral API key from: https://console.mistral.ai/"
echo ""

# Prompt for USPTO API key with validation (uses secure hidden input)
USPTO_API_KEY=$(prompt_and_validate_uspto_key)
if [[ -z "$USPTO_API_KEY" ]]; then
    log_error "Failed to obtain valid USPTO API key"
    exit 1
fi

log_success "USPTO API key validated and configured"
echo ""

# Prompt for Mistral API key (optional)
echo ""
log_info "Mistral API key configuration (optional - for OCR document extraction)"
read -p "Would you like to configure Mistral API key now? (Y/n): " CONFIGURE_MISTRAL
CONFIGURE_MISTRAL=${CONFIGURE_MISTRAL:-Y}

MISTRAL_API_KEY=""
if [[ "$CONFIGURE_MISTRAL" =~ ^[Yy]$ ]]; then
    MISTRAL_API_KEY=$(prompt_and_validate_mistral_key)
    if [[ -z "$MISTRAL_API_KEY" ]]; then
        log_warning "Failed to obtain valid Mistral API key - skipping"
        log_info "You can configure it later using: ./deploy/manage_api_keys.sh"
    else
        log_success "Mistral API key validated and configured"
    fi
else
    log_info "Skipping Mistral API key configuration"
    log_info "You can configure it later using: ./deploy/manage_api_keys.sh"
fi

# Step 6: Store API keys in SECURE storage (NOT in config file!)
echo ""
log_info "Storing API keys in secure storage..."
log_info "Location: ~/.uspto_api_key and ~/.mistral_api_key (file permissions: 600)"
echo ""

# Store USPTO key using environment variable (more secure than command line)
export SETUP_USPTO_KEY="$USPTO_API_KEY"
if [[ -n "$MISTRAL_API_KEY" ]]; then
    export SETUP_MISTRAL_KEY="$MISTRAL_API_KEY"
fi

STORE_RESULT=$(python3 << 'EOF'
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path.cwd() / 'src'))

try:
    from ptab_mcp.shared_secure_storage import store_uspto_api_key, store_mistral_api_key

    # Store USPTO key (required)
    uspto_key = os.environ.get('SETUP_USPTO_KEY', '')
    if not uspto_key:
        print('ERROR: No USPTO API key provided')
        sys.exit(1)

    if not store_uspto_api_key(uspto_key):
        print('ERROR: Failed to store USPTO key')
        sys.exit(1)

    # Store Mistral key (optional)
    mistral_key = os.environ.get('SETUP_MISTRAL_KEY', '')
    if mistral_key:
        if not store_mistral_api_key(mistral_key):
            print('ERROR: Failed to store Mistral key')
            sys.exit(1)
        print('SUCCESS:BOTH')
    else:
        print('SUCCESS:USPTO_ONLY')

except Exception as e:
    print(f'ERROR: {str(e)}')
    sys.exit(1)
EOF
)

# Clear environment variables immediately
unset SETUP_USPTO_KEY
unset SETUP_MISTRAL_KEY

if [[ "$STORE_RESULT" == "SUCCESS:BOTH" ]]; then
    log_success "USPTO and Mistral API keys stored in secure storage"
    log_info "    USPTO Location: ~/.uspto_api_key"
    log_info "    Mistral Location: ~/.mistral_api_key"
    log_info "    Permissions: 600 (owner read/write only)"

    # CRITICAL SECURITY: Set file permissions on both API key files
    if [ -f "$HOME/.uspto_api_key" ]; then
        set_secure_file_permissions "$HOME/.uspto_api_key"
    fi

    if [ -f "$HOME/.mistral_api_key" ]; then
        set_secure_file_permissions "$HOME/.mistral_api_key"
    fi

elif [[ "$STORE_RESULT" == "SUCCESS:USPTO_ONLY" ]]; then
    log_success "USPTO API key stored in secure storage"
    log_info "    Location: ~/.uspto_api_key"
    log_info "    Permissions: 600 (owner read/write only)"

    # CRITICAL SECURITY: Set file permissions on USPTO API key file
    if [ -f "$HOME/.uspto_api_key" ]; then
        set_secure_file_permissions "$HOME/.uspto_api_key"
    fi

else
    log_error "Failed to store API keys: $STORE_RESULT"
    exit 1
fi

# Step 7: Claude Code Configuration
echo ""
log_info "Claude Code Configuration"
echo ""

read -p "Would you like to configure Claude Code integration? (Y/n): " CONFIGURE_CLAUDE
CONFIGURE_CLAUDE=${CONFIGURE_CLAUDE:-Y}

if [[ "$CONFIGURE_CLAUDE" =~ ^[Yy]$ ]]; then
    # Claude Code config location detection (Linux/macOS)
    # Some installations use ~/.claude.json, others use ~/.config/Claude/claude_desktop_config.json
    if [ -f "$HOME/.claude.json" ]; then
        CLAUDE_CONFIG_FILE="$HOME/.claude.json"
        CLAUDE_CONFIG_DIR="$(dirname "$CLAUDE_CONFIG_FILE")"
        log_info "Detected existing Claude config: $CLAUDE_CONFIG_FILE"
    else
        CLAUDE_CONFIG_DIR="$HOME/.config/Claude"
        CLAUDE_CONFIG_FILE="$CLAUDE_CONFIG_DIR/claude_desktop_config.json"
        log_info "Using standard Claude config location: $CLAUDE_CONFIG_FILE"
    fi

    # Create config directory if it doesn't exist (but only if not $HOME)
    if [ ! -d "$CLAUDE_CONFIG_DIR" ]; then
        mkdir -p "$CLAUDE_CONFIG_DIR"
        log_success "Created Claude config directory: $CLAUDE_CONFIG_DIR"
    fi

    # CRITICAL SECURITY: Set directory permissions (700) - but skip if config is directly in $HOME
    if [ "$CLAUDE_CONFIG_DIR" != "$HOME" ]; then
        set_secure_directory_permissions "$CLAUDE_CONFIG_DIR"
    fi

    if [ -f "$CLAUDE_CONFIG_FILE" ]; then
        log_info "Existing Claude Desktop config found"
        log_info "Merging USPTO PTAB configuration with existing config..."

        # Backup the original file
        BACKUP_FILE="${CLAUDE_CONFIG_FILE}.backup_$(date +%Y%m%d_%H%M%S)"
        cp "$CLAUDE_CONFIG_FILE" "$BACKUP_FILE"
        log_info "Backup created: $BACKUP_FILE"

        # Use Python to merge JSON configuration (API key NOT included - in secure storage)
        MERGE_SCRIPT="
import json
import sys

try:
    # Read existing config
    with open('$CLAUDE_CONFIG_FILE', 'r') as f:
        config = json.load(f)

    # Ensure mcpServers exists
    if 'mcpServers' not in config:
        config['mcpServers'] = {}

    # Add or update uspto_ptab server
    # NOTE: API keys are NOT in config - they're loaded from secure storage
    server_config = {
        'command': 'uv',
        'args': [
            '--directory',
            '$PROJECT_DIR',
            'run',
            'ptab-mcp'
        ],
        'env': {
            'PTAB_PROXY_PORT': '8083',
            'ENABLE_ALWAYS_ON_PROXY': 'true'
        }
    }

    config['mcpServers']['uspto_ptab'] = server_config

    # Write merged config
    with open('$CLAUDE_CONFIG_FILE', 'w') as f:
        json.dump(config, f, indent=2)

    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"

        if echo "$MERGE_SCRIPT" | python3; then
            log_success "Successfully merged USPTO PTAB configuration!"
            log_success "Your existing MCP servers have been preserved"
        else
            log_error "Failed to merge config"
            log_info "Please manually add the configuration to $CLAUDE_CONFIG_FILE"
            exit 1
        fi

    else
        # Create new config file using Python for safe JSON generation
        log_info "Creating new Claude Desktop config..."

        CREATE_CONFIG_SCRIPT="
import json
import sys

try:
    # NOTE: API keys are NOT in config - they're loaded from secure storage
    config = {
        'mcpServers': {
            'uspto_ptab': {
                'command': 'uv',
                'args': [
                    '--directory',
                    '$PROJECT_DIR',
                    'run',
                    'ptab-mcp'
                ],
                'env': {
                    'PTAB_PROXY_PORT': '8083',
                    'ENABLE_ALWAYS_ON_PROXY': 'true'
                }
            }
        }
    }

    # Write config file
    with open('$CLAUDE_CONFIG_FILE', 'w') as f:
        json.dump(config, f, indent=2)

    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"

        if echo "$CREATE_CONFIG_SCRIPT" | python3; then
            log_success "Created new Claude Desktop config"
        else
            log_error "Failed to create config file"
            exit 1
        fi
    fi

    # CRITICAL SECURITY FIX: Set restrictive file permissions on config file
    if [ -f "$CLAUDE_CONFIG_FILE" ]; then
        set_secure_file_permissions "$CLAUDE_CONFIG_FILE"
    fi

    log_success "Claude Code configuration complete!"

    # Display configuration method used
    echo ""
    log_success "Security Configuration:"
    log_info "  - USPTO API key stored in secure storage: ~/.uspto_api_key"
    if [ -f "$HOME/.mistral_api_key" ]; then
        log_info "  - Mistral API key stored in secure storage: ~/.mistral_api_key"
    fi
    log_info "  - File permissions: 600 (owner read/write only)"
    log_info "  - API keys NOT in Claude Desktop config file"
    log_info "  - Config directory permissions: 700 (owner only)"
    log_info "  - Shared storage across all USPTO MCPs (PFW/PTAB/FPD/Citations)"
else
    log_info "Skipping Claude Code configuration"
    log_info "You can manually configure later by editing $CLAUDE_CONFIG_FILE"
    log_info "See README.md for configuration template"
fi

echo ""

# Step 8: Final Summary
echo -e "${GREEN}[OK] Linux setup complete!${NC}"
log_warning "Please restart Claude Code to load the MCP server"

echo ""
log_info "Configuration Summary:"
log_success "USPTO API Key: Stored in secure storage (~/.uspto_api_key)"
if [ -f "$HOME/.mistral_api_key" ]; then
    log_success "Mistral API Key: Stored in secure storage (~/.mistral_api_key)"
else
    log_warning "Mistral API Key: Not configured (optional - for OCR)"
fi
log_success "Dependencies: Installed"
log_success "Package: Available as command"
log_success "Installation Directory: $PROJECT_DIR"
log_success "Security: File permissions 600 (owner only)"
log_success "Security: Config directory permissions 700 (owner only)"

echo ""
log_info "Test the server:"
echo "  uv run ptab-mcp --help"

echo ""
log_info "Test with Claude Code:"
echo "  Ask Claude: 'Use PTAB_search_trials_minimal to find all IPR proceedings for Apple Inc'"
echo "  Ask Claude: 'Use PTAB_get_guidance to learn about PTAB MCP features'"
echo "  Ask Claude: 'Use PTAB_get_field_configs to view available field configurations'"

echo ""
log_info "Verify MCP is running:"
echo "  claude mcp list"

echo ""
log_info "Manage API keys later:"
echo "  (Future enhancement - currently use deployment script to update)"

echo ""
echo -e "${GREEN}=== Setup Complete! ===${NC}"
echo ""
