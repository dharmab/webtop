#!/usr/bin/env python3

from collections import deque
from time import sleep
import urllib3.exceptions
from typing import Dict, Iterable, Optional
import argparse
import asyncio
import datetime
import math
import requests
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument('url', metavar='URL', type=str)
    parser.add_argument('--request-history', metavar='N', type=int, default=10)
    parser.add_argument('--timeout', metavar='SEC', type=float, default=10.)

    return parser.parse_args()


def are_args_valid(args: argparse.Namespace) -> bool:
    return True


class Result(object):
    def __init__(
        self,
        *,
        response: Optional[requests.models.Response] = None,
        error: Optional[Exception] = None,
    ):
        self.response = response
        self.error = error

        if self.response is None or self.error is not None:
            self.is_success = False
        else:
            self.is_success = self.response.status_code >= 200 and self.response.status_code < 400


async def request(*, url: str, timeout: int) -> Result:
    try:
        response = requests.get(url, timeout=timeout)
        return Result(response=response)
    except Exception as e:
        return Result(response=None, error=e)


async def render_stats(results: Iterable[Result]) -> None:
    no_results = len(results)
    no_successful_results = 0
    reason_counts: Dict[str, int] = {}
    sum_latency = 0

    for result in results:
        if result.is_success:
            no_successful_results += 1

        if result.response is not None:
            sum_latency += result.response.elapsed / datetime.timedelta(milliseconds=1)

        if result.error is not None:
            reason = str(type(result.error).__name__)
        else:
            reason = f"HTTP {result.response.status_code}"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    success_rate = no_successful_results / no_results * 100.
    avg_latency = math.ceil(sum_latency / no_results)

    summary = {
        "Success rate": f"{success_rate:3.6f}%",
        "Average Latency": f"{avg_latency:4d}ms",
        "Sample Size": no_results,
        "Reasons": reason_counts,
    }
    print(summary, end="\r")


async def main()-> None:
    args = parse_args()
    assert are_args_valid(args)
    results = deque(maxlen=args.request_history)
    try:
        while True:
            result = await request(url=args.url, timeout=args.timeout)
            results.append(result)
            await render_stats(results)
    except KeyboardInterrupt:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
