# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HackRF One device detection and management via subprocess wrappers."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Optional

log = logging.getLogger("hackrf.device")


class HackRFDevice:
    """Interface to a HackRF One device via command-line tools.

    All operations use subprocess calls to hackrf_* binaries.
    No Python bindings required.
    """

    def __init__(self):
        self._info: dict | None = None
        self._available: bool | None = None

    @property
    def is_available(self) -> bool:
        """Check if hackrf_info binary exists on PATH."""
        if self._available is None:
            self._available = shutil.which("hackrf_info") is not None
        return self._available

    def get_info(self) -> dict | None:
        """Return cached device info, or None if not yet detected."""
        return self._info

    async def detect(self) -> dict | None:
        """Run hackrf_info and parse output to detect the device.

        Returns:
            Device info dict with serial, firmware, board_id, etc., or None if not found.
        """
        if not self.is_available:
            log.warning("hackrf_info not found on PATH")
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                "hackrf_info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            log.error("hackrf_info timed out")
            return None
        except FileNotFoundError:
            log.error("hackrf_info binary not found")
            self._available = False
            return None
        except Exception as e:
            log.error(f"hackrf_info failed: {e}")
            return None

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            log.warning(f"hackrf_info returned {proc.returncode}: {err}")
            return None

        output = stdout.decode(errors="replace")
        info = self._parse_hackrf_info(output)
        if info:
            self._info = info
            log.info(f"HackRF detected: serial={info.get('serial', '?')}, "
                      f"firmware={info.get('firmware_version', '?')}")
        return info

    def _parse_hackrf_info(self, output: str) -> dict | None:
        """Parse hackrf_info output into a structured dict.

        Example output:
            hackrf_info version: 2024.02.1
            libhackrf version: 2024.02.1 (0.9)
            Found HackRF
            Index: 0
            Serial number: 0000000000000000 c66c63dc308d3d83
            Board ID Number: 2 (HackRF One)
            Firmware Version: 2024.02.1 (API version 1.08)
            Part ID Number: 0xa000cb3c 0x00724f61
            Hardware Revision: r9
            Hardware appears to have been manufactured by Great Scott Gadgets.
            Hardware supported by installed firmware.
        """
        if "Found HackRF" not in output and "Serial number" not in output:
            return None

        info: dict = {"raw_output": output}

        # Serial number (hex string, possibly space-separated halves, same line only)
        m = re.search(r"Serial number:\s+([0-9a-fA-F]+(?:[ ]+[0-9a-fA-F]+)?)", output)
        if m:
            info["serial"] = m.group(1).strip()

        # Board ID
        m = re.search(r"Board ID Number:\s+(\d+)\s*\(([^)]+)\)", output)
        if m:
            info["board_id"] = int(m.group(1))
            info["board_name"] = m.group(2)

        # Firmware version
        m = re.search(r"Firmware Version:\s+(\S+)(?:\s*\((?:API version|API:)\s*([^)]+)\))?", output)
        if m:
            info["firmware_version"] = m.group(1)
            if m.group(2):
                info["api_version"] = m.group(2)

        # Part ID
        m = re.search(r"Part ID Number:\s+(0x\w+\s+0x\w+)", output)
        if m:
            info["part_id"] = m.group(1)

        # Hardware revision
        m = re.search(r"Hardware Revision:\s+(\S+)", output)
        if m:
            info["hardware_revision"] = m.group(1)

        # hackrf_info version
        m = re.search(r"hackrf_info version:\s+(\S+)", output)
        if m:
            info["tool_version"] = m.group(1)

        # libhackrf version
        m = re.search(r"libhackrf version:\s+(\S+)", output)
        if m:
            info["lib_version"] = m.group(1)

        # Manufacturer
        m = re.search(r"manufactured by\s+(.+?)\.?\s*$", output, re.MULTILINE)
        if m:
            info["manufacturer"] = m.group(1).strip()

        return info

    async def flash_firmware(self, firmware_path: str) -> dict:
        """Flash firmware to the HackRF using hackrf_spiflash.

        Args:
            firmware_path: Path to the firmware .bin file.

        Returns:
            Dict with success status and output.
        """
        if not shutil.which("hackrf_spiflash"):
            return {"success": False, "error": "hackrf_spiflash not found on PATH"}

        try:
            proc = await asyncio.create_subprocess_exec(
                "hackrf_spiflash", "-w", firmware_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except asyncio.TimeoutError:
            return {"success": False, "error": "Flash timed out (120s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        success = proc.returncode == 0
        if success:
            log.info(f"Firmware flashed successfully from {firmware_path}")
            # Invalidate cached info since firmware changed
            self._info = None
        else:
            log.error(f"Firmware flash failed: {output}")

        return {"success": success, "output": output.strip(), "returncode": proc.returncode}

    async def set_clock(self, freq_hz: int) -> dict:
        """Set the HackRF clock frequency using hackrf_clock.

        Args:
            freq_hz: Clock frequency in Hz.

        Returns:
            Dict with success status and output.
        """
        if not shutil.which("hackrf_clock"):
            return {"success": False, "error": "hackrf_clock not found on PATH"}

        try:
            proc = await asyncio.create_subprocess_exec(
                "hackrf_clock", "-o", str(freq_hz),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            return {"success": False, "error": "hackrf_clock timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        return {
            "success": proc.returncode == 0,
            "output": output.strip(),
            "returncode": proc.returncode,
        }
