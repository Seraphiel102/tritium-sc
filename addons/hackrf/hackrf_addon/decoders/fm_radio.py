# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FM radio demodulation using hackrf_transfer + numpy/scipy.

Captures IQ samples via hackrf_transfer subprocess, then performs
wideband FM demodulation entirely in Python with numpy and scipy.
No GNU Radio dependency required.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("hackrf.decoders.fm")

# Common US FM stations (frequency Hz -> call sign)
# Extend this table as needed
US_FM_STATIONS: dict[int, str] = {
    87_900_000: "WFMT 87.9",
    88_100_000: "WCPE 88.1",
    88_500_000: "WAMU 88.5",
    88_700_000: "WRFG 88.7",
    89_300_000: "KPCC 89.3",
    89_900_000: "WKCR 89.9",
    90_100_000: "WBUR 90.1",
    90_700_000: "WFUV 90.7",
    91_500_000: "WBEZ 91.5",
    91_900_000: "WUOM 91.9",
    92_300_000: "KCNR 92.3",
    93_100_000: "WPAT 93.1",
    93_900_000: "WKYS 93.9",
    94_700_000: "WMAS 94.7",
    95_500_000: "WPLJ 95.5",
    96_300_000: "WBBM 96.3",
    97_100_000: "WASH 97.1",
    97_900_000: "WSKQ 97.9",
    98_700_000: "WRKS 98.7",
    99_500_000: "WBAI 99.5",
    100_300_000: "WHTZ 100.3",
    101_100_000: "WCBS 101.1",
    101_900_000: "WLIR 101.9",
    102_700_000: "WNEW 102.7",
    103_500_000: "WKTU 103.5",
    104_300_000: "WAXQ 104.3",
    105_100_000: "WWPR 105.1",
    105_900_000: "WQXR 105.9",
    106_700_000: "WLTW 106.7",
    107_500_000: "WBLS 107.5",
}

# Audio output directory
DEFAULT_AUDIO_DIR = Path("/tmp/hackrf_audio")


class FMRadioDecoder:
    """FM broadcast radio demodulator.

    Uses hackrf_transfer to capture raw IQ samples, then demodulates
    FM audio using scipy signal processing. Outputs PCM float32 audio
    at 48 kHz sample rate.
    """

    def __init__(self, capture_dir: str | Path | None = None):
        self._capture_dir = Path(capture_dir) if capture_dir else DEFAULT_AUDIO_DIR
        self._audio_rate: int = 48_000
        self._last_capture: Path | None = None
        self._last_audio: np.ndarray | None = None
        self._last_freq_hz: int = 0

    async def capture_iq(
        self,
        freq_hz: int,
        duration_s: float = 5.0,
        sample_rate: int = 2_000_000,
        lna_gain: int = 32,
        vga_gain: int = 20,
    ) -> Path:
        """Capture IQ samples from HackRF at the given frequency.

        Args:
            freq_hz: Center frequency in Hz (e.g. 101_100_000 for 101.1 MHz).
            duration_s: Capture duration in seconds.
            sample_rate: Sample rate in samples/sec (default 2 MSPS).
            lna_gain: LNA gain 0-40 dB.
            vga_gain: VGA gain 0-62 dB.

        Returns:
            Path to the raw IQ capture file.

        Raises:
            RuntimeError: If hackrf_transfer fails.
        """
        self._capture_dir.mkdir(parents=True, exist_ok=True)
        num_samples = int(sample_rate * duration_s)
        freq_mhz = freq_hz / 1_000_000

        # Use a temp file for the capture
        capture_file = self._capture_dir / f"fm_{freq_mhz:.1f}MHz_{int(time.time())}.raw"

        cmd = [
            "hackrf_transfer",
            "-r", str(capture_file),
            "-f", str(freq_hz),
            "-s", str(sample_rate),
            "-l", str(max(0, min(40, lna_gain))),
            "-g", str(max(0, min(62, vga_gain))),
            "-n", str(num_samples),
        ]

        log.info(f"Capturing IQ: {freq_mhz:.1f} MHz, {duration_s}s, {sample_rate} SPS")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=duration_s + 30.0,
        )

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"hackrf_transfer failed (rc={proc.returncode}): {err}")

        if not capture_file.exists() or capture_file.stat().st_size == 0:
            raise RuntimeError("hackrf_transfer produced no output")

        self._last_capture = capture_file
        self._last_freq_hz = freq_hz
        log.info(f"Captured {capture_file.stat().st_size} bytes to {capture_file}")
        return capture_file

    def demodulate_fm(
        self,
        iq_data: np.ndarray | Path | str,
        sample_rate: int = 2_000_000,
        audio_rate: int = 48_000,
    ) -> np.ndarray:
        """Demodulate wideband FM from IQ samples.

        Pipeline:
        1. Load interleaved int8 IQ data from hackrf_transfer
        2. Convert to complex64
        3. Low-pass filter (150 kHz cutoff for FM broadcast)
        4. FM discriminator (instantaneous frequency via angle difference)
        5. Decimate to audio sample rate
        6. De-emphasis filter (75 us time constant, US standard)

        Args:
            iq_data: Either a numpy array of complex64 samples, or a
                     Path/string to a raw IQ file from hackrf_transfer.
            sample_rate: IQ sample rate in Hz.
            audio_rate: Output audio sample rate in Hz.

        Returns:
            Float32 numpy array of audio samples at audio_rate.
        """
        from scipy.signal import firwin, lfilter, decimate

        # Load from file if needed
        if isinstance(iq_data, (str, Path)):
            raw = np.fromfile(str(iq_data), dtype=np.int8)
            # hackrf_transfer outputs interleaved I, Q as int8
            if len(raw) % 2 != 0:
                raw = raw[:len(raw) - 1]
            iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
            iq /= 128.0  # Normalize to [-1, 1]
        elif isinstance(iq_data, np.ndarray):
            if np.issubdtype(iq_data.dtype, np.complexfloating):
                iq = iq_data.astype(np.complex64)
            else:
                # Assume interleaved int8
                raw = iq_data.astype(np.float32)
                iq = raw[0::2] + 1j * raw[1::2]
                iq /= 128.0
        else:
            raise TypeError(f"Unsupported iq_data type: {type(iq_data)}")

        if len(iq) < 100:
            raise ValueError(f"IQ data too short: {len(iq)} samples")

        log.info(f"Demodulating {len(iq)} IQ samples at {sample_rate} SPS")

        # Step 1: Low-pass filter — FM broadcast channel is +/- 100 kHz
        # Use a wider filter (150 kHz) to capture the full signal
        fm_bw = 150_000  # Hz
        num_taps = 101
        lpf_cutoff = fm_bw / (sample_rate / 2)
        lpf_cutoff = min(lpf_cutoff, 0.99)  # Keep below Nyquist
        lpf = firwin(num_taps, lpf_cutoff)
        iq_filtered = lfilter(lpf, 1.0, iq)

        # Step 2: FM discriminator — instantaneous frequency
        # d/dt(angle(iq)) = freq deviation
        # Using the conjugate-multiply method: angle(iq[n] * conj(iq[n-1]))
        iq_diff = iq_filtered[1:] * np.conj(iq_filtered[:-1])
        fm_demod = np.angle(iq_diff)

        # Step 3: Decimate to audio rate
        decimation_factor = sample_rate // audio_rate
        if decimation_factor < 1:
            decimation_factor = 1

        if decimation_factor > 1 and len(fm_demod) > decimation_factor * 10:
            # Use scipy decimate for anti-aliased downsampling
            # Break into stages if factor is large
            audio = fm_demod
            remaining = decimation_factor
            while remaining > 1:
                stage = min(remaining, 10)  # scipy decimate max factor per stage
                if len(audio) > stage * 10:
                    audio = decimate(audio, stage, ftype="fir", zero_phase=True)
                else:
                    # Too few samples for decimate, just slice
                    audio = audio[::stage]
                remaining //= stage
                if remaining <= 1:
                    break
        else:
            audio = fm_demod[::max(1, decimation_factor)]

        # Step 4: De-emphasis filter (75 us for US FM, reduces high-freq hiss)
        tau = 75e-6  # 75 microseconds
        dt = 1.0 / audio_rate
        alpha = dt / (tau + dt)
        deemph = np.zeros_like(audio)
        if len(audio) > 0:
            deemph[0] = audio[0]
            for i in range(1, len(audio)):
                deemph[i] = alpha * audio[i] + (1 - alpha) * deemph[i - 1]
            audio = deemph

        # Normalize to [-1, 1]
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.9  # Leave a bit of headroom

        self._last_audio = audio.astype(np.float32)
        self._audio_rate = audio_rate
        log.info(f"Demodulated: {len(audio)} audio samples at {audio_rate} Hz "
                 f"({len(audio) / audio_rate:.1f}s)")
        return self._last_audio

    def save_wav(
        self,
        audio: np.ndarray,
        filename: str | Path,
        sample_rate: int = 48_000,
    ) -> Path:
        """Save audio samples to a WAV file.

        Args:
            audio: Float32 audio samples in [-1, 1] range.
            filename: Output WAV file path.
            sample_rate: Audio sample rate in Hz.

        Returns:
            Path to the saved WAV file.
        """
        filepath = Path(filename)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Convert float32 [-1,1] to int16
        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767).astype(np.int16)

        with wave.open(str(filepath), "w") as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        log.info(f"Saved WAV: {filepath} ({len(audio) / sample_rate:.1f}s, {filepath.stat().st_size} bytes)")
        return filepath

    def get_station_name(self, freq_hz: int) -> str:
        """Look up a US FM station by frequency.

        Rounds to nearest 100 kHz (FM channel spacing).

        Args:
            freq_hz: Frequency in Hz.

        Returns:
            Station call sign string, or "Unknown" if not in table.
        """
        # Round to nearest 100 kHz (US FM channel spacing)
        rounded = round(freq_hz / 100_000) * 100_000
        return US_FM_STATIONS.get(rounded, f"Unknown ({rounded / 1_000_000:.1f} MHz)")

    async def tune_and_demod(
        self,
        freq_hz: int,
        duration_s: float = 5.0,
        sample_rate: int = 2_000_000,
        save_audio: bool = True,
    ) -> dict:
        """Convenience: capture IQ, demodulate FM, optionally save WAV.

        Args:
            freq_hz: FM frequency in Hz.
            duration_s: Capture duration.
            sample_rate: IQ sample rate.
            save_audio: Whether to save a WAV file.

        Returns:
            Dict with capture info, audio stats, and optional WAV path.
        """
        capture_file = await self.capture_iq(freq_hz, duration_s, sample_rate)
        audio = self.demodulate_fm(capture_file, sample_rate)

        result = {
            "freq_hz": freq_hz,
            "freq_mhz": freq_hz / 1_000_000,
            "station": self.get_station_name(freq_hz),
            "capture_file": str(capture_file),
            "capture_size_bytes": capture_file.stat().st_size,
            "audio_samples": len(audio),
            "audio_duration_s": round(len(audio) / self._audio_rate, 2),
            "audio_rate": self._audio_rate,
            "audio_peak": float(np.max(np.abs(audio))),
            "audio_rms": float(np.sqrt(np.mean(audio ** 2))),
        }

        if save_audio:
            freq_mhz = freq_hz / 1_000_000
            wav_path = self._capture_dir / f"fm_{freq_mhz:.1f}MHz_{int(time.time())}.wav"
            self.save_wav(audio, wav_path, self._audio_rate)
            result["wav_file"] = str(wav_path)

        return result
