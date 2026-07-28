from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from .models import Candidate, SUPPORTED_PROTOCOLS

# IPv4 and bracketed IPv6 endpoints. Authentication is intentionally ignored.
ENDPOINT_RE = re.compile(
    r"(?:(?P<scheme>https?|socks4|socks5)://)?"
    r"(?P<host>\[[0-9a-fA-F:]+\]|(?:\d{1,3}\.){3}\d{1,3})"
    r":(?P<port>\d{1,5})",
    re.IGNORECASE,
)

PROTOCOL_ALIASES = {
    "http": "http",
    "https": "https",
    "ssl": "https",
    "connect": "https",
    "socks4": "socks4",
    "sock4": "socks4",
    "s4": "socks4",
    "socks5": "socks5",
    "sock5": "socks5",
    "s5": "socks5",
}


def normalize_protocol(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        output: set[str] = set()
        for item in value:
            output.update(normalize_protocol(item))
        return output

    text = str(value).strip().lower()
    output = set()
    for token in re.split(r"[,/|;\s]+", text):
        normalized = PROTOCOL_ALIASES.get(token)
        if normalized:
            output.add(normalized)
    return output


def normalize_endpoint(host: str, port: str | int) -> str | None:
    host = str(host).strip().strip("[]")
    try:
        ip = ipaddress.ip_address(host)
        parsed_port = int(port)
    except (ValueError, TypeError):
        return None

    if not 1 <= parsed_port <= 65535:
        return None
    if ip.is_unspecified or ip.is_multicast:
        return None

    return f"[{ip.compressed}]:{parsed_port}" if ip.version == 6 else f"{ip.compressed}:{parsed_port}"


def parse_endpoint_text(text: str) -> list[tuple[str, set[str]]]:
    found: list[tuple[str, set[str]]] = []
    for match in ENDPOINT_RE.finditer(text):
        endpoint = normalize_endpoint(match.group("host"), match.group("port"))
        if not endpoint:
            continue
        scheme = match.group("scheme")
        found.append((endpoint, normalize_protocol(scheme)))
    return found


def parse_text(
    text: str,
    source_name: str,
    default_protocol: str,
    fallback_protocols: Iterable[str],
) -> dict[str, Candidate]:
    result: dict[str, Candidate] = {}
    fallback = set(fallback_protocols)
    default = normalize_protocol(default_protocol)

    for endpoint, detected in parse_endpoint_text(text):
        protocols = detected or default
        if not protocols and default_protocol == "auto":
            protocols = fallback
        candidate = Candidate(endpoint=endpoint, protocols=protocols, sources={source_name})
        if endpoint in result:
            result[endpoint].merge(candidate)
        else:
            result[endpoint] = candidate
    return result


def _first_present(record: dict[str, Any], names: tuple[str, ...]) -> Any:
    lower = {str(key).lower(): value for key, value in record.items()}
    for name in names:
        if name in lower and lower[name] not in (None, ""):
            return lower[name]
    return None


def _record_candidate(
    record: dict[str, Any],
    source_name: str,
    default_protocol: str,
    fallback_protocols: set[str],
    inherited_protocols: set[str],
) -> Candidate | None:
    endpoint_value = _first_present(record, ("proxy", "endpoint", "address", "server"))
    ip_value = _first_present(record, ("ip", "host", "hostname"))
    port_value = _first_present(record, ("port", "proxy_port"))

    endpoint: str | None = None
    detected_from_endpoint: set[str] = set()
    if endpoint_value:
        matches = parse_endpoint_text(str(endpoint_value))
        if matches:
            endpoint, detected_from_endpoint = matches[0]
    if not endpoint and ip_value is not None and port_value is not None:
        endpoint = normalize_endpoint(str(ip_value), port_value)
    if not endpoint:
        return None

    protocol_value = _first_present(record, ("protocol", "protocols", "type", "scheme", "proxy_type"))
    protocols = normalize_protocol(protocol_value) | detected_from_endpoint | inherited_protocols
    if not protocols:
        protocols = normalize_protocol(default_protocol)
    if not protocols and default_protocol == "auto":
        protocols = set(fallback_protocols)

    country = _first_present(
        record,
        ("country_code", "countrycode", "country", "iso_code", "cc"),
    )
    anonymity = _first_present(record, ("anonymity", "anonymity_level", "level"))

    return Candidate(
        endpoint=endpoint,
        protocols={item for item in protocols if item in SUPPORTED_PROTOCOLS},
        sources={source_name},
        reported_country=str(country).upper() if country else None,
        reported_anonymity=str(anonymity).lower() if anonymity else None,
    )


def parse_json(
    text: str,
    source_name: str,
    default_protocol: str,
    fallback_protocols: Iterable[str],
) -> dict[str, Candidate]:
    data = json.loads(text)
    result: dict[str, Candidate] = {}
    fallback = set(fallback_protocols)

    def add(candidate: Candidate | None) -> None:
        if not candidate:
            return
        if candidate.endpoint in result:
            result[candidate.endpoint].merge(candidate)
        else:
            result[candidate.endpoint] = candidate

    def walk(value: Any, inherited_protocols: set[str] | None = None) -> None:
        inherited_protocols = inherited_protocols or set()
        if isinstance(value, dict):
            add(
                _record_candidate(
                    value,
                    source_name,
                    default_protocol,
                    fallback,
                    inherited_protocols,
                )
            )
            for key, nested in value.items():
                key_protocols = normalize_protocol(key)
                for endpoint, detected in parse_endpoint_text(str(key)):
                    protocols = detected | inherited_protocols | key_protocols
                    if not protocols:
                        protocols = normalize_protocol(default_protocol)
                    if not protocols and default_protocol == "auto":
                        protocols = fallback
                    add(
                        Candidate(
                            endpoint=endpoint,
                            protocols={item for item in protocols if item in SUPPORTED_PROTOCOLS},
                            sources={source_name},
                        )
                    )
                walk(nested, inherited_protocols | key_protocols)
        elif isinstance(value, list):
            for item in value:
                walk(item, inherited_protocols)
        elif isinstance(value, str):
            for endpoint, detected in parse_endpoint_text(value):
                protocols = detected | inherited_protocols
                if not protocols:
                    protocols = normalize_protocol(default_protocol)
                if not protocols and default_protocol == "auto":
                    protocols = fallback
                add(
                    Candidate(
                        endpoint=endpoint,
                        protocols={item for item in protocols if item in SUPPORTED_PROTOCOLS},
                        sources={source_name},
                    )
                )

    walk(data)
    return result


def parse_payload(
    text: str,
    payload_format: str,
    source_name: str,
    default_protocol: str,
    fallback_protocols: Iterable[str],
) -> dict[str, Candidate]:
    if payload_format.lower() == "json":
        return parse_json(text, source_name, default_protocol, fallback_protocols)
    return parse_text(text, source_name, default_protocol, fallback_protocols)
