#!/usr/bin/env python3

import aiohttp
import argparse
import asyncio
from collections import deque
import datetime
import json
import math
import os
import signal
import time
from threading import Event
from typing import Dict, Collection, Optional, Deque
import yaml
from yarl import URL


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("url", metavar="URL", type=URL)

    parser.add_argument(
        "--method",
        metavar="VERB",
        help="HTTP method",
        type=str.upper,
        choices=["GET", "HEAD", "OPTIONS", "TRACE"],
        default="GET",
    )

    parser.add_argument("-k", "--workers", metavar="N", type=int, help="Number of workers", default=1)

    parser.add_argument(
        "--request-history", metavar="N", type=int, help="Number of request results to track", default=1000
    )

    parser.add_argument("--timeout", metavar="SEC", type=float, help="Request timeout threshold", default=1.0)

    parser.add_argument(
        "-o",
        "--output-format",
        metavar="FORMAT",
        type=str,
        choices=("json", "yaml"),
        help="Output format",
        default="json",
    )

    return parser.parse_args()


def are_args_valid(args: argparse.Namespace) -> bool:
    return all((args.url.is_absolute(), args.request_history >= 1, args.timeout > 0, args.workers > 0))


class Result(object):
    def __init__(self, *, response: Optional[aiohttp.ClientResponse] = None, error: Optional[Exception] = None):
        self.response = response
        self.error = error
        if self.response is None or self.error is not None:
            self.is_success = False
        else:
            self.is_success = 200 <= self.response.status < 400


class ResponseResult(Result):
    def __init__(self, *, response: aiohttp.ClientResponse, duration: datetime.timedelta):
        super().__init__(response=response, error=None)
        self.elapsed = duration


class ErrorResult(Result):
    def __init__(self, *, error: Exception):
        super().__init__(response=None, error=error)


async def request(*, url: URL, method: str, session: aiohttp.ClientSession) -> Result:
    try:
        start_time = time.time()
        async with session.request(method, url) as response:
            await response.read()
            end_time = time.time()
            duration = datetime.timedelta(seconds=end_time - start_time)
            return ResponseResult(response=response, duration=duration)
    except Exception as e:
        return ErrorResult(error=e)


def build_stats(*, url: URL, method: str, results: Collection[Result]) -> dict:
    # no_ = Number Of
    no_results = len(results)
    no_successful_results = 0
    no_responses = 0
    reason_counts: Dict[str, int] = {}
    sum_latency = 0

    for result in results:
        if result.is_success:
            no_successful_results += 1

        if isinstance(result, ResponseResult):
            assert result.response is not None
            no_responses += 1
            sum_latency += math.ceil(result.elapsed / datetime.timedelta(milliseconds=1))
            reason = f"HTTP {result.response.status}"
        elif isinstance(result, ErrorResult):
            reason = str(type(result.error).__name__)

        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    if no_results > 0:
        success_rate = no_successful_results / no_results * 100.0
    else:
        success_rate = 0.0

    if no_responses > 0:
        avg_latency = math.ceil(sum_latency / no_responses)
    else:
        avg_latency = 0

    summary = {
        "URL": str(url),
        "Verb": method,
        "Sample Size": no_results,
        "Success Rate": f"{success_rate:3.9f}%",
        "Average Latency": f"{avg_latency}ms",
        "Count by Reason": reason_counts,
    }

    return summary


def render_stats(stats: dict, _format: str) -> str:
    if _format == "json":
        output = json.dumps(stats, indent=2)
    elif _format == "yaml":
        output = yaml.dump(stats, default_flow_style=False, sort_keys=False)  # type: ignore
    return output


async def main() -> None:
    args = parse_args()
    assert are_args_valid(args)

    results: Deque[Result] = deque(maxlen=args.request_history)
    shutdown_event = Event()

    def shutdown_signal_handler(_, __):
        shutdown_event.set()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(shutdown_signal, shutdown_signal_handler)

    tasks = []

    async def renderer() -> None:
        while True:
            if shutdown_event.is_set():
                return

            stats = build_stats(url=args.url, method=args.method, results=results)
            output = render_stats(stats, _format=args.output_format)

            os.system("clear")
            print(output, flush=True)

            await asyncio.sleep(0.1)

    tasks.append(renderer())
    timeout = aiohttp.ClientTimeout(connect=args.timeout)
    connector = aiohttp.TCPConnector(force_close=True, limit=0)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:

        async def worker() -> None:
            while not shutdown_event.is_set():
                result = await request(url=args.url, method=args.method, session=session)
                results.append(result)

        tasks.extend([worker() for _ in range(args.workers)])
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
