from __future__ import annotations

import asyncio
import ipaddress
import json
import random
import time
from typing import Any

import aiohttp
from aiohttp_socks import ProxyConnector

from .models import CheckTask

HTTP_CHECK_URL = "http://example.com/"
HTTPS_CHECK_URL = "https://example.com/"
ANONYMITY_URL = "https://httpbin.org/get"

FORWARDING_HEADERS = {
    "forwarded",
    "via",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "client-ip",
    "proxy-connection",
}


async def _read_small(response: aiohttp.ClientResponse, limit: int = 65536) -> bytes:
    return await response.content.read(limit)


async def check_http_proxy(endpoint: str, protocol: str, timeout: float) -> dict[str, Any]:
    target = HTTPS_CHECK_URL if protocol == "https" else HTTP_CHECK_URL
    started = time.perf_counter()
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    connector = aiohttp.TCPConnector(limit=1, ttl_dns_cache=120)
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                target,
                proxy=f"http://{endpoint}",
                timeout=request_timeout,
                allow_redirects=True,
            ) as response:
                await _read_small(response)
                working = 200 <= response.status < 500
                return {
                    "working": working,
                    "status_code": response.status,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "error": None if working else f"HTTP {response.status}",
                }
    except Exception as exc:
        return {
            "working": False,
            "status_code": None,
            "latency_ms": None,
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
        }


async def check_socks_proxy(endpoint: str, protocol: str, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    proxy_url = f"{protocol}://{endpoint}"
    try:
        connector = ProxyConnector.from_url(proxy_url, rdns=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                HTTPS_CHECK_URL,
                timeout=request_timeout,
                allow_redirects=True,
            ) as response:
                await _read_small(response)
                working = 200 <= response.status < 500
                return {
                    "working": working,
                    "status_code": response.status,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "error": None if working else f"HTTP {response.status}",
                }
    except Exception as exc:
        return {
            "working": False,
            "status_code": None,
            "latency_ms": None,
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
        }


async def run_check(task: CheckTask, timeout: float) -> tuple[CheckTask, dict[str, Any]]:
    if task.protocol in {"http", "https"}:
        result = await check_http_proxy(task.endpoint, task.protocol, timeout)
    else:
        result = await check_socks_proxy(task.endpoint, task.protocol, timeout)
    return task, result


async def run_checks(
    tasks: list[CheckTask],
    concurrency: int,
    timeout: float,
) -> list[tuple[CheckTask, dict[str, Any]]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def guarded(task: CheckTask) -> tuple[CheckTask, dict[str, Any]]:
        async with semaphore:
            return await run_check(task, timeout)

    random.shuffle(tasks)
    return await asyncio.gather(*(guarded(task) for task in tasks))


def _extract_ips(value: str) -> set[str]:
    found: set[str] = set()
    for token in value.replace(",", " ").split():
        token = token.strip("[]()")
        try:
            found.add(ipaddress.ip_address(token).compressed)
        except ValueError:
            continue
    return found


async def discover_direct_ips(timeout: float) -> set[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                ANONYMITY_URL,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                data = await response.json(content_type=None)
                return _extract_ips(str(data.get("origin", "")))
    except Exception:
        return set()


async def check_elite(endpoint: str, direct_ips: set[str], timeout: float) -> dict[str, Any]:
    if not direct_ips:
        return {"elite": False, "checked": False, "reason": "direct IP unavailable"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                ANONYMITY_URL,
                proxy=f"http://{endpoint}",
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                data = await response.json(content_type=None)
    except Exception as exc:
        return {"elite": False, "checked": False, "reason": f"{type(exc).__name__}: {exc}"}

    origin_ips = _extract_ips(str(data.get("origin", "")))
    headers = {str(k).lower(): str(v) for k, v in dict(data.get("headers", {})).items()}
    leaked_in_origin = bool(origin_ips & direct_ips)
    leaking_headers = sorted(key for key in FORWARDING_HEADERS if key in headers)
    leaked_in_headers = any(any(ip in value for ip in direct_ips) for value in headers.values())
    elite = bool(origin_ips) and not leaked_in_origin and not leaked_in_headers and not leaking_headers
    return {
        "elite": elite,
        "checked": True,
        "origin": sorted(origin_ips),
        "leaking_headers": leaking_headers,
        "reason": None if elite else "client/proxy headers exposed or exit IP unchanged",
    }


async def run_elite_checks(
    endpoints: list[str],
    limit: int,
    concurrency: int,
    timeout: float,
) -> dict[str, dict[str, Any]]:
    direct_ips = await discover_direct_ips(timeout)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    selected = endpoints[: max(0, limit)]

    async def guarded(endpoint: str) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            return endpoint, await check_elite(endpoint, direct_ips, timeout)

    pairs = await asyncio.gather(*(guarded(endpoint) for endpoint in selected))
    return dict(pairs)
