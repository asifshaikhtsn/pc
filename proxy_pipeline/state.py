from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Candidate, CheckTask


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated_at": None, "proxies": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("proxies"), dict):
            raise ValueError("invalid state")
        return data
    except Exception:
        return {"version": 1, "updated_at": None, "proxies": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = iso_now()
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def sync_candidates(state: dict[str, Any], candidates: dict[str, Candidate], countries: dict[str, str]) -> None:
    now = iso_now()
    proxies = state.setdefault("proxies", {})
    for endpoint, candidate in candidates.items():
        item = proxies.setdefault(endpoint, {"checks": {}, "elite": {}, "first_seen": now})
        item["last_seen"] = now
        item["sources"] = sorted(candidate.sources)
        item["candidate_protocols"] = sorted(candidate.protocols)
        item["country"] = countries.get(endpoint, "UNKNOWN")
        item["reported_country"] = candidate.reported_country
        item["reported_anonymity"] = candidate.reported_anonymity


def _is_due(check: dict[str, Any] | None, now: datetime, working_minutes: int, dead_minutes: int) -> tuple[bool, int]:
    if not check or not check.get("last_checked"):
        return True, 0
    last = parse_time(check.get("last_checked"))
    if not last:
        return True, 0
    age_minutes = (now - last).total_seconds() / 60
    if check.get("working"):
        return age_minutes >= working_minutes, 1
    return age_minutes >= dead_minutes, 2


def select_tasks(
    state: dict[str, Any],
    candidates: dict[str, Candidate],
    max_checks: int,
    working_recheck_minutes: int,
    dead_recheck_minutes: int,
) -> list[CheckTask]:
    now = utc_now()
    ranked: list[tuple[int, float, CheckTask]] = []
    proxies = state.setdefault("proxies", {})

    for endpoint, candidate in candidates.items():
        item = proxies[endpoint]
        checks = item.setdefault("checks", {})
        desired: set[str] = set()
        for protocol in candidate.protocols:
            if protocol == "http":
                desired.update({"http", "https"})
            elif protocol in {"https", "socks4", "socks5"}:
                desired.add(protocol)

        for protocol in desired:
            due, priority = _is_due(
                checks.get(protocol),
                now,
                working_recheck_minutes,
                dead_recheck_minutes,
            )
            if not due:
                continue
            last = parse_time(checks.get(protocol, {}).get("last_checked"))
            age = (now - last).total_seconds() if last else 10**12
            ranked.append((priority, -age, CheckTask(endpoint, protocol)))

    ranked.sort(key=lambda row: (row[0], row[1], row[2].endpoint, row[2].protocol))
    return [row[2] for row in ranked[: max(0, max_checks)]]


def apply_check_results(
    state: dict[str, Any],
    results: list[tuple[CheckTask, dict[str, Any]]],
) -> None:
    now = iso_now()
    proxies = state["proxies"]
    for task, result in results:
        record = dict(result)
        record["last_checked"] = now
        proxies[task.endpoint].setdefault("checks", {})[task.protocol] = record


def apply_elite_results(state: dict[str, Any], results: dict[str, dict[str, Any]]) -> None:
    now = iso_now()
    for endpoint, result in results.items():
        record = dict(result)
        record["last_checked"] = now
        state["proxies"][endpoint]["elite"] = record


def prune_unseen(state: dict[str, Any], days: int) -> int:
    now = utc_now()
    removed = 0
    for endpoint in list(state.get("proxies", {})):
        last_seen = parse_time(state["proxies"][endpoint].get("last_seen"))
        if last_seen and (now - last_seen).total_seconds() > days * 86400:
            del state["proxies"][endpoint]
            removed += 1
    return removed
