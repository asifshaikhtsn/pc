from __future__ import annotations

import csv
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Candidate

OUTPUT_TYPES = ("http", "https", "elite", "socks4", "socks5")


def _safe_country(value: str | None) -> str:
    text = (value or "UNKNOWN").upper().strip()
    return text if len(text) == 2 and text.isalpha() else "UNKNOWN"


def _write_lines(path: Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(sorted(set(values)))
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def build_raw_outputs(raw_root: Path, candidates: dict[str, Candidate], countries: dict[str, str]) -> None:
    if raw_root.exists():
        shutil.rmtree(raw_root)
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for endpoint, candidate in candidates.items():
        country = _safe_country(countries.get(endpoint))
        for protocol in candidate.protocols:
            if protocol in {"http", "https", "socks4", "socks5"}:
                grouped[(protocol, country)].append(endpoint)

    for (protocol, country), endpoints in grouped.items():
        _write_lines(raw_root / protocol / country / "proxies.txt", endpoints)
    for protocol in ("http", "https", "socks4", "socks5"):
        all_values = [endpoint for (kind, _), values in grouped.items() if kind == protocol for endpoint in values]
        _write_lines(raw_root / protocol / "ALL" / "proxies.txt", all_values)


def _is_recent(value: str | None, max_age_minutes: int) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - parsed).total_seconds() <= max_age_minutes * 60


def build_validated_outputs(
    proxies_root: Path,
    state: dict[str, Any],
    active_window_minutes: int = 60,
    max_working_age_minutes: int = 360,
) -> dict[str, Any]:
    if proxies_root.exists():
        shutil.rmtree(proxies_root)

    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for endpoint, item in state.get("proxies", {}).items():
        if not _is_recent(item.get("last_seen"), active_window_minutes):
            continue
        country = _safe_country(item.get("country"))
        checks = item.get("checks", {})
        for protocol in ("http", "https", "socks4", "socks5"):
            check = checks.get(protocol, {})
            if check.get("working") is True and _is_recent(
                check.get("last_checked"), max_working_age_minutes
            ):
                grouped[(protocol, country)].append(endpoint)
        elite = item.get("elite", {})
        if (
            elite.get("elite") is True
            and _is_recent(elite.get("last_checked"), max_working_age_minutes)
            and (
                checks.get("http", {}).get("working")
                or checks.get("https", {}).get("working")
            )
        ):
            grouped[("elite", country)].append(endpoint)

    counts: dict[str, Any] = {kind: {"total": 0, "countries": {}} for kind in OUTPUT_TYPES}
    for (kind, country), endpoints in grouped.items():
        unique = sorted(set(endpoints))
        _write_lines(proxies_root / kind / country / "proxies.txt", unique)
        counts[kind]["countries"][country] = len(unique)
        counts[kind]["total"] += len(unique)

    for kind in OUTPUT_TYPES:
        all_values = [endpoint for (group_kind, _), values in grouped.items() if group_kind == kind for endpoint in values]
        _write_lines(proxies_root / kind / "ALL" / "proxies.txt", all_values)
    return counts


def write_stats(
    stats_root: Path,
    state: dict[str, Any],
    fetch_report: dict[str, Any],
    counts: dict[str, Any],
    run_info: dict[str, Any],
) -> None:
    stats_root.mkdir(parents=True, exist_ok=True)
    summary = {
        "updated_at": state.get("updated_at"),
        "scraped_unique_endpoints": fetch_report.get("unique_endpoints", 0),
        "validated": counts,
        "run": run_info,
        "sources": fetch_report.get("sources", {}),
        "source_errors": fetch_report.get("errors", []),
    }
    (stats_root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    with (stats_root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["type", "country", "working_count"])
        for kind in OUTPUT_TYPES:
            for country, count in sorted(counts[kind]["countries"].items()):
                writer.writerow([kind, country, count])
            writer.writerow([kind, "ALL", counts[kind]["total"]])

    with (stats_root / "latest-results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "proxy",
                "country",
                "sources",
                "http",
                "https",
                "elite",
                "socks4",
                "socks5",
                "last_seen",
            ]
        )
        for endpoint, item in sorted(state.get("proxies", {}).items()):
            checks = item.get("checks", {})
            writer.writerow(
                [
                    endpoint,
                    _safe_country(item.get("country")),
                    "|".join(item.get("sources", [])),
                    checks.get("http", {}).get("working", ""),
                    checks.get("https", {}).get("working", ""),
                    item.get("elite", {}).get("elite", ""),
                    checks.get("socks4", {}).get("working", ""),
                    checks.get("socks5", {}).get("working", ""),
                    item.get("last_seen", ""),
                ]
            )
