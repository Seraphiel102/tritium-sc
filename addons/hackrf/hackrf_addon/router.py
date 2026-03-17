# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the HackRF One SDR addon."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File
from typing import Optional

import tempfile
import os


def create_router(device, spectrum, receiver) -> APIRouter:
    """Create FastAPI router for HackRF addon endpoints.

    Args:
        device: HackRFDevice instance.
        spectrum: SpectrumAnalyzer instance.
        receiver: FMReceiver instance.

    Returns:
        Configured APIRouter.
    """

    router = APIRouter()

    @router.get("/status")
    async def status():
        """Overall HackRF addon status."""
        info = device.get_info()
        return {
            "available": device.is_available,
            "connected": info is not None,
            "device": {
                "serial": info.get("serial", "") if info else "",
                "firmware": info.get("firmware_version", "") if info else "",
                "board": info.get("board_name", "") if info else "",
            },
            "sweep": spectrum.get_status(),
            "receiver": receiver.get_status(),
        }

    @router.get("/info")
    async def info():
        """Full device info from hackrf_info.

        Runs hackrf_info and returns parsed output. Refreshes cached info.
        """
        result = await device.detect()
        if result is None:
            return {
                "available": device.is_available,
                "connected": False,
                "error": "HackRF not detected. Is the device connected?",
            }
        # Remove raw output from API response (it's large)
        clean = {k: v for k, v in result.items() if k != "raw_output"}
        clean["connected"] = True
        return clean

    @router.get("/ports")
    async def detect_ports():
        """Detect connected HackRF devices.

        Checks for HackRF by running hackrf_info. Unlike serial devices,
        HackRF uses USB bulk transfer (not serial ports).
        """
        info = await device.detect()
        devices = []
        if info:
            devices.append({
                "type": "hackrf-one",
                "serial": info.get("serial", ""),
                "firmware": info.get("firmware_version", ""),
                "board": info.get("board_name", "HackRF One"),
                "hardware_revision": info.get("hardware_revision", ""),
            })
        return {
            "devices": devices,
            "count": len(devices),
            "hackrf_info_available": device.is_available,
        }

    @router.post("/sweep/start")
    async def sweep_start(body: dict = None):
        """Start a spectrum sweep.

        Body: {
            "freq_start": 88,       // Start frequency in MHz (default 0)
            "freq_end": 108,        // End frequency in MHz (default 6000)
            "bin_width": 500000     // Bin width in Hz (default 500000)
        }
        """
        body = body or {}
        freq_start = int(body.get("freq_start", 0))
        freq_end = int(body.get("freq_end", 6000))
        bin_width = int(body.get("bin_width", 500_000))
        return await spectrum.start_sweep(freq_start, freq_end, bin_width)

    @router.post("/sweep/stop")
    async def sweep_stop():
        """Stop the running spectrum sweep."""
        return await spectrum.stop_sweep()

    @router.get("/sweep/data")
    async def sweep_data():
        """Get latest sweep data points.

        Returns the most recent sweep as a list of {freq_hz, power_dbm} points.
        """
        data = spectrum.get_data()
        return {
            "data": data,
            "count": len(data),
            "status": spectrum.get_status(),
        }

    @router.get("/sweep/peaks")
    async def sweep_peaks(threshold: float = -30.0):
        """Get frequency peaks above threshold.

        Query params:
            threshold: Minimum power in dBm (default -30).
        """
        peaks = spectrum.signal_db.get_peaks(threshold_dbm=threshold)
        return {
            "peaks": peaks,
            "count": len(peaks),
            "threshold_dbm": threshold,
        }

    @router.post("/tune")
    async def tune(body: dict):
        """Tune the receiver to a frequency.

        Body: {
            "freq_hz": 100000000,    // Center frequency in Hz
            "sample_rate": 2000000,  // Sample rate in Hz (optional)
            "lna_gain": 32,          // LNA gain 0-40 dB (optional)
            "vga_gain": 20           // VGA gain 0-62 dB (optional)
        }
        """
        freq_hz = int(body.get("freq_hz", 100_000_000))
        result = receiver.tune(freq_hz)
        if not result.get("success"):
            return result

        # Optionally start capture immediately
        if body.get("start_capture", False):
            capture_result = await receiver.start(
                freq_hz=freq_hz,
                sample_rate=body.get("sample_rate"),
                lna_gain=body.get("lna_gain"),
                vga_gain=body.get("vga_gain"),
                duration_seconds=body.get("duration_seconds"),
            )
            result["capture"] = capture_result

        return result

    @router.post("/capture/start")
    async def capture_start(body: dict = None):
        """Start IQ sample capture.

        Body: {
            "freq_hz": 100000000,      // Center frequency in Hz
            "sample_rate": 2000000,    // Sample rate (default 2 MSPS)
            "lna_gain": 32,            // LNA gain (default 32)
            "vga_gain": 20,            // VGA gain (default 20)
            "duration_seconds": null   // null = continuous
        }
        """
        body = body or {}
        return await receiver.start(
            freq_hz=body.get("freq_hz"),
            sample_rate=body.get("sample_rate"),
            lna_gain=body.get("lna_gain"),
            vga_gain=body.get("vga_gain"),
            duration_seconds=body.get("duration_seconds"),
        )

    @router.post("/capture/stop")
    async def capture_stop():
        """Stop IQ sample capture."""
        return await receiver.stop()

    @router.get("/capture/list")
    async def capture_list():
        """List all IQ capture files."""
        captures = receiver.get_captures()
        return {"captures": captures, "count": len(captures)}

    @router.get("/firmware")
    async def firmware_info():
        """Get firmware version information."""
        info = device.get_info()
        if not info:
            # Try to detect
            info = await device.detect()
        if not info:
            return {"error": "HackRF not detected"}
        return {
            "firmware_version": info.get("firmware_version", ""),
            "api_version": info.get("api_version", ""),
            "tool_version": info.get("tool_version", ""),
            "lib_version": info.get("lib_version", ""),
            "hardware_revision": info.get("hardware_revision", ""),
        }

    @router.post("/flash")
    async def flash_firmware(firmware: UploadFile = File(...)):
        """Flash firmware to the HackRF.

        Upload a .bin firmware file. The device will be flashed using hackrf_spiflash.
        WARNING: This is a destructive operation. Ensure the firmware is correct.
        """
        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            content = await firmware.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = await device.flash_firmware(tmp_path)
            return result
        finally:
            os.unlink(tmp_path)

    @router.get("/health")
    async def health():
        """Addon health check."""
        info = device.get_info()
        return {
            "status": "ok" if info else "degraded",
            "available": device.is_available,
            "connected": info is not None,
            "sweep_running": spectrum.is_running,
        }

    return router
