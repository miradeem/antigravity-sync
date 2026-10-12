#!/bin/bash
# Convenient Bash wrapper for agy_sync.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/agy_sync.py" "$@"
