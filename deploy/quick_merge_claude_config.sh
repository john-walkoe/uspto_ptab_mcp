#!/bin/bash

# Quick script to merge PTAB config into existing ~/.claude.json
# This is a wrapper around merge_ptab_to_claude_json.py

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run the Python merge script
python3 "$SCRIPT_DIR/merge_ptab_to_claude_json.py"
