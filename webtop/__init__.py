#!/usr/bin/env python3

from collections import deque
from typing import Dict, Iterable, Optional
import argparse
import datetime
import json
import math
import os
import requests
import sys
import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument('url', metavar='URL', type=str)
    parser.add_argument(
        '--request-history',
        metavar='N',
        type=int,
        help='Number of request results to track',
        default=1000
    )

    parser.add_argument(
        '--timeout',
        metavar='SEC',
        type=float,
        help='Request timeout threshold',
        default=1.
    )

    parser.add_argument(
        '-o', '--output-format',
        metavar='FORMAT',
        type=str,
        choices=('json', 'yaml'),
        help='Output format',
        default='json'
    )

    return parser.parse_args()


def are_args_valid(args: argparse.Namespace) -> bool:
    return all((
        args.url.startswith(('http://', 'https://')),
        args.request_history >= 1,
        args.timeout > 0
    ))


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


class ResponseResult(Result):
    def __init__(
        self,
        *,
        response: requests.models.Response
    ):
        super().__init__(response=response, error=None)


class ErrorResult(Result):
    def __init__(
        self,
        *,
        error: Exception
    ):
        super().__init__(response=None, error=error)


def request(*, url: str, timeout: int) -> Result:
    try:
        response = requests.get(url, timeout=timeout)
        return ResponseResult(response=response)
    except Exception as e:
        return ErrorResult(error=e)


def build_stats(results: Iterable[Result]) -> dict:
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
            no_responses += 1
            sum_latency += result.response.elapsed / datetime.timedelta(milliseconds=1)
            reason = f"HTTP {result.response.status_code}"
        elif isinstance(result, ErrorResult):
            reason = str(type(result.error).__name__)

        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    success_rate = no_successful_results / no_results * 100.
    avg_latency = math.ceil(sum_latency / no_responses)

    summary = {
        "Sample Size": no_results,
        "Success Rate": f"{success_rate:3.9f}%",
        "Average Latency": f"{avg_latency}ms",
        "Count by Reason": reason_counts,
    }

    return summary


def render_stats(stats: dict, _format: str) -> None:
    if _format == "json":
        output = json.dumps(stats, indent=2)
    elif _format == "yaml":
        output = yaml.dump(stats, default_flow_style=False, sort_keys=False)

    os.system('clear')
    print(output)


def main()-> None:
    args = parse_args()
    assert are_args_valid(args)
    results = deque(maxlen=args.request_history)
    try:
        while True:
            result = request(url=args.url, timeout=args.timeout)
            results.append(result)
            stats = build_stats(results)
            render_stats(stats, _format=args.output_format)
    except KeyboardInterrupt:
        os.system('clear')
        sys.exit(0)


if __name__ == "__main__":
    main()
