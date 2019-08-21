#!/usr/bin/env python3

from collections import deque
from threading import Event
from typing import Dict, Optional, Deque, List, Any, Set
import aiohttp
import asyncio
import copy
import datetime
import enum
import math
import socket
import time


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


async def request(*, url: str, method: str, session: aiohttp.ClientSession) -> Result:
    try:
        start_time = time.time()
        async with session.request(method, url) as response:
            await response.read()
            end_time = time.time()
            duration = datetime.timedelta(seconds=end_time - start_time)
            return ResponseResult(response=response, duration=duration)
    except Exception as e:
        return ErrorResult(error=e)


class Resolver(aiohttp.resolver.AbstractResolver):
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


class HTTPMethod(enum.Enum):
    GET = "GET"
    HEAD = "HEAD"


class Runner(object):
    def __init__(
        self,
        url: str,
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
                force_close=True, limit=0, resolver=Resolver(custom_mappings=self.__name_resolution_overrides)
            ),
        )

    async def start(self,) -> None:
        async with self.__session() as session:

            async def worker() -> None:
                while not self.__stop_event.is_set():
                    result = await request(url=self.url, method=self.method.value, session=session)
                    self.__results.append(result)

            event_loop = asyncio.get_event_loop()
            tasks = []
            for _ in range(self.__number_of_workers):
                tasks.append(event_loop.create_task(worker()))
            self.__tasks = tasks

    async def stop(self) -> None:
        self.__stop_event.set()
        asyncio.gather(*self.__tasks)

    def get_results(self) -> Set[Result]:
        return set(copy.deepcopy(self.__results))

    def get_statistics(self) -> "Statistics":
        return Statistics(self)


class Statistics(object):
    def __init__(self, runner: Runner):
        self.url = runner.url
        self.method = runner.method.value
        results = runner.get_results()
        self.sample_size = len(results)
        self.reason_counts: Dict[str, int] = {}
        number_of_successful_results = 0
        number_of_responses = 0
        sum_latency = 0

        for result in results:
            if result.is_success:
                number_of_successful_results += 1

            if isinstance(result, ResponseResult):
                number_of_responses += 1
                sum_latency += math.ceil(result.elapsed / datetime.timedelta(milliseconds=1))
                assert result.response is not None
                reason = f"HTTP {result.response.status}"
            elif isinstance(result, ErrorResult):
                reason = str(type(result.error).__name__)

            self.reason_counts[reason] = self.reason_counts.get(reason, 0) + 1

        self.success_rate = number_of_successful_results / number_of_responses * 100.0 if self.sample_size > 0 else 0.0
        self.mean_latency = math.ceil(sum_latency / number_of_responses) if number_of_responses > 0 else 0.0
