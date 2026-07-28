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


def _merge_candidates(target: dict[str, Candidate], incoming: dict[str, Candidate]) -> None:
    """Merge endpoint candidates while preserving all protocol/source metadata."""
    for endpoint, candidate in incoming.items():
        if endpoint in target:
            target[endpoint].merge(candidate)
        else:
            target[endpoint] = candidate


async def fetch_source(
    session: aiohttp.ClientSession,
    source: dict[str, Any],
    timeout: float = 60.0,
) -> tuple[str, dict[str, Candidate], list[str]]:
    """
    Download and merge every configured mirror/file for a source.

    Previously the function returned after the first successful mirror. That meant
    gitrecon's proxylist.json was parsed, while proxylist.txt was never downloaded.
    Some repositories publish different-sized datasets in JSON and TXT, so all
    configured files must be merged and deduplicated by IP:PORT.
    """
    name = source["name"]
    errors: list[str] = []
    merged: dict[str, Candidate] = {}

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
                _merge_candidates(merged, candidates)
            else:
                errors.append(f"{url}: no proxies parsed")
        except Exception as exc:  # one file failure must not abort the whole source
            errors.append(f"{url}: {type(exc).__name__}: {exc}")

    return name, merged, errors


async def fetch_all_sources(config_path: Path) -> tuple[dict[str, Candidate], dict[str, Any]]:
    sources = json.loads(config_path.read_text(encoding="utf-8"))
    headers = {
        "User-Agent": "pcpehle-proxy-updater/1.1 (+https://github.com/asifshaikhtsn/pc)",
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
        _merge_candidates(merged, candidates)

    report["unique_endpoints"] = len(merged)
    return merged, report
