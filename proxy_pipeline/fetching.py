from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp

from .models import Candidate
from .parsing import parse_payload


async def _fetch_text(session: aiohttp.ClientSession, url: str, timeout: float) -> str:
    request_timeout = aiohttp.ClientTimeout(total=timeout)
    async with session.get(url, timeout=request_timeout, allow_redirects=True) as response:
        response.raise_for_status()
        return await response.text(errors="ignore")


async def fetch_source(
    session: aiohttp.ClientSession,
    source: dict[str, Any],
    timeout: float = 30.0,
) -> tuple[str, dict[str, Candidate], list[str]]:
    name = source["name"]
    errors: list[str] = []
    for mirror in source.get("mirrors", []):
        url = mirror["url"]
        payload_format = mirror.get("format", "text")
        try:
            text = await _fetch_text(session, url, timeout)
            candidates = parse_payload(
                text=text,
                payload_format=payload_format,
                source_name=name,
                default_protocol=source.get("protocol", "auto"),
                fallback_protocols=source.get("fallback_protocols", []),
            )
            if candidates:
                return name, candidates, errors
            errors.append(f"{url}: no proxies parsed")
        except Exception as exc:  # source failures must not abort all sources
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    return name, {}, errors


async def fetch_all_sources(config_path: Path) -> tuple[dict[str, Candidate], dict[str, Any]]:
    sources = json.loads(config_path.read_text(encoding="utf-8"))
    headers = {
        "User-Agent": "pcpehle-proxy-updater/1.0 (+https://github.com/asifshaikhtsn/pcpehle)",
        "Accept": "text/plain, application/json;q=0.9, */*;q=0.8",
    }
    connector = aiohttp.TCPConnector(limit=12, ttl_dns_cache=300)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        results = await asyncio.gather(*(fetch_source(session, source) for source in sources))

    merged: dict[str, Candidate] = {}
    report: dict[str, Any] = {"sources": {}, "errors": []}
    for name, candidates, errors in results:
        report["sources"][name] = {"parsed": len(candidates), "errors": errors}
        report["errors"].extend(errors)
        for endpoint, candidate in candidates.items():
            if endpoint in merged:
                merged[endpoint].merge(candidate)
            else:
                merged[endpoint] = candidate
    report["unique_endpoints"] = len(merged)
    return merged, report
