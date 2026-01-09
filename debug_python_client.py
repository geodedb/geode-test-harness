#!/usr/bin/env python3
"""Debug script for Python client."""

import asyncio
import sys
from pathlib import Path

# Add Python client to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from geode_client import Client

async def main():
    print("Creating client...")
    client = Client(
        host="localhost",
        port=54321,
        skip_verify=True
    )

    print("Creating connection...")
    try:
        conn = await client.connect()
        print(f"Connection established: {conn}")
        print(f"Connected: {conn._connected}")

        print("\nExecuting simple query...")
        page, pager = await conn.query("RETURN 1 AS x")
        print(f"Got page with {len(page.rows)} rows")
        print(f"Page columns: {[col.name for col in page.columns]}")
        print(f"Page data: {page.rows}")

        print("\nClosing connection...")
        await conn.close()
        print("Connection closed successfully")

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
