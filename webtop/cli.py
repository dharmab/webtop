#!/usr/bin/env python3

from yarl import URL
from typing import Dict, Optional
import api
import argparse
import asyncio
import durationpy  # type: ignore
import json
import os
import signal
import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument("url", metavar="URL", type=URL)

    parser.add_argument(
        "--method",
        metavar="VERB",
        help="HTTP method",
        type=str.upper,
        choices=["GET", "HEAD", "OPTIONS", "TRACE"],
        default="GET",
    )

    parser.add_argument(
        "-k", "--workers", metavar="N", type=int, help="Number of workers", default=1
    )

    parser.add_argument(
        "--request-history",
        metavar="N",
        type=int,
        help="Number of request results to track",
        default=1000,
    )

    parser.add_argument(
        "--timeout",
        metavar="SEC",
        type=float,
        help="Request timeout threshold",
        default=1.0,
    )

    parser.add_argument(
        "--follow-redirects",
        metavar="BOOL",
        type=str,
        help="Whether HTTP 3XX responses will be followed",
        default="true",
    )

    parser.add_argument(
        "--verify-tls",
        metavar="BOOL",
        type=str,
        help="Whether to verify TLS certificates",
        default="true",
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

    parser.add_argument(
        "--resolve",
        metavar="HOST:ADDRESS",
        type=str,
        help="Manually resolve host to address",
    )

    parser.add_argument(
        "-d",
        "--duration",
        metavar="TIME",
        type=str,
        help="Test duration, e.g. 3h2m1s",
        default=None,
    )

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


def render_stats(stats: dict, _format: str) -> str:
    if _format == "json":
        output = json.dumps(stats, indent=2)
    elif _format == "yaml":
        output = yaml.dump(  # type: ignore
            stats, default_flow_style=False, sort_keys=False
        )
    return output


async def main() -> None:
    # Parse arguments
    args = parse_args()
    assert are_args_valid(args)

    custom_resolution: Dict[str, str] = {}
    if args.resolve is not None:
        host, address = args.resolve.split(":")
        if args.url.host == host:
            custom_resolution = {host: address}

    tasks = []

    # Start webtop runner
    runner = api.Runner(
        url=args.url,
        name_resolution_overrides=custom_resolution,
        method=args.method,
        number_of_running_requests=args.request_history,
        number_of_workers=args.workers,
        timeout=args.timeout,
    )

    tasks.append(asyncio.create_task(runner.start()))

    # Start renderer
    async def renderer():
        while True:
            if shutdown_event.is_set():
                return

            stats = api.build_stats(
                url=args.url, method=args.method, results=runner.get_results()
            )
            output = render_stats(stats, _format=args.output_format)

            os.system("clear")
            print(output, flush=True)

            await asyncio.sleep(0.1)

    tasks.append(asyncio.create_task(renderer()))

    # Handle shutdown
    shutdown_event = asyncio.Event()

    def shutdown_signal_handler(_, __):
        shutdown_event.set()
        runner.stop()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal

    if args.duration is not None:
        asyncio.wait(
            [shutdown_event.wait()], timeout=durationpy.from_str(args.duration)
        )

    # Zhu Li, do the things!
    task_group = asyncio.gather(*tasks)
    await task_group


if __name__ == "__main__":
    asyncio.run(main())
