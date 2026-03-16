# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Server-side geo-reference — thin re-export from tritium_lib.geo.

All coordinate transform logic now lives in tritium-lib (the shared
library used by both tritium-sc and tritium-edge).  This module
re-exports everything so existing ``from engine.tactical.geo import ...``
statements continue to work without modification.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

# Re-export everything from the canonical source in tritium-lib.
# If tritium-lib is not installed, fall back to a minimal local stub
# so that import-time errors don't break the server entirely.

_USE_LIB = False
try:
    from tritium_lib.geo import (  # noqa: F401 — re-export
        METERS_PER_DEG_LAT,
        CameraCalibration,
        GeoReference,
        camera_pixel_to_ground,
        get_reference,
        haversine_distance,
        init_reference,
        is_initialized,
        latlng_to_local,
        local_to_latlng,
        local_to_latlng_2d,
        reset,
    )
    _USE_LIB = True
except ImportError:
    pass

if not _USE_LIB:
    # Fallback: tritium-lib not installed — local implementation
    METERS_PER_DEG_LAT = 111_320.0

    @dataclass
    class GeoReference:  # type: ignore[no-redef]
        lat: float = 0.0
        lng: float = 0.0
        alt: float = 0.0
        initialized: bool = False

        @property
        def meters_per_deg_lng(self) -> float:
            return METERS_PER_DEG_LAT * math.cos(math.radians(self.lat))

    @dataclass
    class CameraCalibration:  # type: ignore[no-redef]
        position: tuple[float, float]
        heading: float
        fov_h: float = 60.0
        mount_height: float = 2.5
        max_range: float = 30.0

    _ref = GeoReference()
    _lock = threading.Lock()

    def init_reference(lat: float, lng: float, alt: float = 0.0) -> GeoReference:  # type: ignore[misc]
        global _ref
        with _lock:
            _ref = GeoReference(lat=lat, lng=lng, alt=alt, initialized=True)
        return _ref

    def get_reference() -> GeoReference:  # type: ignore[misc]
        return _ref

    def is_initialized() -> bool:  # type: ignore[misc]
        return _ref.initialized

    def reset() -> None:  # type: ignore[misc]
        global _ref
        with _lock:
            _ref = GeoReference()

    def local_to_latlng(x: float, y: float, z: float = 0.0) -> dict:  # type: ignore[misc]
        ref = _ref
        if not ref.initialized:
            return {"lat": 0.0, "lng": 0.0, "alt": z}
        lat = ref.lat + y / METERS_PER_DEG_LAT
        lng = ref.lng + x / ref.meters_per_deg_lng
        alt = ref.alt + z
        return {"lat": lat, "lng": lng, "alt": alt}

    def latlng_to_local(lat: float, lng: float, alt: float = 0.0) -> tuple[float, float, float]:  # type: ignore[misc]
        ref = _ref
        if not ref.initialized:
            return (0.0, 0.0, alt)
        y = (lat - ref.lat) * METERS_PER_DEG_LAT
        x = (lng - ref.lng) * ref.meters_per_deg_lng
        z = alt - ref.alt
        return (x, y, z)

    def local_to_latlng_2d(x: float, y: float) -> tuple[float, float]:  # type: ignore[misc]
        result = local_to_latlng(x, y, 0.0)
        return (result["lat"], result["lng"])

    def camera_pixel_to_ground(cx: float, cy: float, calib: CameraCalibration) -> tuple[float, float] | None:  # type: ignore[misc]
        angle_h = (cx - 0.5) * calib.fov_h
        bearing = calib.heading + angle_h
        if cy < 0.1:
            return None
        range_factor = 1.0 - cy
        range_m = 2.0 + range_factor * calib.max_range
        bearing_rad = math.radians(bearing)
        dx = range_m * math.sin(bearing_rad)
        dy = range_m * math.cos(bearing_rad)
        return (calib.position[0] + dx, calib.position[1] + dy)

    def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:  # type: ignore[misc]
        R = 6_371_000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lng2 - lng1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
