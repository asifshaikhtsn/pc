from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SUPPORTED_PROTOCOLS = {"http", "https", "socks4", "socks5"}


@dataclass(frozen=True)
class CheckTask:
    endpoint: str
    protocol: str


@dataclass
class Candidate:
    endpoint: str
    protocols: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    reported_country: str | None = None
    reported_anonymity: str | None = None

    def merge(self, other: "Candidate") -> None:
        self.protocols.update(other.protocols)
        self.sources.update(other.sources)
        self.reported_country = self.reported_country or other.reported_country
        self.reported_anonymity = self.reported_anonymity or other.reported_anonymity

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "protocols": sorted(self.protocols),
            "sources": sorted(self.sources),
            "reported_country": self.reported_country,
            "reported_anonymity": self.reported_anonymity,
        }
