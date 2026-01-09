#!/usr/bin/env python3
"""Quick test of Python client connection."""

import asyncio
import sys
from pathlib import Path

# Add Python client to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from geode_client import Client


async def test_connection():
    """Test basic connection."""
    print("Creating client...")
    client = Client(host="localhost", port=56691, skip_verify=True)

    print("Connecting...")
    try:
        async with client.connection() as conn:
            print(f"Connected! conn={conn}")
            print("Sending query...")
            page, _ = await conn.query("RETURN 1 AS x")
            print(f"Got response: {page.rows}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_connection())
