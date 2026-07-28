from __future__ import annotations

import ipaddress
from pathlib import Path

import geoip2.database


class CountryResolver:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.reader = geoip2.database.Reader(str(database_path)) if database_path.exists() else None

    def close(self) -> None:
        if self.reader:
            self.reader.close()

    def country_code(self, endpoint: str) -> str:
        host = endpoint.rsplit(":", 1)[0].strip("[]")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return "UNKNOWN"

        if not self.reader:
            return "UNKNOWN"
        try:
            response = self.reader.country(host)
            code = response.country.iso_code or response.registered_country.iso_code
            return code.upper() if code else "UNKNOWN"
        except Exception:
            return "UNKNOWN"
