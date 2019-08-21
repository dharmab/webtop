#!/usr/bin/env python3

from . import api
from threading import Event
from yarl import URL
from time import sleep
import argparse
import json
import os
import signal
import yaml


def _parse_args() -> argparse.Namespace:
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

    parser.add_argument("--resolve", metavar="HOST:ADDRESS", type=str, help="Manually resolve host to address")

    return parser.parse_args()


def _are_args_valid(args: argparse.Namespace) -> bool:
    return all(
        (
            args.url.is_absolute(),
            args.request_history >= 1,
            args.timeout > 0,
            args.workers > 0,
            args.resolve is None or ":" in args.resolve,
        )
    )


def _build_stats(statistics: api.Statistics) -> dict:
    return {
        "URL": statistics.url,
        "Verb": statistics.method,
        "Sample Size": statistics.sample_size,
        "Success Rate": f"{statistics.success_rate:3.9f}%",
        "Average Latency": f"{statistics.mean_latency}ms",
        "Count by Reason": statistics.reason_counts,
    }


def _render_stats(statistics: dict, *, _format: str) -> str:
    if _format == "json":
        output = json.dumps(statistics, indent=2)
    elif _format == "yaml":
        output = yaml.dump(statistics, default_flow_style=False, sort_keys=False)  # type: ignore
    return output


def _print_stats(statistics: api.Statistics, _format: str) -> None:
    stats = _build_stats(statistics)
    output = _render_stats(stats, _format=_format)
    os.system("clear")
    print(output, flush=True)


def main() -> None:
    args = _parse_args()
    assert _are_args_valid(args)

    if args.resolve is not None:
        host, address = args.resolve.split(":")
        if args.url.host == host:
            custom_resolution = {host: address}

    runner = api.Runner(
        url=str(args.url),
        name_resolution_overrides=custom_resolution,
        method=args.method,
        number_of_running_requests=args.request_history,
        number_of_workers=args.number_of_workers,
        timeout=args.timeout
    )

    shutdown_event = Event()

    def shutdown_signal_handler(_, __):
        await runner.stop()
        shutdown_event.set()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(shutdown_signal, shutdown_signal_handler)

    while not shutdown_event.is_set():
        _print_stats(runner.get_statistics(), _format=args.foramt)
        sleep(0.1)


if __name__ == "__main__":
    main()
