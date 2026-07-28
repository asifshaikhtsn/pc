# PC Pehle Proxy Lists

This repository automatically collects public proxies, removes duplicates, checks supported protocols, resolves the proxy IP country, checks HTTP-proxy anonymity in small batches, and creates type → country folders.

## Output structure

```text
proxies/
├── http/
│   ├── ALL/proxies.txt
│   ├── IN/proxies.txt
│   ├── US/proxies.txt
│   └── UNKNOWN/proxies.txt
├── https/
├── elite/
├── socks4/
└── socks5/
```

- `proxies/` contains validated working proxies.
- `raw/` contains scraped and deduplicated candidates grouped by source-reported protocol and GeoIP country. Raw does **not** mean working.
- `stats/summary.json` and `stats/summary.csv` contain counts.
- `stats/latest-results.csv` contains the latest state of every proxy.
- `state/proxies.json` stores incremental test history so every run does not retest everything.

## Current sources

1. `gitrecon1455/fresh-proxy-list`
2. `dpangestuw/Free-Proxy`

Add future sources in [`config/sources.json`](config/sources.json). Plain-text, common JSON layouts, scheme-prefixed proxies, and `IP:PORT` values are supported.

## Automatic schedule

The workflow runs every five minutes. A run:

1. Downloads current source lists.
2. Normalizes and globally deduplicates endpoints.
3. Resolves countries using a locally cached GeoLite2 Country database.
4. Selects a limited incremental validation batch.
5. Tests HTTP, HTTPS CONNECT, SOCKS4, and SOCKS5 support.
6. Performs a limited HTTP anonymity check for working HTTPS-capable HTTP proxies.
7. Rebuilds country folders and commits only changed files.

GitHub schedules may start later than the exact cron minute under platform load.

## Important meaning of `elite`

`elite` is an anonymity classification, not a transport protocol. This project places a proxy in `proxies/elite/<COUNTRY>/proxies.txt` only after an anonymity echo test does not observe the runner IP or common forwarding headers. Public echo services can be unavailable or rate-limited, so elite checks are deliberately limited per run.

## GitHub setup

After uploading these files:

1. Open **Settings → Actions → General**.
2. Under **Workflow permissions**, select **Read and write permissions**.
3. Open **Actions → Update proxy lists → Run workflow** for the first manual run.
4. Scheduled runs will continue every five minutes while Actions are enabled.

No password or personal access token is required for the workflow's normal commit because it uses the repository-provided `GITHUB_TOKEN` with `contents: write` permission.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
mkdir -p data
curl -L https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb -o data/GeoLite2-Country.mmdb
python -m proxy_pipeline --root .
```

## Tuning

Environment variables used by the workflow:

| Variable | Default | Meaning |
|---|---:|---|
| `MAX_CHECKS_PER_RUN` | 1800 | Maximum protocol checks in one run |
| `CHECK_CONCURRENCY` | 120 | Concurrent basic checks |
| `CHECK_TIMEOUT_SECONDS` | 6 | Timeout for each check |
| `ELITE_CHECKS_PER_RUN` | 100 | Maximum elite checks per run |
| `WORKING_RECHECK_MINUTES` | 30 | Recheck interval for working proxies |
| `DEAD_RECHECK_MINUTES` | 360 | Recheck interval for failed proxies |
| `PRUNE_AFTER_DAYS` | 3 | Remove state entries not seen in sources |
| `ACTIVE_SOURCE_WINDOW_MINUTES` | 60 | Keep source-missing proxies out of current output after this age |
| `MAX_WORKING_AGE_MINUTES` | 360 | Do not publish a working result older than this |

## Safety note

Free public proxies are untrusted. Do not send passwords, cookies, private files, payment data, or other sensitive information through them. A successful connectivity check does not prove that a proxy is safe.
