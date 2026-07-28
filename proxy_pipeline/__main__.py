from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .checking import run_checks, run_elite_checks
from .fetching import fetch_all_sources
from .geolocation import CountryResolver
from .output import build_raw_outputs, build_validated_outputs, write_stats
from .state import (
    apply_check_results,
    apply_elite_results,
    load_state,
    prune_unseen,
    save_state,
    select_tasks,
    sync_candidates,
    parse_time,
    utc_now,
)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


async def async_main(root: Path) -> None:
    config_path = root / "config" / "sources.json"
    state_path = root / "state" / "proxies.json.gz"
    mmdb_path = root / "data" / "GeoLite2-Country.mmdb"

    candidates, fetch_report = await fetch_all_sources(config_path)
    if not candidates:
        raise RuntimeError("No proxies were parsed from any configured source; refusing to overwrite outputs.")

    resolver = CountryResolver(mmdb_path)
    try:
        countries = {endpoint: resolver.country_code(endpoint) for endpoint in candidates}
    finally:
        resolver.close()

    state = load_state(state_path)
    sync_candidates(state, candidates, countries)
    build_raw_outputs(root / "raw", candidates, countries)

    max_checks = env_int("MAX_CHECKS_PER_RUN", 1800)
    concurrency = env_int("CHECK_CONCURRENCY", 120)
    timeout = env_float("CHECK_TIMEOUT_SECONDS", 6.0)
    tasks = select_tasks(
        state,
        candidates,
        max_checks=max_checks,
        working_recheck_minutes=env_int("WORKING_RECHECK_MINUTES", 30),
        dead_recheck_minutes=env_int("DEAD_RECHECK_MINUTES", 360),
    )
    results = await run_checks(tasks, concurrency=concurrency, timeout=timeout) if tasks else []
    apply_check_results(state, results)

    now = utc_now()
    elite_candidates = []
    for endpoint, item in state.get("proxies", {}).items():
        if item.get("checks", {}).get("https", {}).get("working") is not True:
            continue
        elite_state = item.get("elite", {})
        if elite_state.get("elite") is True:
            continue
        last_elite_check = parse_time(elite_state.get("last_checked"))
        if last_elite_check and (now - last_elite_check).total_seconds() < 6 * 3600:
            continue
        elite_candidates.append(endpoint)
    elite_candidates.sort(
        key=lambda endpoint: state["proxies"][endpoint].get("elite", {}).get("last_checked", "")
    )
    elite_results = await run_elite_checks(
        elite_candidates,
        limit=env_int("ELITE_CHECKS_PER_RUN", 100),
        concurrency=env_int("ELITE_CONCURRENCY", 15),
        timeout=timeout,
    )
    apply_elite_results(state, elite_results)

    removed = prune_unseen(state, days=env_int("PRUNE_AFTER_DAYS", 3))
    save_state(state_path, state)
    counts = build_validated_outputs(
        root / "proxies",
        state,
        active_window_minutes=env_int("ACTIVE_SOURCE_WINDOW_MINUTES", 60),
        max_working_age_minutes=env_int("MAX_WORKING_AGE_MINUTES", 360),
    )
    run_info = {
        "checks_selected": len(tasks),
        "checks_completed": len(results),
        "elite_checks_completed": len(elite_results),
        "state_entries_pruned": removed,
        "max_checks_per_run": max_checks,
        "check_concurrency": concurrency,
        "check_timeout_seconds": timeout,
    }
    write_stats(root / "stats", state, fetch_report, counts, run_info)

    print(f"Scraped unique endpoints: {len(candidates)}")
    print(f"Protocol checks completed: {len(results)}")
    print(f"Elite checks completed: {len(elite_results)}")
    for kind, details in counts.items():
        print(f"{kind}: {details['total']} working")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape, validate, and categorize public proxies.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    args = parser.parse_args()
    asyncio.run(async_main(args.root.resolve()))


if __name__ == "__main__":
    main()
