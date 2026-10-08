"""Closed-loop transfer traffic against payments-api. Runs locally or as a Cloud Run job.

  BASE_URL=https://payments-api-xxx.run.app CONCURRENCY=40 DURATION_S=900 python loadgen.py
"""

from __future__ import annotations

import asyncio
import os
import random
import time

import httpx

BASE = os.environ["BASE_URL"].rstrip("/")
CONC = int(os.environ.get("CONCURRENCY", "40"))
DURATION = int(os.environ.get("DURATION_S", "900"))
TOKEN = os.environ.get("ID_TOKEN")  # set when the service requires authentication


async def worker(client: httpx.AsyncClient, stats: dict, stop: float) -> None:
    rng = random.Random()
    while time.time() < stop:
        a, b = rng.sample(range(1, 201), 2)
        try:
            r = await client.post("/v1/transfers", json={
                "from_account": f"acc_{a:04d}", "to_account": f"acc_{b:04d}",
                "amount": round(rng.uniform(5, 900), 2)})
            stats[r.status_code] = stats.get(r.status_code, 0) + 1
        except httpx.HTTPError:
            stats["net_err"] = stats.get("net_err", 0) + 1
        await asyncio.sleep(rng.uniform(0.05, 0.25))


async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    stats: dict = {}
    stop = time.time() + DURATION
    async with httpx.AsyncClient(base_url=BASE, timeout=15, headers=headers) as client:
        tasks = [asyncio.create_task(worker(client, stats, stop)) for _ in range(CONC)]
        while time.time() < stop:
            await asyncio.sleep(10)
            print(time.strftime("%H:%M:%S"), dict(sorted(stats.items(), key=str)), flush=True)
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
