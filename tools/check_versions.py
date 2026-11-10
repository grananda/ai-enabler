#!/usr/bin/env python3
"""Compatibility entry point for the changes-fragment policy (not per-MR bumps).

Usage: python tools/check_versions.py [base] [release.py validate flags...]
Default base remains origin/main; missing refs fail closed.
"""
import sys
from release import main

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and not args[0].startswith("-"):
        args = ["--base", args[0], *args[1:]]
    sys.exit(main(["validate", *args]))
