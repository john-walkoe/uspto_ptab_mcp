#!/usr/bin/env python3
"""
Merge USPTO PTAB MCP configuration into ~/.claude.json

This script specifically handles the case where Claude Code uses ~/.claude.json
instead of ~/.config/Claude/claude_desktop_config.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def main():
    # Determine project directory
    project_dir = Path.cwd()
    if not (project_dir / "pyproject.toml").exists():
        print("ERROR: Must run from uspto_ptab_mcp directory")
        sys.exit(1)

    # Claude config file location
    claude_config = Path.home() / ".claude.json"

    if not claude_config.exists():
        print(f"ERROR: {claude_config} does not exist")
        print("Claude Code may not be configured yet")
        sys.exit(1)

    # Backup existing config
    backup_path = Path(str(claude_config) + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    print(f"Creating backup: {backup_path}")
    backup_path.write_text(claude_config.read_text())

    # Load existing config
    print(f"Reading: {claude_config}")
    with claude_config.open('r') as f:
        config = json.load(f)

    # Ensure mcpServers exists
    if 'mcpServers' not in config:
        config['mcpServers'] = {}

    # Check if uspto_ptab already exists
    if 'uspto_ptab' in config['mcpServers']:
        print("WARN: uspto_ptab already exists in config - will overwrite")

    # Add or update uspto_ptab configuration
    config['mcpServers']['uspto_ptab'] = {
        'command': 'uv',
        'args': [
            '--directory',
            str(project_dir),
            'run',
            'ptab-mcp'
        ],
        'env': {
            'PTAB_PROXY_PORT': '8083',
            'ENABLE_ALWAYS_ON_PROXY': 'true'
        }
    }

    # Write updated config
    print(f"Writing: {claude_config}")
    with claude_config.open('w') as f:
        json.dump(config, f, indent=2)

    # Set secure permissions
    claude_config.chmod(0o600)

    print()
    print("✓ SUCCESS: USPTO PTAB MCP configuration added to ~/.claude.json")
    print()
    print("Next steps:")
    print("  1. Restart Claude Code")
    print("  2. Run: claude mcp list")
    print("  3. Verify uspto_ptab appears in the list")
    print()

if __name__ == '__main__':
    main()
