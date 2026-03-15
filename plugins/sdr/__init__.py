# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SDR (Software Defined Radio) plugin package.

Generic SDR plugin base + HackRF-specific implementation.

To create a new SDR backend (RTL-SDR, Airspy, etc.), subclass
SDRPlugin and override the hardware-specific methods.
"""
from __future__ import annotations

from .plugin import SDRPlugin
from .hackrf import HackRFPlugin

__all__ = ["SDRPlugin", "HackRFPlugin"]
