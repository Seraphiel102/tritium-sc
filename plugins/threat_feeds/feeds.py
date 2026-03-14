# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Threat feed manager — load, store, and query known-bad indicators.

Supports indicator types: mac, ip, ssid, device_name.
Persists to data/threat_feeds/indicators.json.
Integrates with the enrichment pipeline as a provider.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("threat-feeds")

# Valid indicator types
INDICATOR_TYPES = {"mac", "ip", "ssid", "device_name"}


@dataclass
class ThreatIndicator:
    """A single known-bad indicator from a threat intelligence feed."""

    indicator_type: str  # mac, ip, ssid, device_name
    value: str
    threat_level: str = "suspicious"  # suspicious, hostile
    source: str = "manual"
    description: str = ""
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ThreatIndicator:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def match_key(self) -> str:
        """Normalized lookup key: (type, upper-value)."""
        return f"{self.indicator_type}:{self.value.upper()}"


class ThreatFeedManager:
    """Central registry of known-bad indicators.

    Thread-safe. Persists state to JSON on every mutation.
    """

    def __init__(self, data_dir: str | None = None) -> None:
        if data_dir is None:
            data_dir = os.path.join(os.getcwd(), "data", "threat_feeds")
        self._data_dir = data_dir
        self._indicators_path = os.path.join(data_dir, "indicators.json")
        self._lock = threading.Lock()
        # Keyed by match_key() for O(1) lookup
        self._indicators: dict[str, ThreatIndicator] = {}
        self._load_from_disk()

    # -- Persistence -----------------------------------------------------------

    def _load_from_disk(self) -> None:
        """Load indicators from the JSON persistence file."""
        if not os.path.exists(self._indicators_path):
            return
        try:
            with open(self._indicators_path, "r") as f:
                raw = json.load(f)
            for entry in raw:
                ind = ThreatIndicator.from_dict(entry)
                self._indicators[ind.match_key()] = ind
            logger.info("Loaded %d threat indicators from %s",
                        len(self._indicators), self._indicators_path)
        except Exception as exc:
            logger.error("Failed to load threat indicators: %s", exc)

    def _save_to_disk(self) -> None:
        """Persist current indicators to JSON."""
        os.makedirs(self._data_dir, exist_ok=True)
        data = [ind.to_dict() for ind in self._indicators.values()]
        try:
            with open(self._indicators_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save threat indicators: %s", exc)

    # -- CRUD ------------------------------------------------------------------

    def add_indicator(self, indicator: ThreatIndicator) -> ThreatIndicator:
        """Add or update a single indicator. Returns the stored indicator."""
        if indicator.indicator_type not in INDICATOR_TYPES:
            raise ValueError(
                f"Invalid indicator_type '{indicator.indicator_type}'. "
                f"Must be one of: {INDICATOR_TYPES}"
            )
        key = indicator.match_key()
        with self._lock:
            existing = self._indicators.get(key)
            if existing is not None:
                # Update: keep earliest first_seen, refresh last_seen
                indicator.first_seen = existing.first_seen
                indicator.last_seen = time.time()
            self._indicators[key] = indicator
            self._save_to_disk()
        logger.info("Added threat indicator: %s", key)
        return indicator

    def remove_indicator(self, indicator_type: str, value: str) -> bool:
        """Remove an indicator. Returns True if it existed."""
        key = f"{indicator_type}:{value.upper()}"
        with self._lock:
            removed = self._indicators.pop(key, None)
            if removed is not None:
                self._save_to_disk()
                return True
        return False

    def check(self, indicator_type: str, value: str) -> ThreatIndicator | None:
        """Check if a value matches a known-bad indicator.

        Returns the ThreatIndicator if found, None otherwise.
        """
        key = f"{indicator_type}:{value.upper()}"
        with self._lock:
            ind = self._indicators.get(key)
            if ind is not None:
                ind.last_seen = time.time()
            return ind

    def check_mac(self, mac: str) -> ThreatIndicator | None:
        """Convenience: check a MAC address against threat feeds."""
        return self.check("mac", mac)

    def check_ssid(self, ssid: str) -> ThreatIndicator | None:
        """Convenience: check an SSID against threat feeds."""
        return self.check("ssid", ssid)

    def check_ip(self, ip: str) -> ThreatIndicator | None:
        """Convenience: check an IP address against threat feeds."""
        return self.check("ip", ip)

    def get_all(self, indicator_type: str | None = None) -> list[ThreatIndicator]:
        """Return all indicators, optionally filtered by type."""
        with self._lock:
            if indicator_type is None:
                return list(self._indicators.values())
            return [
                ind for ind in self._indicators.values()
                if ind.indicator_type == indicator_type
            ]

    @property
    def count(self) -> int:
        """Total number of indicators."""
        with self._lock:
            return len(self._indicators)

    # -- Bulk import -----------------------------------------------------------

    def load_indicators(self, file_path: str) -> int:
        """Load indicators from a JSON or CSV file. Returns count imported."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_path.endswith(".csv"):
            return self._load_csv(file_path)
        else:
            return self._load_json(file_path)

    def load_indicators_from_content(
        self, content: str, format: str = "json"
    ) -> int:
        """Load indicators from string content (json or csv)."""
        if format == "csv":
            return self._parse_csv(content)
        else:
            return self._parse_json(content)

    def _load_json(self, file_path: str) -> int:
        with open(file_path, "r") as f:
            raw = json.load(f)
        return self._import_list(raw)

    def _parse_json(self, content: str) -> int:
        raw = json.loads(content)
        if isinstance(raw, dict):
            raw = raw.get("indicators", [raw])
        return self._import_list(raw)

    def _load_csv(self, file_path: str) -> int:
        with open(file_path, "r") as f:
            return self._parse_csv(f.read())

    def _parse_csv(self, content: str) -> int:
        reader = csv.DictReader(io.StringIO(content))
        entries = list(reader)
        return self._import_list(entries)

    def _import_list(self, entries: list[dict]) -> int:
        count = 0
        for entry in entries:
            try:
                ind = ThreatIndicator.from_dict(entry)
                if ind.indicator_type in INDICATOR_TYPES and ind.value:
                    self.add_indicator(ind)
                    count += 1
            except Exception as exc:
                logger.warning("Skipping invalid indicator entry: %s", exc)
        return count

    # -- Enrichment provider ---------------------------------------------------

    async def enrichment_provider(
        self, target_id: str, identifiers: dict
    ) -> Any:
        """Enrichment pipeline provider callback.

        Checks MAC, SSID, IP, and device_name against known-bad indicators.
        Returns an EnrichmentResult if any match is found.
        """
        # Import here to avoid circular dependency
        from engine.tactical.enrichment import EnrichmentResult

        # Check all identifier types
        checks = [
            ("mac", identifiers.get("mac", "")),
            ("ssid", identifiers.get("ssid", "")),
            ("ip", identifiers.get("ip", "")),
            ("device_name", identifiers.get("name", "")),
        ]

        for ind_type, value in checks:
            if not value:
                continue
            match = self.check(ind_type, value)
            if match is not None:
                return EnrichmentResult(
                    provider="threat_feed",
                    enrichment_type="threat_match",
                    data={
                        "indicator_type": match.indicator_type,
                        "value": match.value,
                        "threat_level": match.threat_level,
                        "source": match.source,
                        "description": match.description,
                    },
                    confidence=0.95,
                )
        return None


# ---------------------------------------------------------------------------
# Seed data — example known-bad indicators for testing and demos
# ---------------------------------------------------------------------------

SEED_INDICATORS: list[dict] = [
    # Known-bad MACs (synthetic examples)
    {
        "indicator_type": "mac",
        "value": "DE:AD:BE:EF:00:01",
        "threat_level": "hostile",
        "source": "tritium-intel",
        "description": "Known rogue access point MAC",
    },
    {
        "indicator_type": "mac",
        "value": "DE:AD:BE:EF:00:02",
        "threat_level": "hostile",
        "source": "tritium-intel",
        "description": "Known wardriving device",
    },
    {
        "indicator_type": "mac",
        "value": "AA:BB:CC:DD:EE:01",
        "threat_level": "suspicious",
        "source": "community-feed",
        "description": "Suspected BLE tracker/stalkerware",
    },
    {
        "indicator_type": "mac",
        "value": "AA:BB:CC:DD:EE:02",
        "threat_level": "suspicious",
        "source": "community-feed",
        "description": "Suspected WiFi deauth device",
    },
    {
        "indicator_type": "mac",
        "value": "11:22:33:44:55:66",
        "threat_level": "hostile",
        "source": "tritium-intel",
        "description": "Known packet injection hardware",
    },
    # Known-bad SSIDs
    {
        "indicator_type": "ssid",
        "value": "FreeWiFi-EVIL",
        "threat_level": "hostile",
        "source": "tritium-intel",
        "description": "Known evil twin access point SSID",
    },
    {
        "indicator_type": "ssid",
        "value": "WiFi-Pineapple",
        "threat_level": "hostile",
        "source": "tritium-intel",
        "description": "WiFi Pineapple default SSID",
    },
    {
        "indicator_type": "ssid",
        "value": "FREE_INTERNET",
        "threat_level": "suspicious",
        "source": "community-feed",
        "description": "Commonly used honeypot SSID",
    },
    {
        "indicator_type": "ssid",
        "value": "linksys",
        "threat_level": "suspicious",
        "source": "community-feed",
        "description": "Default router SSID — potential impersonation",
    },
    {
        "indicator_type": "ssid",
        "value": "xfinitywifi-clone",
        "threat_level": "hostile",
        "source": "tritium-intel",
        "description": "Known evil twin targeting Xfinity customers",
    },
]


def seed_default_indicators(manager: ThreatFeedManager) -> int:
    """Load the default seed indicators into the manager.

    Only adds indicators that are not already present. Returns count added.
    """
    count = 0
    for entry in SEED_INDICATORS:
        ind = ThreatIndicator.from_dict(entry)
        existing = manager.check(ind.indicator_type, ind.value)
        if existing is None:
            manager.add_indicator(ind)
            count += 1
    return count
