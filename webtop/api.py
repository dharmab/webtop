#!/usr/bin/env python3

from threading import Event
from collections import deque
from typing import Any, Collection, Deque, Dict, List, Optional, Set
from yarl import URL
import asyncio
import enum
import aiohttp
import datetime
import json
import math
import socket
import time
import yaml


class Resolver(aiohttp.resolver.AbstractResolver):
    async def close(self) -> None:
        await self.async_resolver.close()

    def __init__(
        self, *args, custom_mappings: Optional[Dict[str, str]] = None, **kwargs
    ):
        super().__init__(*args, **kwargs)  # type: ignore
        if custom_mappings is None:
            self.custom_mappings: Dict[str, str] = {}
        else:
            self.custom_mappings = custom_mappings
        self.async_resolver = aiohttp.resolver.AsyncResolver()  # type: ignore

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> List[Dict[str, Any]]:
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


class Result(object):
    def __init__(
        self,
        *,
        response: Optional[aiohttp.ClientResponse] = None,
        error: Optional[Exception] = None,
    ):
        self.response = response
        self.error = error
        if self.response is None or self.error is not None:
            self.is_success = False
        else:
            self.is_success = 200 <= self.response.status < 400


class ResponseResult(Result):
    def __init__(
        self, *, response: aiohttp.ClientResponse, duration: datetime.timedelta
    ):
        super().__init__(response=response, error=None)
        self.elapsed = duration


class ErrorResult(Result):
    def __init__(self, *, error: Exception):
        super().__init__(response=None, error=error)


class HTTPMethod(enum.Enum):
    GET = "GET"
    HEAD = "HEAD"


class Runner(object):
    def __init__(
        self,
        url: URL,
        name_resolution_overrides: Optional[Dict[str, str]],
        method: str = "GET",
        number_of_running_requests: int = 100_000,
        number_of_workers: int = 1,
        timeout: int = 10,
    ):
        self.url = url
        self.method = HTTPMethod[method]
        self.__name_resolution_overrides = name_resolution_overrides or {}
        self.__number_of_running_requests = number_of_running_requests
        self.__number_of_workers = number_of_workers
        self.__results: Deque[Result] = deque(maxlen=number_of_running_requests)
        self.__stop_event = Event()
        self.__timeout = timeout

    def __session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(connect=self.__timeout),
            connector=aiohttp.TCPConnector(
                force_close=True,
                limit=0,
                resolver=Resolver(custom_mappings=self.__name_resolution_overrides),
            ),
        )

    async def start(self) -> None:
        async with self.__session() as session:

            async def worker() -> None:
                while not self.__stop_event.is_set():
                    result = await request(
                        url=self.url, method=self.method.value, session=session
                    )
                    self.__results.append(result)

            tasks = []
            for _ in range(self.__number_of_workers):
                tasks.append(worker())
            await asyncio.gather(*tasks)

    def stop(self) -> None:
        self.__stop_event.set()

    def get_results(self) -> Set[Result]:
        return set(self.__results)


async def request(
    *,
    url: URL,
    method: str = "GET",
    follow_redirects: bool = True,
    session: aiohttp.ClientSession,
) -> Result:
    try:
        start_time = time.time()
        async with session.request(
            method, url, allow_redirects=follow_redirects
        ) as response:
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
            sum_latency += math.ceil(
                result.elapsed / datetime.timedelta(milliseconds=1)
            )
            reason = f"HTTP {result.response.status}"
        elif isinstance(result, ErrorResult):
            error = result.error
            # aiohttp uses very generic errors, so we need to drill down
            if isinstance(error, aiohttp.ClientConnectorError) and hasattr(
                error, "os_error"
            ):
                error = error.os_error
            if isinstance(error, aiohttp.ClientConnectorCertificateError) and hasattr(
                error, "certificate_error"
            ):
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
