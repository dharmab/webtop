#!/usr/bin/env python3

from collections import deque
from typing import Dict, Collection, Optional, Deque, List, Any, Callable
from yarl import URL
import aiohttp
import argparse
import asyncio
import datetime
import durationpy  # type: ignore
import json
import math
import os
import signal
import socket
import time
import yaml


class CustomResolver(aiohttp.resolver.AbstractResolver):
    async def close(self) -> None:
        await self.async_resolver.close()

    def __init__(self, *args, custom_mappings: Optional[Dict[str, str]] = None, **kwargs):
        super().__init__(*args, **kwargs)  # type: ignore
        if custom_mappings is None:
            self.custom_mappings: Dict[str, str] = {}
        else:
            self.custom_mappings = custom_mappings
        self.async_resolver = aiohttp.resolver.AsyncResolver()  # type: ignore

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> List[Dict[str, Any]]:
        if host in self.custom_mappings:
            return [
                {
                    "hostname": host,
                    "host": self.custom_mappings[host],
                    "port": port,
                    "family": family,
                    "proto": 0,
                    "flags": socket.AI_NUMERICHOST,
                }
            ]
        return await self.async_resolver.resolve(host, port, family)


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
        "--follow-redirects",
        metavar="BOOL",
        type=str,
        help="Whether HTTP 3XX responses will be followed",
        default="true",
    )

    parser.add_argument(
        "--verify-tls", metavar="BOOL", type=str, help="Whether to verify TLS certificates", default="true"
    )

    parser.add_argument(
        "-o",
        "--output-format",
        metavar="FORMAT",
        type=str,
        choices=("json", "yaml"),
        help="Output format",
        default="json",
    )

    parser.add_argument("--resolve", metavar="HOST:ADDRESS", type=str, help="Manually resolve host to address")

    parser.add_argument("-d", "--duration", metavar="TIME", type=str, help="Test duration, e.g. 3h2m1s", default=None)

    return parser.parse_args()


def duration_is_valid(duration: Optional[str]) -> bool:
    if duration is None:
        return True
    try:
        durationpy.from_str(duration)
        return True
    # Really?! durationpy raises bare Exception??
    except Exception:
        return False


def _str_to_bool(s: str, default: bool) -> bool:
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    return default


def are_args_valid(args: argparse.Namespace) -> bool:
    return all(
        (
            args.url.is_absolute(),
            args.request_history >= 1,
            args.timeout > 0,
            args.workers > 0,
            args.resolve is None or ":" in args.resolve,
            duration_is_valid(args.duration),
        )
    )


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


async def request(
    *, url: URL, method: str = "GET", follow_redirects: bool = True, session: aiohttp.ClientSession
) -> Result:
    try:
        start_time = time.time()
        async with session.request(method, url, allow_redirects=follow_redirects) as response:
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
            error = result.error
            # aiohttp uses very generic errors, so we need to drill down
            if isinstance(error, aiohttp.ClientConnectorError) and hasattr(error, "os_error"):
                error = error.os_error
            if isinstance(error, aiohttp.ClientConnectorCertificateError) and hasattr(error, "certificate_error"):
                error = error.certificate_error

            reason = ""
            error_module = type(error).__module__
            if error_module and error_module != "builtins":
                reason += f"{error_module}."
            reason += type(error).__qualname__

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

    resolver: Callable = aiohttp.resolver.DefaultResolver
    if args.resolve is not None:
        host, address = args.resolve.split(":")
        if args.url.host == host:
            custom_resolution = {host: address}

            def resolver():
                return CustomResolver(custom_mappings=custom_resolution)

    results: Deque[Result] = deque(maxlen=args.request_history)
    shutdown_event = asyncio.Event()

    def shutdown_signal_handler(_, __):
        shutdown_event.set()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(shutdown_signal, shutdown_signal_handler)

    tasks = []

    if args.duration is not None:
        duration = durationpy.from_str(args.duration)

        async def stop_test():
            await asyncio.wait([shutdown_event.wait()], timeout=duration.total_seconds())
            shutdown_event.set()

        tasks.append(stop_test())

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
    connector = aiohttp.TCPConnector(
        force_close=True, limit=0, resolver=resolver(), verify_ssl=_str_to_bool(args.verify_tls, default=True)
    )
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:

        async def worker() -> None:
            while not shutdown_event.is_set():
                result = await request(
                    url=args.url,
                    method=args.method,
                    session=session,
                    follow_redirects=_str_to_bool(args.follow_redirects, default=True),
                )
                results.append(result)

        for _ in range(args.workers):
            tasks.append(worker())
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
