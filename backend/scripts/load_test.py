"""Small repeatable HTTP load gate for API replicas.

Example: ``python -m scripts.load_test --requests 1000 --concurrency 100``.
This validates request-path capacity; extraction throughput is intentionally
measured separately because it is bounded by model-token quota and worker size.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import time

import httpx


def percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    if not values:
        return math.inf
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


async def run(url: str, requests: int, concurrency: int) -> tuple[list[float], int, float]:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    failures = 0
    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=concurrency,
    )

    async with httpx.AsyncClient(limits=limits, timeout=20) as client:
        async def one() -> None:
            nonlocal failures
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    if response.status_code >= 400:
                        failures += 1
                except Exception:
                    failures += 1
                finally:
                    latencies.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(requests)))
        elapsed = time.perf_counter() - started
    return latencies, failures, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Concurrent BidSense API load gate")
    parser.add_argument("--url", default="http://127.0.0.1:8100/api/notifications?limit=1")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--max-p95-ms", type=float, default=6000)
    args = parser.parse_args()
    latencies, failures, elapsed = asyncio.run(
        run(args.url, args.requests, args.concurrency)
    )
    print(f"requests={args.requests} concurrency={args.concurrency} failures={failures}")
    print(f"elapsed={elapsed:.2f}s throughput={args.requests / elapsed:.1f} req/s")
    print(
        f"latency ms: mean={statistics.mean(latencies):.1f} "
        f"p50={percentile(latencies, .5):.1f} "
        f"p95={percentile(latencies, .95):.1f} "
        f"p99={percentile(latencies, .99):.1f}"
    )
    return 0 if failures == 0 and percentile(latencies, .95) <= args.max_p95_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())
