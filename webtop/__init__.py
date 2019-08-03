#!/usr/bin/env python3

from collections import deque
from requests_toolbelt.adapters import host_header_ssl  # type: ignore
from threading import Lock, Thread, Event
from time import sleep
from typing import Dict, Collection, Optional, Callable, Any, Deque
from yarl import URL
import argparse
import datetime
import json
import math
import os
import requests
import requests.compat
import requests.adapters
import signal
import urllib3.poolmanager  # type: ignore
import yaml


class NoPoolManager(urllib3.poolmanager.PoolManager):
    def connection_from_pool_key(self, pool_key, request_context=None):
        scheme = request_context["scheme"]
        host = request_context["host"]
        port = request_context["port"]
        return self._new_pool(scheme, host, port, request_context=request_context)


class NoPoolSSLAdapter(host_header_ssl.HostHeaderSSLAdapter):
    def init_poolmanager(self, connections, maxsize, block=requests.adapters.DEFAULT_POOLBLOCK, **pool_kwargs):
        self._pool_connections = connections
        self._pool_maxsize = maxsize
        self._pool_block = block

        self.poolmanager = NoPoolManager(
            num_pools=connections, maxsize=maxsize, block=block, strict=True, **pool_kwargs
        )


class NoPoolAdapter(requests.adapters.HTTPAdapter):
    init_poolmanager = NoPoolSSLAdapter.init_poolmanager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("url", metavar="URL", type=str)

    parser.add_argument(
        "--method",
        metavar="VERB",
        help="HTTP method",
        type=str.upper,
        choices=["GET", "HEAD", "OPTIONS", "TRACE"],
        default="GET",
    )

    parser.add_argument("-k", "--threads", metavar="N", type=int, help="Thread pool size", default=1)

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


def are_args_valid(args: argparse.Namespace) -> bool:
    return all(
        (
            args.url.startswith(("http://", "https://")),
            args.request_history >= 1,
            args.timeout > 0,
            args.threads > 0,
            args.resolve is None or ":" in args.resolve,
        )
    )


class Result(object):
    def __init__(self, *, response: Optional[requests.models.Response] = None, error: Optional[Exception] = None):
        self.response = response
        self.error = error

        if self.response is None or self.error is not None:
            self.is_success = False
        else:
            self.is_success = self.response.status_code >= 200 and self.response.status_code < 400


class ResponseResult(Result):
    def __init__(self, *, response: requests.models.Response):
        super().__init__(response=response, error=None)


class ErrorResult(Result):
    def __init__(self, *, error: Exception):
        super().__init__(response=None, error=error)


def request(
    *, url: URL, method: str, timeout: int, session: requests.sessions.Session, headers: Dict[str, str]
) -> Result:
    try:
        response = session.request(method, str(url), timeout=timeout, headers=headers)
        return ResponseResult(response=response)
    except Exception as e:
        return ErrorResult(error=e)


def build_stats(*, url: str, method: str, results: Collection[Result]) -> dict:
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
            sum_latency += math.ceil(result.response.elapsed / datetime.timedelta(milliseconds=1))
            reason = f"HTTP {result.response.status_code}"
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
        "URL": url,
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


def main() -> None:
    args = parse_args()
    assert are_args_valid(args)

    url = URL(args.url)
    headers = {}
    if args.resolve is not None:
        parsed_url = URL(url)
        host, address = args.resolve.split(":")
        if parsed_url.host == host:
            url = url.with_host(address)
            headers["Host"] = host

    results: Deque[Result] = deque(maxlen=args.request_history)
    results_lock = Lock()
    shutdown_event = Event()

    def shutdown_signal_handler(signum, frame):
        shutdown_event.set()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(shutdown_signal, shutdown_signal_handler)

    threads = []

    def start_daemon(target: Callable[[], Any]) -> None:
        # Fly, Pantalaimon!
        thread = Thread(target=target)
        threads.append(thread)
        thread.daemon = True
        thread.start()

    def renderer() -> None:
        while True:
            if shutdown_event.is_set():
                return

            with results_lock:
                stats = build_stats(url=args.url, method=args.method, results=results)
            output = render_stats(stats, _format=args.output_format)

            os.system("clear")
            print(output, flush=True)

            sleep(0.1)

    start_daemon(target=renderer)
    with requests.Session() as session:
        session.mount("http://", NoPoolAdapter())
        session.mount("https://", NoPoolSSLAdapter())

        def worker() -> None:
            while True:
                result = request(url=url, method=args.method, timeout=args.timeout, session=session, headers=headers)
                with results_lock:
                    results.append(result)

                if shutdown_event.is_set():
                    return

        for i in range(args.threads):
            start_daemon(target=worker)

        for thread in threads:
            thread.join()


if __name__ == "__main__":
    main()
