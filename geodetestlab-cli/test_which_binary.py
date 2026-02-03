#!/usr/bin/env python3
"""Test which binary is being selected."""

import sys

sys.path.insert(0, "/home/benji/src/gl/devnw/codepros/geode/geodetestlab/geodetestlab")

from core.utils import find_geode_binary

try:
    binary = find_geode_binary()
    print(f"Selected binary: {binary}")
except Exception as e:
    print(f"Error: {e}")
