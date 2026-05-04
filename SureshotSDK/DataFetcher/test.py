"""
Integration test for DataFetcherPool.

Tests the async Stagehand session pool directly (bypasses the HTTP service layer).
Run:  python -m SureshotSDK.DataFetcher.test [SYMBOL]
Requires: BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID, MODEL_API_KEY env vars
"""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


async def main():
    from SureshotSDK.DataFetcher.pool import DataFetcherPool

    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"

    print(f"Initializing DataFetcherPool (pool_size=1)...")
    pool = DataFetcherPool(pool_size=1)
    await pool.initialize()

    print(f"Fetching bar for {symbol}...")
    bar = await pool.get_current_bar(symbol)

    if bar:
        print(f"  close (price) : {bar['c']}")
        print(f"  timestamp ms  : {bar['t']}")
    else:
        print("FAILED — no bar returned")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
