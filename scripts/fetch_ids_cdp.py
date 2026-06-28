#!/usr/bin/env python3
"""Collect all saved-job IDs by attaching to a running Chrome via CDP.

Prereq: launch Chrome with remote debugging and log into LinkedIn, e.g.
  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
    --remote-debugging-port=9222 --user-data-dir="$HOME/li-chrome-profile"

Usage: uv run python scripts/fetch_ids_cdp.py [stage]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import browser as browser_mod

stage = sys.argv[1] if len(sys.argv) > 1 else "saved"
ids = browser_mod.fetch_saved_job_ids_cdp(stage=stage)
print(f"\nTOTAL {stage} job IDs: {len(ids)}")
print(ids)
