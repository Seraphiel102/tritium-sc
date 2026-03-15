# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WiFi probe request multi-node proximity estimator.

When multiple edge nodes see the same device probing for the same SSID,
the timing differences between observations can estimate which node the
device is closest to. This is a simple proximity estimation technique
that doesn't require synchronized clocks — it uses relative timing
within short windows.

Algorithm:
  1. Collect probe observations from multiple nodes within a time window.
  2. For each (device_mac, ssid) pair seen by 2+ nodes, rank nodes by
     the earliest observation timestamp and strongest RSSI.
  3. The node that sees the probe first AND with strongest RSSI is most
     likely the closest to the device.
  4. Produce a ProximityEstimate with ranked node distances.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("wifi-fingerprint.proximity")

# Time window for considering probes as the "same" transmission (seconds)
TIMING_WINDOW = 5.0
# Minimum nodes that must see a probe for proximity estimation
MIN_NODES = 2
# Maximum history per device MAC
MAX_HISTORY = 200
# Prune entries older than this (seconds)
STALE_THRESHOLD = 300.0


@dataclass(slots=True)
class ProbeObservation:
    """A single probe observation from one edge node."""
    device_mac: str
    ssid: str
    node_id: str
    rssi: int
    timestamp: float
    ntp_timestamp: float = 0.0  # NTP epoch if available (from edge)
    channel: int = 0


@dataclass
class ProximityEstimate:
    """Estimated proximity ranking of a device to edge nodes."""
    device_mac: str
    ssid: str
    timestamp: float
    node_rankings: list[dict[str, Any]]  # [{node_id, rssi, time_delta, rank, score}]
    closest_node: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_mac": self.device_mac,
            "ssid": self.ssid,
            "timestamp": self.timestamp,
            "closest_node": self.closest_node,
            "confidence": round(self.confidence, 3),
            "node_rankings": self.node_rankings,
        }


class ProbeProximityEstimator:
    """Estimates device proximity to edge nodes from probe request timing.

    Feed probe observations from multiple edge nodes. The estimator
    detects when the same device probes for the same SSID from multiple
    nodes and estimates which node is closest based on timing and RSSI.
    """

    def __init__(self, event_bus: Any = None) -> None:
        self._event_bus = event_bus
        self._lock = threading.Lock()
        # Recent observations keyed by device_mac
        self._observations: dict[str, list[ProbeObservation]] = defaultdict(list)
        # Recent proximity estimates
        self._estimates: list[ProximityEstimate] = []
        self._max_estimates = 500

    def ingest_probe(
        self,
        device_mac: str,
        ssid: str,
        node_id: str,
        rssi: int,
        timestamp: float | None = None,
        ntp_timestamp: float = 0.0,
        channel: int = 0,
    ) -> ProximityEstimate | None:
        """Ingest a probe observation and check for multi-node proximity estimation.

        Returns a ProximityEstimate if enough nodes have seen this device
        probing for this SSID recently, else None.
        """
        device_mac = device_mac.lower()
        ts = timestamp or time.time()

        obs = ProbeObservation(
            device_mac=device_mac,
            ssid=ssid,
            node_id=node_id,
            rssi=rssi,
            timestamp=ts,
            ntp_timestamp=ntp_timestamp,
            channel=channel,
        )

        with self._lock:
            self._observations[device_mac].append(obs)
            # Trim history
            if len(self._observations[device_mac]) > MAX_HISTORY:
                self._observations[device_mac] = self._observations[device_mac][-MAX_HISTORY:]

            # Check for multi-node observations of this device + SSID
            return self._check_proximity(device_mac, ssid, ts)

    def _check_proximity(
        self, device_mac: str, ssid: str, now: float
    ) -> ProximityEstimate | None:
        """Check if we have enough multi-node observations for a proximity estimate."""
        if not ssid:
            return None

        # Find recent observations of this device + SSID from different nodes
        cutoff = now - TIMING_WINDOW
        recent = [
            obs for obs in self._observations[device_mac]
            if obs.ssid == ssid and obs.timestamp > cutoff
        ]

        # Deduplicate by node_id — keep the earliest (strongest timing signal)
        node_best: dict[str, ProbeObservation] = {}
        for obs in recent:
            if obs.node_id not in node_best or obs.timestamp < node_best[obs.node_id].timestamp:
                node_best[obs.node_id] = obs

        if len(node_best) < MIN_NODES:
            return None

        # Rank nodes by timing (earliest first) and RSSI (strongest first)
        nodes = list(node_best.values())
        earliest_time = min(n.timestamp for n in nodes)

        rankings: list[dict[str, Any]] = []
        for obs in nodes:
            time_delta = obs.timestamp - earliest_time
            rankings.append({
                "node_id": obs.node_id,
                "rssi": obs.rssi,
                "time_delta": round(time_delta, 4),
                "channel": obs.channel,
            })

        # Score: combine timing rank and RSSI rank
        # Lower time_delta = better, higher RSSI = better
        rankings.sort(key=lambda r: (r["time_delta"], -r["rssi"]))
        for i, r in enumerate(rankings):
            r["rank"] = i + 1
            # Score: timing contributes 60%, RSSI 40%
            timing_score = max(0.0, 1.0 - r["time_delta"] / TIMING_WINDOW)
            rssi_score = max(0.0, min(1.0, (r["rssi"] + 100) / 60.0))  # -100 -> 0, -40 -> 1
            r["score"] = round(timing_score * 0.6 + rssi_score * 0.4, 3)

        closest = rankings[0]["node_id"]
        confidence = rankings[0]["score"]

        # If second node has very similar scores, reduce confidence
        if len(rankings) > 1:
            score_gap = rankings[0]["score"] - rankings[1]["score"]
            if score_gap < 0.1:
                confidence *= 0.7  # uncertain — nodes are too close

        estimate = ProximityEstimate(
            device_mac=device_mac,
            ssid=ssid,
            timestamp=now,
            node_rankings=rankings,
            closest_node=closest,
            confidence=round(confidence, 3),
        )

        self._estimates.append(estimate)
        if len(self._estimates) > self._max_estimates:
            self._estimates = self._estimates[-self._max_estimates:]

        # Publish event
        if self._event_bus is not None:
            self._event_bus.publish("wifi_probe:proximity", data=estimate.to_dict())

        logger.debug(
            "Probe proximity: %s probed '%s' — closest to %s (conf=%.2f, %d nodes)",
            device_mac, ssid, closest, confidence, len(rankings),
        )

        return estimate

    def get_estimates(
        self, device_mac: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get recent proximity estimates, optionally filtered by device."""
        with self._lock:
            if device_mac:
                filtered = [
                    e for e in self._estimates
                    if e.device_mac == device_mac.lower()
                ]
            else:
                filtered = list(self._estimates)
            return [e.to_dict() for e in reversed(filtered[-limit:])]

    def get_closest_node(self, device_mac: str) -> str | None:
        """Get the most recent closest-node estimate for a device."""
        device_mac = device_mac.lower()
        with self._lock:
            for est in reversed(self._estimates):
                if est.device_mac == device_mac:
                    return est.closest_node
        return None

    def get_status(self) -> dict[str, Any]:
        """Return estimator status for API."""
        with self._lock:
            return {
                "tracked_devices": len(self._observations),
                "total_estimates": len(self._estimates),
                "total_observations": sum(
                    len(obs) for obs in self._observations.values()
                ),
            }

    def prune_stale(self, max_age: float = STALE_THRESHOLD) -> int:
        """Remove old observations."""
        cutoff = time.time() - max_age
        pruned = 0
        with self._lock:
            for mac in list(self._observations.keys()):
                old_len = len(self._observations[mac])
                self._observations[mac] = [
                    o for o in self._observations[mac] if o.timestamp > cutoff
                ]
                pruned += old_len - len(self._observations[mac])
                if not self._observations[mac]:
                    del self._observations[mac]
        return pruned
