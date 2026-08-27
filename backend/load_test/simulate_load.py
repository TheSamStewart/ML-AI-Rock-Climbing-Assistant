"""Async load-test script for the analysis API.

Not part of the pytest suite on purpose: pytest's suite (including
test_concurrency.py) proves correctness with fakeredis/mocks so it's fast
and needs no infra. This script hits a *real* running stack - real Redis,
real Celery worker, real uvicorn - and measures latency/throughput/error
rate under concurrent virtual users.

Usage:
    uv run python load_test/simulate_load.py --base-url http://localhost:8000 \
        --users 200 --duration 60 --ramp-up 10

Run against `docker-compose up redis api worker` for a local number, or
point --base-url at a staging deployment for a real 10,000-user figure - a
laptop and a GitHub-hosted CI runner cannot honestly generate that much
concurrency themselves. See Agents.md section 4 for context.
"""

import argparse
import asyncio
import csv
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field

import httpx

FAKE_IMAGE_BYTES = b"fake binary image contents for load testing"
POLL_INTERVAL_SECONDS = 0.25
POLL_TIMEOUT_SECONDS = 10


@dataclass
class Sample:
    endpoint: str
    latency_s: float
    status_code: int
    error: str | None = None


@dataclass
class Results:
    samples: list[Sample] = field(default_factory=list)

    def add(self, sample: Sample):
        self.samples.append(sample)

    def summary(self):
        by_endpoint: dict[str, list[Sample]] = {}
        for s in self.samples:
            by_endpoint.setdefault(s.endpoint, []).append(s)

        lines = []
        total = len(self.samples)
        total_errors = sum(1 for s in self.samples if s.error or s.status_code >= 400)
        lines.append(f"Total requests: {total}")
        lines.append(f"Total errors:   {total_errors} ({(total_errors / total * 100) if total else 0:.2f}%)")
        lines.append("")

        for endpoint, samples in sorted(by_endpoint.items()):
            latencies = sorted(s.latency_s for s in samples)
            errors = sum(1 for s in samples if s.error or s.status_code >= 400)
            lines.append(f"[{endpoint}] n={len(samples)} errors={errors}")
            if latencies:
                lines.append(
                    f"  p50={_percentile(latencies, 50) * 1000:.1f}ms  "
                    f"p95={_percentile(latencies, 95) * 1000:.1f}ms  "
                    f"p99={_percentile(latencies, 99) * 1000:.1f}ms  "
                    f"max={latencies[-1] * 1000:.1f}ms"
                )
        return "\n".join(lines)

    def to_csv(self, path: str):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["endpoint", "latency_s", "status_code", "error"])
            for s in self.samples:
                writer.writerow([s.endpoint, s.latency_s, s.status_code, s.error or ""])


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


async def _timed_request(client: httpx.AsyncClient, endpoint_label: str, method: str, url: str, **kwargs) -> tuple[Sample, httpx.Response | None]:
    start = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
        latency = time.perf_counter() - start
        return Sample(endpoint_label, latency, response.status_code), response
    except httpx.HTTPError as exc:
        latency = time.perf_counter() - start
        return Sample(endpoint_label, latency, 0, error=str(exc)), None


async def virtual_user(user_id: int, base_url: str, stop_at: float, results: Results):
    async with httpx.AsyncClient(base_url=base_url, timeout=POLL_TIMEOUT_SECONDS) as client:
        while time.monotonic() < stop_at:
            idempotency_key = str(uuid.uuid4())
            files = {"photo": (f"user{user_id}.jpg", FAKE_IMAGE_BYTES, "image/jpeg")}
            headers = {"Idempotency-Key": idempotency_key}

            sample, response = await _timed_request(
                client, "POST /analysis", "POST", "/analysis", files=files, headers=headers
            )
            results.add(sample)

            if response is None or response.status_code != 202:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            task_id = response.json().get("task_id")
            if not task_id:
                continue

            poll_deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
            while time.monotonic() < poll_deadline:
                sample, response = await _timed_request(
                    client, "GET /analysis/{task_id}", "GET", f"/analysis/{task_id}"
                )
                results.add(sample)

                if response is not None and response.json().get("status") not in (
                    "PENDING",
                    "STARTED",
                    "RETRY",
                ):
                    break
                await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def run(base_url: str, users: int, duration: float, ramp_up: float) -> Results:
    results = Results()
    stop_at = time.monotonic() + duration

    tasks = []
    for i in range(users):
        if ramp_up > 0 and users > 1:
            await asyncio.sleep(ramp_up / users)
        tasks.append(asyncio.create_task(virtual_user(i, base_url, stop_at, results)))

    await asyncio.gather(*tasks)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=200, help="Concurrent virtual users (default: 200)")
    parser.add_argument("--duration", type=float, default=60, help="Seconds to run after ramp-up (default: 60)")
    parser.add_argument("--ramp-up", type=float, default=10, help="Seconds to spread user start over (default: 10)")
    parser.add_argument("--csv", default=None, help="Optional path to write raw per-request samples")
    args = parser.parse_args()

    print(f"Ramping up to {args.users} virtual users over {args.ramp_up}s, running for {args.duration}s...")
    results = asyncio.run(run(args.base_url, args.users, args.duration, args.ramp_up))

    print()
    print(results.summary())

    if args.csv:
        results.to_csv(args.csv)
        print(f"\nRaw samples written to {args.csv}")

    error_rate = (
        sum(1 for s in results.samples if s.error or s.status_code >= 400) / len(results.samples)
        if results.samples
        else 1.0
    )
    if error_rate > 0.01:
        print(f"\nError rate {error_rate * 100:.2f}% exceeded 1% threshold.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
