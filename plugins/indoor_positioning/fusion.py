# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WiFi fingerprint + BLE RSSI position fusion engine.

Combines two indoor positioning methods:
  1. WiFi fingerprint matching (kNN on RSSI vectors against reference database)
  2. BLE RSSI-based trilateration (weighted centroid from multi-node observations)

The fused position is a confidence-weighted average of both estimates.
Each method produces a position with a confidence score; the fusion
weights each position proportionally to its confidence.

Output: indoor position estimate with uncertainty radius in meters.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("indoor-positioning.fusion")

# kNN parameters
DEFAULT_K = 3  # number of neighbors for kNN fingerprint matching
MIN_COMMON_BSSIDS = 2  # minimum overlapping BSSIDs for a valid fingerprint match

# Confidence floor — never let a method contribute less than this
CONFIDENCE_FLOOR = 0.05

# Maximum distance (in RSSI Euclidean space) before fingerprint match is rejected
MAX_FINGERPRINT_DISTANCE = 30.0

# Uncertainty radius scaling — maps confidence to meters
# confidence 1.0 -> ~1m uncertainty, 0.1 -> ~15m uncertainty
UNCERTAINTY_BASE_METERS = 1.5
UNCERTAINTY_SCALE = 15.0


@dataclass
class PositionEstimate:
    """A single-method position estimate."""
    lat: float
    lon: float
    confidence: float
    method: str  # "fingerprint", "trilateration", "fused"
    uncertainty_m: float = 0.0  # uncertainty radius in meters
    anchors_used: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lat": round(self.lat, 8),
            "lon": round(self.lon, 8),
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "uncertainty_m": round(self.uncertainty_m, 2),
            "anchors_used": self.anchors_used,
            "metadata": self.metadata,
        }


@dataclass
class FusedPosition:
    """Result of fusing multiple position estimates."""
    target_id: str
    lat: float
    lon: float
    confidence: float
    uncertainty_m: float
    method: str = "fused"
    wifi_estimate: Optional[PositionEstimate] = None
    ble_estimate: Optional[PositionEstimate] = None
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    floor_level: int = 0
    building: str = ""
    plan_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "target_id": self.target_id,
            "lat": round(self.lat, 8),
            "lon": round(self.lon, 8),
            "confidence": round(self.confidence, 4),
            "uncertainty_m": round(self.uncertainty_m, 2),
            "method": self.method,
            "timestamp": self.timestamp,
        }
        if self.wifi_estimate:
            result["wifi_estimate"] = self.wifi_estimate.to_dict()
        if self.ble_estimate:
            result["ble_estimate"] = self.ble_estimate.to_dict()
        if self.room_id is not None:
            result["room_id"] = self.room_id
        if self.room_name is not None:
            result["room_name"] = self.room_name
        if self.floor_level != 0:
            result["floor_level"] = self.floor_level
        if self.building:
            result["building"] = self.building
        if self.plan_id:
            result["plan_id"] = self.plan_id
        return result


def confidence_to_uncertainty(confidence: float) -> float:
    """Convert a 0-1 confidence to an uncertainty radius in meters.

    Higher confidence -> smaller uncertainty.
    confidence=1.0 -> ~1.5m, confidence=0.1 -> ~15m
    """
    clamped = max(0.01, min(1.0, confidence))
    return UNCERTAINTY_BASE_METERS + UNCERTAINTY_SCALE * (1.0 - clamped)


def knn_fingerprint_match(
    observed_rssi: dict[str, float],
    fingerprints: list[dict],
    k: int = DEFAULT_K,
) -> Optional[PositionEstimate]:
    """Match observed WiFi RSSI vector against fingerprint database using kNN.

    Each fingerprint has: rssi_map (dict[bssid, rssi]), lat, lon, room_id, plan_id.
    Returns the weighted-average position of the k nearest neighbors, or None.
    """
    if not fingerprints or not observed_rssi:
        return None

    # Compute distance to each fingerprint
    scored: list[tuple[float, dict]] = []

    for fp in fingerprints:
        fp_rssi = fp.get("rssi_map", {})
        if not fp_rssi:
            continue

        common = set(observed_rssi.keys()) & set(fp_rssi.keys())
        if len(common) < MIN_COMMON_BSSIDS:
            continue

        dist_sq = sum(
            (observed_rssi[bssid] - fp_rssi[bssid]) ** 2 for bssid in common
        )
        # Normalize by number of common BSSIDs for fair comparison
        distance = math.sqrt(dist_sq / len(common))

        if distance <= MAX_FINGERPRINT_DISTANCE:
            scored.append((distance, fp))

    if not scored:
        return None

    # Sort by distance, take k nearest
    scored.sort(key=lambda x: x[0])
    neighbors = scored[:k]

    # Weighted average: closer neighbors get higher weight (inverse distance)
    total_weight = 0.0
    w_lat = 0.0
    w_lon = 0.0

    for distance, fp in neighbors:
        # Avoid division by zero for exact matches
        weight = 1.0 / max(distance, 0.01)
        fp_lat = fp.get("lat", 0.0)
        fp_lon = fp.get("lon", 0.0)
        if fp_lat == 0.0 and fp_lon == 0.0:
            continue
        w_lat += weight * fp_lat
        w_lon += weight * fp_lon
        total_weight += weight

    if total_weight == 0.0:
        return None

    avg_lat = w_lat / total_weight
    avg_lon = w_lon / total_weight

    # Confidence: based on best match distance and number of neighbors
    best_distance = neighbors[0][0]
    confidence = max(0.1, min(1.0, 1.0 - best_distance / MAX_FINGERPRINT_DISTANCE))
    # Boost for more neighbors
    neighbor_boost = min(1.0, len(neighbors) / k)
    confidence *= (0.7 + 0.3 * neighbor_boost)
    confidence = min(1.0, confidence)

    return PositionEstimate(
        lat=avg_lat,
        lon=avg_lon,
        confidence=round(confidence, 4),
        method="fingerprint",
        uncertainty_m=confidence_to_uncertainty(confidence),
        anchors_used=len(neighbors),
        metadata={
            "k_used": len(neighbors),
            "best_distance": round(best_distance, 2),
            "best_room_id": neighbors[0][1].get("room_id"),
        },
    )


def fuse_positions(
    wifi_est: Optional[PositionEstimate],
    ble_est: Optional[PositionEstimate],
    target_id: str = "",
) -> Optional[FusedPosition]:
    """Fuse WiFi fingerprint and BLE trilateration position estimates.

    Uses confidence-weighted averaging. If only one method produced a result,
    that result is returned directly (no fusion needed).

    Returns None if neither method produced an estimate.
    """
    if wifi_est is None and ble_est is None:
        return None

    # Single-source fallback
    if wifi_est is None:
        return FusedPosition(
            target_id=target_id,
            lat=ble_est.lat,
            lon=ble_est.lon,
            confidence=ble_est.confidence,
            uncertainty_m=ble_est.uncertainty_m,
            method="trilateration",
            ble_estimate=ble_est,
        )

    if ble_est is None:
        return FusedPosition(
            target_id=target_id,
            lat=wifi_est.lat,
            lon=wifi_est.lon,
            confidence=wifi_est.confidence,
            uncertainty_m=wifi_est.uncertainty_m,
            method="fingerprint",
            wifi_estimate=wifi_est,
        )

    # Both available — weighted fusion
    w_wifi = max(CONFIDENCE_FLOOR, wifi_est.confidence)
    w_ble = max(CONFIDENCE_FLOOR, ble_est.confidence)
    total_w = w_wifi + w_ble

    fused_lat = (w_wifi * wifi_est.lat + w_ble * ble_est.lat) / total_w
    fused_lon = (w_wifi * wifi_est.lon + w_ble * ble_est.lon) / total_w

    # Fused confidence is higher than either individual (information gain)
    fused_confidence = min(
        1.0,
        1.0 - (1.0 - wifi_est.confidence) * (1.0 - ble_est.confidence),
    )

    fused_uncertainty = confidence_to_uncertainty(fused_confidence)

    return FusedPosition(
        target_id=target_id,
        lat=round(fused_lat, 8),
        lon=round(fused_lon, 8),
        confidence=round(fused_confidence, 4),
        uncertainty_m=round(fused_uncertainty, 2),
        method="fused",
        wifi_estimate=wifi_est,
        ble_estimate=ble_est,
    )


class IndoorPositionFusion:
    """Stateful indoor position fusion engine.

    Holds references to the trilateration engine and floorplan store,
    and produces fused position estimates on demand.

    Thread-safe.
    """

    def __init__(
        self,
        trilateration_engine: Any = None,
        floorplan_store: Any = None,
        k: int = DEFAULT_K,
    ) -> None:
        self._trilat = trilateration_engine
        self._store = floorplan_store
        self._k = k
        self._lock = threading.Lock()
        # Cache of recent WiFi RSSI observations per target
        # target_id -> {bssid: rssi}
        self._wifi_observations: dict[str, dict[str, float]] = {}
        # Cache of recent fused positions
        self._positions: dict[str, FusedPosition] = {}

    def update_wifi_observation(
        self, target_id: str, rssi_map: dict[str, float]
    ) -> None:
        """Update the WiFi RSSI observation for a target."""
        with self._lock:
            self._wifi_observations[target_id] = rssi_map

    def estimate_position(self, target_id: str) -> Optional[FusedPosition]:
        """Produce a fused indoor position for a target.

        Combines:
          1. WiFi fingerprint kNN match (if WiFi observations exist)
          2. BLE trilateration (if trilateration engine has data)

        Returns the fused position, or None if no data is available.
        """
        wifi_est = self._get_wifi_estimate(target_id)
        ble_est = self._get_ble_estimate(target_id)

        fused = fuse_positions(wifi_est, ble_est, target_id=target_id)
        if fused is None:
            return None

        # Room-level localization
        self._assign_room(fused)

        with self._lock:
            self._positions[target_id] = fused

        return fused

    def get_cached_position(self, target_id: str) -> Optional[FusedPosition]:
        """Get the most recently computed fused position for a target."""
        with self._lock:
            return self._positions.get(target_id)

    def get_all_positions(self) -> dict[str, FusedPosition]:
        """Get all cached fused positions."""
        with self._lock:
            return dict(self._positions)

    def _get_wifi_estimate(self, target_id: str) -> Optional[PositionEstimate]:
        """Get WiFi fingerprint position estimate for a target."""
        with self._lock:
            rssi_map = self._wifi_observations.get(target_id)

        if not rssi_map or self._store is None:
            return None

        fingerprints = self._store.get_fingerprints()
        if not fingerprints:
            return None

        return knn_fingerprint_match(rssi_map, fingerprints, k=self._k)

    def _get_ble_estimate(self, target_id: str) -> Optional[PositionEstimate]:
        """Get BLE trilateration position estimate for a target."""
        if self._trilat is None:
            return None

        # Extract MAC from target_id (e.g., "ble_AA:BB:CC:DD:EE:FF" -> "AA:BB:CC:DD:EE:FF")
        mac = target_id
        if mac.startswith("ble_"):
            mac = mac[4:]

        result = self._trilat.estimate_position(mac)
        if result is None:
            return None

        return PositionEstimate(
            lat=result.lat,
            lon=result.lon,
            confidence=result.confidence,
            method="trilateration",
            uncertainty_m=confidence_to_uncertainty(result.confidence),
            anchors_used=result.anchors_used,
        )

    def _assign_room(self, fused: FusedPosition) -> None:
        """Assign room-level localization to a fused position.

        Searches all active floor plans for the room containing the point.
        """
        if self._store is None:
            return

        try:
            plans = self._store.list_plans(status="active")
        except Exception:
            plans = []

        for plan in plans:
            bounds = plan.get("bounds")
            if bounds:
                if not (
                    bounds.get("south", -90) <= fused.lat <= bounds.get("north", 90)
                    and bounds.get("west", -180) <= fused.lon <= bounds.get("east", 180)
                ):
                    continue

            for room in plan.get("rooms", []):
                polygon = room.get("polygon", [])
                if len(polygon) < 3:
                    continue
                if _point_in_polygon(fused.lat, fused.lon, polygon):
                    fused.room_id = room.get("room_id")
                    fused.room_name = room.get("name", room.get("room_id"))
                    fused.floor_level = room.get(
                        "floor_level", plan.get("floor_level", 0)
                    )
                    fused.building = plan.get("building", "")
                    fused.plan_id = plan.get("plan_id", "")
                    return

            # Check if inside plan bounds but not a specific room
            if bounds and (
                bounds.get("south", -90) <= fused.lat <= bounds.get("north", 90)
                and bounds.get("west", -180) <= fused.lon <= bounds.get("east", 180)
            ):
                fused.floor_level = plan.get("floor_level", 0)
                fused.building = plan.get("building", "")
                fused.plan_id = plan.get("plan_id", "")
                return

    @property
    def tracked_targets(self) -> int:
        """Number of targets with cached positions."""
        with self._lock:
            return len(self._positions)

    def clear(self) -> None:
        """Clear all cached data."""
        with self._lock:
            self._wifi_observations.clear()
            self._positions.clear()


def _point_in_polygon(lat: float, lon: float, polygon: list[dict]) -> bool:
    """Ray-casting point-in-polygon test."""
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        pi_lat = polygon[i].get("lat", 0)
        pi_lon = polygon[i].get("lon", 0)
        pj_lat = polygon[j].get("lat", 0)
        pj_lon = polygon[j].get("lon", 0)

        if ((pi_lon > lon) != (pj_lon > lon)) and (
            lat < (pj_lat - pi_lat) * (lon - pi_lon) / (pj_lon - pi_lon) + pi_lat
        ):
            inside = not inside
        j = i
    return inside
