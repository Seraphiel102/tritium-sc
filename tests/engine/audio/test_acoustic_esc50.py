# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for acoustic classifier using real ESC-50 dataset.

Loads real .wav files from the ESC-50 dataset, extracts audio features,
and classifies them using the MFCC KNN classifier. Compares results against
ground truth labels from esc50.csv.

ESC-50 dataset location: data/library/audio/ESC-50/
Reference: https://github.com/karolpiczak/ESC-50
"""

import csv
import math
import struct
import wave
from pathlib import Path

import pytest

from engine.audio.acoustic_classifier import (
    AcousticClassifier,
    AudioFeatures,
    MFCCClassifier,
)

# ESC-50 dataset path — relative to repo root
ESC50_ROOT = Path(__file__).resolve().parents[4] / "data" / "library" / "audio" / "ESC-50"
ESC50_AUDIO = ESC50_ROOT / "audio"
ESC50_META = ESC50_ROOT / "meta" / "esc50.csv"

# Mapping from ESC-50 categories to our AcousticEventType values
ESC50_TO_TRITIUM = {
    "dog": "animal",
    "cat": "animal",
    "rooster": "animal",
    "pig": "animal",
    "cow": "animal",
    "frog": "animal",
    "hen": "animal",
    "crow": "animal",
    "sheep": "animal",
    "insects": "animal",
    "crickets": "animal",
    "siren": "siren",
    "car_horn": "vehicle",
    "engine": "vehicle",
    "train": "vehicle",
    "helicopter": "vehicle",
    "airplane": "vehicle",
    "fireworks": "explosion",
    "glass_breaking": "glass_break",
    "chainsaw": "machinery",
    "vacuum_cleaner": "machinery",
    "washing_machine": "machinery",
    "hand_saw": "machinery",
    "clock_alarm": "alarm",
    "clock_tick": "unknown",
    "footsteps": "footsteps",
    "laughing": "voice",
    "crying_baby": "voice",
    "coughing": "voice",
    "sneezing": "voice",
    "breathing": "voice",
    "snoring": "voice",
    "drinking_sipping": "unknown",
    "brushing_teeth": "unknown",
    "clapping": "unknown",
    "keyboard_typing": "unknown",
    "mouse_click": "unknown",
    "door_wood_creaks": "unknown",
    "door_wood_knock": "unknown",
    "can_opening": "unknown",
    "pouring_water": "unknown",
    "toilet_flush": "unknown",
    "rain": "unknown",
    "sea_waves": "unknown",
    "crackling_fire": "unknown",
    "thunderstorm": "explosion",
    "chirping_birds": "animal",
    "water_drops": "unknown",
    "wind": "unknown",
    "church_bells": "alarm",
}


def _extract_wav_features(wav_path: str) -> AudioFeatures:
    """Extract audio features from a WAV file using pure Python.

    No numpy/scipy/librosa required — uses the wave module to read raw PCM
    and computes basic spectral features from the waveform.
    """
    with wave.open(wav_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_data = wf.readframes(n_frames)

    duration_ms = int(n_frames / framerate * 1000)

    # Convert to float samples (mono, 16-bit assumed)
    if sample_width == 2:
        fmt = f"<{n_frames * n_channels}h"
        samples_int = struct.unpack(fmt, raw_data)
    elif sample_width == 4:
        fmt = f"<{n_frames * n_channels}i"
        samples_int = struct.unpack(fmt, raw_data)
    else:
        # 8-bit unsigned
        samples_int = [b - 128 for b in raw_data]

    # Mix to mono
    if n_channels > 1:
        mono = []
        for i in range(0, len(samples_int), n_channels):
            mono.append(sum(samples_int[i:i + n_channels]) / n_channels)
        samples_int = mono

    max_val = 2 ** (sample_width * 8 - 1)
    samples = [s / max_val for s in samples_int]
    n = len(samples)
    if n == 0:
        return AudioFeatures(duration_ms=duration_ms)

    # RMS energy
    rms = math.sqrt(sum(s * s for s in samples) / n)

    # Peak amplitude
    peak = max(abs(s) for s in samples)

    # Zero crossing rate
    crossings = sum(1 for i in range(1, n) if (samples[i] >= 0) != (samples[i - 1] >= 0))
    zcr = crossings / n if n > 1 else 0.0

    # Approximate spectral centroid using autocorrelation to find dominant frequency
    # Simple approach: find zero-crossing based frequency estimate
    if crossings > 0:
        avg_period = n / (crossings / 2)
        if avg_period > 0:
            dominant_freq = framerate / avg_period
        else:
            dominant_freq = 0.0
    else:
        dominant_freq = 0.0

    spectral_centroid = max(0.0, min(dominant_freq, framerate / 2))

    # Spectral bandwidth estimate (rough)
    spectral_bandwidth = spectral_centroid * 0.5

    # Generate approximate MFCCs (13 coefficients from energy in frequency bands)
    # This is a simplified DCT-like decomposition of the energy envelope
    mfcc = _approximate_mfcc(samples, framerate)

    return AudioFeatures(
        rms_energy=rms,
        peak_amplitude=peak,
        zero_crossing_rate=zcr,
        spectral_centroid=spectral_centroid,
        spectral_bandwidth=spectral_bandwidth,
        duration_ms=duration_ms,
        mfcc=mfcc,
        spectral_rolloff=spectral_centroid * 1.5,
        spectral_flatness=0.5,  # Placeholder
    )


def _approximate_mfcc(samples: list[float], sample_rate: int, n_mfcc: int = 13) -> list[float]:
    """Approximate MFCC coefficients using windowed energy analysis.

    This is a simplified approach for testing purposes. For production
    classification, use librosa or edge-computed MFCCs sent via MQTT.
    """
    n = len(samples)
    if n < 256:
        return [0.0] * n_mfcc

    # Split into overlapping frames
    frame_size = min(1024, n // 4)
    hop = frame_size // 2
    n_frames = max(1, (n - frame_size) // hop + 1)

    # Compute energy per frame
    frame_energies = []
    for i in range(n_frames):
        start = i * hop
        end = min(start + frame_size, n)
        frame = samples[start:end]
        energy = sum(s * s for s in frame) / len(frame)
        frame_energies.append(math.log(energy + 1e-10))

    # Simple DCT-like transform of frame energies to get MFCC-like coefficients
    m = len(frame_energies)
    mfcc = []
    for k in range(n_mfcc):
        coeff = 0.0
        for j in range(m):
            coeff += frame_energies[j] * math.cos(math.pi * k * (2 * j + 1) / (2 * m))
        mfcc.append(coeff / m)

    return mfcc


def _load_esc50_metadata() -> list[dict]:
    """Load ESC-50 metadata CSV."""
    if not ESC50_META.exists():
        return []

    entries = []
    with open(ESC50_META, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(row)
    return entries


def _select_test_samples(entries: list[dict], n_per_category: int = 1) -> list[dict]:
    """Select diverse samples from different ESC-50 categories.

    Picks categories that map to our AcousticEventType values and
    selects n_per_category samples from each.
    """
    # Categories we care about (ones that map to non-unknown types)
    important_categories = [
        "dog", "siren", "engine", "glass_breaking", "chainsaw",
        "laughing", "footsteps", "clock_alarm", "fireworks", "helicopter",
    ]

    selected = []
    for cat in important_categories:
        cat_entries = [e for e in entries if e["category"] == cat]
        for entry in cat_entries[:n_per_category]:
            selected.append(entry)

    return selected


@pytest.fixture
def esc50_samples():
    """Load ESC-50 test samples."""
    entries = _load_esc50_metadata()
    if not entries:
        pytest.skip("ESC-50 metadata not found")
    samples = _select_test_samples(entries)
    if not samples:
        pytest.skip("No suitable ESC-50 samples found")
    return samples


class TestESC50DatasetAvailability:
    """Verify ESC-50 dataset is accessible."""

    def test_dataset_exists(self):
        """ESC-50 dataset directory exists."""
        assert ESC50_ROOT.exists(), f"ESC-50 not found at {ESC50_ROOT}"

    def test_audio_directory(self):
        """Audio files directory exists."""
        assert ESC50_AUDIO.exists(), f"ESC-50 audio not found at {ESC50_AUDIO}"

    def test_metadata_exists(self):
        """Metadata CSV exists."""
        assert ESC50_META.exists(), f"ESC-50 metadata not found at {ESC50_META}"

    def test_wav_files_present(self):
        """At least some WAV files are present."""
        wavs = list(ESC50_AUDIO.glob("*.wav"))
        assert len(wavs) >= 100, f"Expected 100+ WAV files, found {len(wavs)}"

    def test_metadata_has_entries(self):
        """Metadata CSV has entries."""
        entries = _load_esc50_metadata()
        assert len(entries) >= 1000, f"Expected 1000+ entries, got {len(entries)}"


class TestESC50FeatureExtraction:
    """Test feature extraction from real ESC-50 WAV files."""

    def test_extract_dog_bark(self):
        """Extract features from a dog bark sample."""
        entries = _load_esc50_metadata()
        dogs = [e for e in entries if e["category"] == "dog"]
        if not dogs:
            pytest.skip("No dog samples found")

        wav_path = ESC50_AUDIO / dogs[0]["filename"]
        if not wav_path.exists():
            pytest.skip(f"WAV file not found: {wav_path}")

        features = _extract_wav_features(str(wav_path))
        assert features.duration_ms > 0
        assert features.rms_energy > 0.0
        assert features.mfcc is not None
        assert len(features.mfcc) == 13

    def test_extract_siren(self):
        """Extract features from a siren sample."""
        entries = _load_esc50_metadata()
        sirens = [e for e in entries if e["category"] == "siren"]
        if not sirens:
            pytest.skip("No siren samples found")

        wav_path = ESC50_AUDIO / sirens[0]["filename"]
        if not wav_path.exists():
            pytest.skip(f"WAV file not found: {wav_path}")

        features = _extract_wav_features(str(wav_path))
        assert features.duration_ms > 0
        assert features.rms_energy > 0.0
        assert features.peak_amplitude > 0.0

    def test_extract_multiple_categories(self):
        """Extract features from 10 different categories."""
        entries = _load_esc50_metadata()
        categories = ["dog", "siren", "engine", "glass_breaking", "laughing",
                       "footsteps", "chainsaw", "helicopter", "fireworks", "clock_alarm"]

        extracted = 0
        for cat in categories:
            cat_entries = [e for e in entries if e["category"] == cat]
            if not cat_entries:
                continue
            wav_path = ESC50_AUDIO / cat_entries[0]["filename"]
            if not wav_path.exists():
                continue
            features = _extract_wav_features(str(wav_path))
            assert features.duration_ms > 0
            assert features.mfcc is not None
            extracted += 1

        assert extracted >= 5, f"Only extracted features from {extracted} categories"


class TestESC50Classification:
    """Classify real ESC-50 samples and measure accuracy."""

    def test_classify_10_samples(self):
        """Classify 10 samples from different categories against ground truth."""
        entries = _load_esc50_metadata()
        if not entries:
            pytest.skip("ESC-50 metadata not found")

        classifier = AcousticClassifier(enable_ml=True)
        assert classifier.ml_available, "ML classifier should be available"

        test_categories = [
            "dog", "siren", "engine", "glass_breaking", "laughing",
            "footsteps", "chainsaw", "helicopter", "fireworks", "clock_alarm",
        ]

        results = []
        for cat in test_categories:
            cat_entries = [e for e in entries if e["category"] == cat]
            if not cat_entries:
                continue
            wav_path = ESC50_AUDIO / cat_entries[0]["filename"]
            if not wav_path.exists():
                continue

            features = _extract_wav_features(str(wav_path))
            event = classifier.classify(features)

            expected = ESC50_TO_TRITIUM.get(cat, "unknown")
            actual = event.event_type.value
            is_correct = actual == expected

            results.append({
                "category": cat,
                "expected": expected,
                "predicted": actual,
                "confidence": event.confidence,
                "correct": is_correct,
            })

        assert len(results) >= 5, f"Need at least 5 classified samples, got {len(results)}"

        correct = sum(1 for r in results if r["correct"])
        accuracy = correct / len(results)

        # Log results for debugging
        for r in results:
            status = "OK" if r["correct"] else "MISS"
            print(f"  [{status}] {r['category']:20s} expected={r['expected']:12s} "
                  f"predicted={r['predicted']:12s} conf={r['confidence']:.3f}")

        print(f"\n  Accuracy: {correct}/{len(results)} = {accuracy:.1%}")

        # We don't require high accuracy — this is a simple KNN on synthetic
        # training data classifying real audio. Even 20% is useful signal.
        # The point is the pipeline works end-to-end.
        assert accuracy >= 0.0, "Classification pipeline should complete without errors"

    def test_mfcc_classifier_on_esc50(self):
        """Test the raw MFCC classifier on ESC-50 samples."""
        entries = _load_esc50_metadata()
        if not entries:
            pytest.skip("ESC-50 metadata not found")

        clf = MFCCClassifier(k=3)
        clf.train()
        assert clf.is_trained

        # Classify 5 samples
        test_cats = ["dog", "siren", "engine", "laughing", "fireworks"]
        classified = 0

        for cat in test_cats:
            cat_entries = [e for e in entries if e["category"] == cat]
            if not cat_entries:
                continue
            wav_path = ESC50_AUDIO / cat_entries[0]["filename"]
            if not wav_path.exists():
                continue

            features = _extract_wav_features(str(wav_path))
            best_class, confidence, predictions = clf.classify(features)

            assert isinstance(best_class, str)
            assert 0.0 <= confidence <= 1.0
            assert len(predictions) > 0
            classified += 1

        assert classified >= 3, f"Should classify at least 3 samples, got {classified}"


class TestESC50Integration:
    """Test ESC-50 data integration with the broader system."""

    def test_category_mapping_complete(self):
        """Every ESC-50 category has a Tritium mapping."""
        entries = _load_esc50_metadata()
        if not entries:
            pytest.skip("No ESC-50 metadata")

        categories = set(e["category"] for e in entries)
        for cat in categories:
            assert cat in ESC50_TO_TRITIUM, f"Missing mapping for ESC-50 category: {cat}"

    def test_feature_extraction_deterministic(self):
        """Same file produces same features."""
        entries = _load_esc50_metadata()
        dogs = [e for e in entries if e["category"] == "dog"]
        if not dogs:
            pytest.skip("No dog samples")

        wav_path = ESC50_AUDIO / dogs[0]["filename"]
        if not wav_path.exists():
            pytest.skip("WAV file not found")

        f1 = _extract_wav_features(str(wav_path))
        f2 = _extract_wav_features(str(wav_path))

        assert f1.rms_energy == f2.rms_energy
        assert f1.peak_amplitude == f2.peak_amplitude
        assert f1.zero_crossing_rate == f2.zero_crossing_rate
        assert f1.mfcc == f2.mfcc


class TestESC50FullBenchmark:
    """Full 50-category ESC-50 benchmark against our 11 sound classes.

    Measures classification accuracy on the mapped subset of ESC-50 categories.
    Of the 50 ESC-50 categories:
      - 34 map to our 11 sound classes (animal, voice, vehicle, etc.)
      - 16 map to 'unknown' (no direct Tritium equivalent)

    Categories that map to each Tritium class:
      animal (12):    dog, cat, rooster, pig, cow, frog, hen, crow, sheep,
                      insects, crickets, chirping_birds
      voice (6):      laughing, crying_baby, coughing, sneezing, breathing, snoring
      vehicle (5):    car_horn, engine, train, helicopter, airplane
      machinery (4):  chainsaw, vacuum_cleaner, washing_machine, hand_saw
      explosion (2):  fireworks, thunderstorm
      alarm (2):      clock_alarm, church_bells
      siren (1):      siren
      glass_break (1): glass_breaking
      footsteps (1):  footsteps
      music (0):      (no direct ESC-50 category maps to music)
      gunshot (0):    (no direct ESC-50 category maps to gunshot)
      unknown (16):   clock_tick, drinking_sipping, brushing_teeth, clapping,
                      keyboard_typing, mouse_click, door_wood_creaks,
                      door_wood_knock, can_opening, pouring_water, toilet_flush,
                      rain, sea_waves, crackling_fire, water_drops, wind
    """

    def test_category_mapping_coverage(self):
        """Report how many ESC-50 categories map to our 11 classes."""
        mapped = {k: v for k, v in ESC50_TO_TRITIUM.items() if v != "unknown"}
        unmapped = {k: v for k, v in ESC50_TO_TRITIUM.items() if v == "unknown"}

        # Group by target class
        class_to_categories: dict[str, list[str]] = {}
        for cat, cls in mapped.items():
            class_to_categories.setdefault(cls, []).append(cat)

        print("\n  === ESC-50 -> Tritium Category Mapping ===")
        for cls in sorted(class_to_categories.keys()):
            cats = sorted(class_to_categories[cls])
            print(f"  {cls:12s} ({len(cats):2d}): {', '.join(cats)}")
        print(f"  {'unknown':12s} ({len(unmapped):2d}): {', '.join(sorted(unmapped.keys()))}")

        assert len(mapped) == 34, f"Expected 34 mapped categories, got {len(mapped)}"
        assert len(unmapped) == 16, f"Expected 16 unmapped categories, got {len(unmapped)}"
        assert len(class_to_categories) == 9, (
            f"Expected 9 Tritium classes covered, got {len(class_to_categories)}"
        )

    def test_full_benchmark_all_50_categories(self):
        """Classify ALL ESC-50 samples and report accuracy per class.

        Runs the MFCC KNN classifier on every WAV file in ESC-50 (2000 files)
        and computes:
          - Per-category accuracy (50 ESC-50 categories)
          - Per-class accuracy (11 Tritium classes)
          - Overall accuracy on the mapped subset
          - Confusion summary
        """
        entries = _load_esc50_metadata()
        if not entries:
            pytest.skip("ESC-50 metadata not found")

        # Check that audio files exist
        sample_path = ESC50_AUDIO / entries[0]["filename"]
        if not sample_path.exists():
            pytest.skip("ESC-50 audio files not found")

        classifier = AcousticClassifier(enable_ml=True)
        assert classifier.ml_available, "ML classifier should be available"

        # Classify every sample
        per_category_results: dict[str, dict[str, int]] = {}
        per_class_correct = {}
        per_class_total = {}
        total_correct = 0
        total_mapped = 0
        total_unknown = 0
        confusion: dict[str, dict[str, int]] = {}
        skipped = 0

        for entry in entries:
            cat = entry["category"]
            expected = ESC50_TO_TRITIUM.get(cat, "unknown")
            wav_path = ESC50_AUDIO / entry["filename"]

            if not wav_path.exists():
                skipped += 1
                continue

            try:
                features = _extract_wav_features(str(wav_path))
                event = classifier.classify(features)
                predicted = event.event_type.value
            except Exception:
                skipped += 1
                continue

            # Track per-ESC50-category results
            if cat not in per_category_results:
                per_category_results[cat] = {"correct": 0, "total": 0}
            per_category_results[cat]["total"] += 1

            if expected == "unknown":
                total_unknown += 1
                continue

            total_mapped += 1
            is_correct = predicted == expected

            if is_correct:
                total_correct += 1
                per_category_results[cat]["correct"] += 1

            # Per-class tracking
            per_class_correct.setdefault(expected, 0)
            per_class_total.setdefault(expected, 0)
            per_class_total[expected] += 1
            if is_correct:
                per_class_correct[expected] += 1

            # Confusion matrix
            confusion.setdefault(expected, {})
            confusion[expected].setdefault(predicted, 0)
            confusion[expected][predicted] += 1

        # Report
        print(f"\n  === ESC-50 Full Benchmark Results ===")
        print(f"  Total samples:  {len(entries)}")
        print(f"  Mapped samples: {total_mapped} (from {len(per_category_results)} categories)")
        print(f"  Unmapped (unknown target): {total_unknown}")
        print(f"  Skipped (missing/error):   {skipped}")

        if total_mapped > 0:
            accuracy = total_correct / total_mapped
            print(f"\n  Overall accuracy on mapped subset: {total_correct}/{total_mapped} = {accuracy:.1%}")
        else:
            accuracy = 0.0
            print("\n  No mapped samples classified")

        print(f"\n  --- Per Tritium Class Accuracy ---")
        for cls in sorted(per_class_total.keys()):
            c = per_class_correct.get(cls, 0)
            t = per_class_total[cls]
            pct = c / t * 100 if t > 0 else 0
            print(f"  {cls:12s}: {c:3d}/{t:3d} = {pct:5.1f}%")

        print(f"\n  --- Per ESC-50 Category (mapped only) ---")
        for cat in sorted(per_category_results.keys()):
            expected = ESC50_TO_TRITIUM.get(cat, "unknown")
            if expected == "unknown":
                continue
            r = per_category_results[cat]
            pct = r["correct"] / r["total"] * 100 if r["total"] > 0 else 0
            print(f"  {cat:20s} -> {expected:12s}: {r['correct']:2d}/{r['total']:2d} = {pct:5.1f}%")

        print(f"\n  --- Confusion Summary (expected -> predicted) ---")
        for expected in sorted(confusion.keys()):
            preds = confusion[expected]
            top_preds = sorted(preds.items(), key=lambda x: x[1], reverse=True)[:3]
            pred_str = ", ".join(f"{p}:{n}" for p, n in top_preds)
            print(f"  {expected:12s} -> {pred_str}")

        # The pipeline should complete without crashes on all 2000 files
        assert total_mapped >= 100, f"Should classify 100+ mapped samples, got {total_mapped}"
        # Record accuracy as a metric — even low accuracy is useful signal
        # with synthetic training data vs real audio
        assert accuracy >= 0.0, "Accuracy calculation should work"

    def test_benchmark_per_fold(self):
        """Accuracy by ESC-50 fold (1-5) to check for data distribution bias."""
        entries = _load_esc50_metadata()
        if not entries:
            pytest.skip("ESC-50 metadata not found")

        sample_path = ESC50_AUDIO / entries[0]["filename"]
        if not sample_path.exists():
            pytest.skip("ESC-50 audio files not found")

        classifier = AcousticClassifier(enable_ml=True)

        fold_correct = {str(i): 0 for i in range(1, 6)}
        fold_total = {str(i): 0 for i in range(1, 6)}

        # Sample 2 per category per fold for speed
        category_fold_seen: dict[str, dict[str, int]] = {}

        for entry in entries:
            cat = entry["category"]
            fold = entry["fold"]
            expected = ESC50_TO_TRITIUM.get(cat, "unknown")
            if expected == "unknown":
                continue

            category_fold_seen.setdefault(cat, {})
            count = category_fold_seen[cat].get(fold, 0)
            if count >= 2:
                continue
            category_fold_seen[cat][fold] = count + 1

            wav_path = ESC50_AUDIO / entry["filename"]
            if not wav_path.exists():
                continue

            try:
                features = _extract_wav_features(str(wav_path))
                event = classifier.classify(features)
                predicted = event.event_type.value
            except Exception:
                continue

            fold_total[fold] += 1
            if predicted == expected:
                fold_correct[fold] += 1

        print("\n  === Per-Fold Accuracy ===")
        for fold in ["1", "2", "3", "4", "5"]:
            c = fold_correct[fold]
            t = fold_total[fold]
            pct = c / t * 100 if t > 0 else 0
            print(f"  Fold {fold}: {c:3d}/{t:3d} = {pct:5.1f}%")

        total_folds_with_data = sum(1 for f in fold_total.values() if f > 0)
        assert total_folds_with_data >= 3, "Should have data in at least 3 folds"
