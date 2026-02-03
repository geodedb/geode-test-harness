#!/usr/bin/env python3
"""Direct test of geode binary."""

import os
import subprocess

# Test the binary directly
binary = "/home/benji/src/gl/devnw/codepros/geode/zig-out/bin/geode"

if not os.path.exists(binary):
    print(f"Binary not found: {binary}")
    exit(1)

print(f"Testing binary: {binary}")

# Test help command
try:
    result = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=5)
    print(f"Exit code: {result.returncode}")
    print(f"Stdout length: {len(result.stdout)}")
    print(f"First 200 chars of stdout: {result.stdout[:200]}")
    print(f"Stderr length: {len(result.stderr)}")
    if result.stderr:
        print(f"Stderr: {result.stderr[:200]}")
except subprocess.TimeoutExpired:
    print("Command timed out!")
except Exception as e:
    print(f"Error: {e}")
