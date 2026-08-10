#!/bin/sh
# Double-click installer for macOS.
cd "$(dirname "$0")" || exit 1
exec /usr/bin/python3 scripts/install.py
