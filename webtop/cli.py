#!/usr/bin/env python3

from collections import deque
from yarl import URL
from typing import Callable, Deque, Optional
import aiohttp
import argparse
import asyncio
import durationpy  # type: ignore
import os
import signal
import webtop.api


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


async def main() -> None:
    args = parse_args()
    assert are_args_valid(args)

    resolver: Callable = aiohttp.resolver.DefaultResolver
    if args.resolve is not None:
        host, address = args.resolve.split(":")
        if args.url.host == host:
            custom_resolution = {host: address}

            def resolver():
                return webtop.api.CustomResolver(custom_mappings=custom_resolution)

    results: Deque[webtop.api.Result] = deque(maxlen=args.request_history)
    shutdown_event = asyncio.Event()

    def shutdown_signal_handler(_, __):
        shutdown_event.set()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(shutdown_signal, shutdown_signal_handler)

    tasks = []

    if args.duration is not None:
        duration = durationpy.from_str(args.duration)

        async def stop_test():
            await asyncio.wait([shutdown_event.wait()], timeout=duration)
            shutdown_event.set()

        tasks.append(stop_test())

    async def renderer() -> None:
        while True:
            if shutdown_event.is_set():
                return

            stats = webtop.api.build_stats(url=args.url, method=args.method, results=results)
            output = webtop.api.render_stats(stats, _format=args.output_format)

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
                result = await webtop.api.request(
                    url=args.url,
                    method=args.method,
                    session=session,
                    follow_redirects=_str_to_bool(args.follow_redirects, default=True),
                )
                results.append(result)

        for _ in range(args.workers):
            tasks.append(worker())
        await asyncio.gather(*tasks)
