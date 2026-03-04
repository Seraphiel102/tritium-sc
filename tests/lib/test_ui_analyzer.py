# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for UIAnalyzer — generalized UI analysis framework.

All tests use synthetic numpy images. No browser, no server, no models.
"""
from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.unit


class TestDetectBlobs:
    """Test blob detection with synthetic images."""

    def test_finds_green_circles(self):
        """Create 480x640 black image, draw 5 green circles, detect all 5."""
        from tests.lib.ui_analyzer import UIAnalyzer
        from tests.lib.ui_colors import FRIENDLY_GREEN_BGR

        img = np.zeros((480, 640, 3), dtype=np.uint8)
        centers = [(100, 100), (200, 200), (300, 300), (400, 150), (500, 350)]
        for cx, cy in centers:
            cv2.circle(img, (cx, cy), 20, FRIENDLY_GREEN_BGR, -1)

        analyzer = UIAnalyzer()
        blobs = analyzer.detect_blobs(img, FRIENDLY_GREEN_BGR)
        assert len(blobs) == 5

    def test_tolerance_matches_shifted_color(self):
        """Draw circles with green shifted by 30 in B channel; tolerance=40 detects."""
        from tests.lib.ui_analyzer import UIAnalyzer
        from tests.lib.ui_colors import FRIENDLY_GREEN_BGR

        img = np.zeros((480, 640, 3), dtype=np.uint8)
        shifted = (FRIENDLY_GREEN_BGR[0] + 30, FRIENDLY_GREEN_BGR[1], FRIENDLY_GREEN_BGR[2])
        for cx, cy in [(100, 100), (300, 300), (500, 200)]:
            cv2.circle(img, (cx, cy), 20, shifted, -1)

        analyzer = UIAnalyzer()
        blobs = analyzer.detect_blobs(img, FRIENDLY_GREEN_BGR, tolerance=40)
        assert len(blobs) == 3

    def test_filters_small_blobs(self):
        """Draw 3 large circles + 2 tiny dots; min_area=100 finds only 3."""
        from tests.lib.ui_analyzer import UIAnalyzer
        from tests.lib.ui_colors import HOSTILE_RED_BGR

        img = np.zeros((480, 640, 3), dtype=np.uint8)
        # Large circles (radius 20 -> area ~1256)
        cv2.circle(img, (100, 100), 20, HOSTILE_RED_BGR, -1)
        cv2.circle(img, (300, 200), 20, HOSTILE_RED_BGR, -1)
        cv2.circle(img, (500, 300), 20, HOSTILE_RED_BGR, -1)
        # Tiny dots (radius 2 -> area ~12)
        cv2.circle(img, (200, 400), 2, HOSTILE_RED_BGR, -1)
        cv2.circle(img, (400, 400), 2, HOSTILE_RED_BGR, -1)

        analyzer = UIAnalyzer()
        blobs = analyzer.detect_blobs(img, HOSTILE_RED_BGR, min_area=100)
        assert len(blobs) == 3

    def test_blob_has_correct_fields(self):
        """Each BlobInfo has center_x, center_y, area, bbox."""
        from tests.lib.ui_analyzer import UIAnalyzer, BlobInfo
        from tests.lib.ui_colors import CYAN_PRIMARY_BGR

        img = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(img, (100, 100), 15, CYAN_PRIMARY_BGR, -1)

        analyzer = UIAnalyzer()
        blobs = analyzer.detect_blobs(img, CYAN_PRIMARY_BGR)
        assert len(blobs) == 1
        blob = blobs[0]
        assert isinstance(blob, BlobInfo)
        assert isinstance(blob.center_x, int)
        assert isinstance(blob.center_y, int)
        assert blob.area > 0
        assert len(blob.bbox) == 4

    def test_no_blobs_on_empty_image(self):
        """All-black image returns empty list."""
        from tests.lib.ui_analyzer import UIAnalyzer
        from tests.lib.ui_colors import FRIENDLY_GREEN_BGR

        img = np.zeros((480, 640, 3), dtype=np.uint8)
        analyzer = UIAnalyzer()
        blobs = analyzer.detect_blobs(img, FRIENDLY_GREEN_BGR)
        assert len(blobs) == 0


class TestMeasureSpread:
    """Test spatial spread measurement."""

    def test_single_blob_zero_spread(self):
        """1 blob -> std_dev near 0."""
        from tests.lib.ui_analyzer import UIAnalyzer, BlobInfo

        blobs = [BlobInfo(center_x=100, center_y=100, area=500, bbox=(90, 90, 20, 20))]
        analyzer = UIAnalyzer()
        spread = analyzer.measure_spread(blobs)
        assert spread.std_dev == pytest.approx(0.0, abs=0.01)

    def test_four_corner_blobs(self):
        """Blobs at four corners -> large span."""
        from tests.lib.ui_analyzer import UIAnalyzer, BlobInfo

        blobs = [
            BlobInfo(center_x=10, center_y=10, area=500, bbox=(0, 0, 20, 20)),
            BlobInfo(center_x=610, center_y=10, area=500, bbox=(600, 0, 20, 20)),
            BlobInfo(center_x=10, center_y=460, area=500, bbox=(0, 450, 20, 20)),
            BlobInfo(center_x=610, center_y=460, area=500, bbox=(600, 450, 20, 20)),
        ]
        analyzer = UIAnalyzer()
        spread = analyzer.measure_spread(blobs)
        assert spread.span_x == 600
        assert spread.span_y == 450
        assert spread.std_dev > 100  # large spread across the image

    def test_centroid_is_average(self):
        """Centroid is the average of blob centers."""
        from tests.lib.ui_analyzer import UIAnalyzer, BlobInfo

        blobs = [
            BlobInfo(center_x=100, center_y=200, area=500, bbox=(90, 190, 20, 20)),
            BlobInfo(center_x=300, center_y=400, area=500, bbox=(290, 390, 20, 20)),
        ]
        analyzer = UIAnalyzer()
        spread = analyzer.measure_spread(blobs)
        assert spread.centroid == (200, 300)

    def test_empty_blobs_returns_zero(self):
        """No blobs -> zero spread metrics."""
        from tests.lib.ui_analyzer import UIAnalyzer

        analyzer = UIAnalyzer()
        spread = analyzer.measure_spread([])
        assert spread.span_x == 0
        assert spread.span_y == 0
        assert spread.std_dev == 0.0


class TestContentPercentage:
    """Test non-black pixel percentage calculation."""

    def test_black_image_zero(self):
        """All black -> 0%."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        analyzer = UIAnalyzer()
        pct = analyzer.content_percentage(img)
        assert pct == pytest.approx(0.0, abs=0.1)

    def test_white_image_hundred(self):
        """All white -> 100%."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.full((100, 100, 3), 255, dtype=np.uint8)
        analyzer = UIAnalyzer()
        pct = analyzer.content_percentage(img)
        assert pct == pytest.approx(100.0, abs=0.1)

    def test_center_region_only(self):
        """White center, black border -> region measurement limited to center."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((200, 200, 3), dtype=np.uint8)
        img[50:150, 50:150] = 255  # white center

        analyzer = UIAnalyzer()
        # Measure only the white center region
        pct = analyzer.content_percentage(img, region=(50, 50, 100, 100))
        assert pct == pytest.approx(100.0, abs=0.1)

        # Full image should be about 25%
        pct_full = analyzer.content_percentage(img)
        assert 20.0 < pct_full < 30.0

    def test_custom_threshold(self):
        """Threshold controls what counts as 'content'."""
        from tests.lib.ui_analyzer import UIAnalyzer

        # Image with dim gray pixels (value 10)
        img = np.full((100, 100, 3), 10, dtype=np.uint8)
        analyzer = UIAnalyzer()
        # threshold=15 -> dim gray counted as black -> 0%
        pct_high = analyzer.content_percentage(img, threshold=15)
        assert pct_high == pytest.approx(0.0, abs=0.1)
        # threshold=5 -> dim gray counted as content -> 100%
        pct_low = analyzer.content_percentage(img, threshold=5)
        assert pct_low == pytest.approx(100.0, abs=0.1)


class TestCountElements:
    """Test element counting (distinct blobs of a color)."""

    def test_count_three_blobs(self):
        """Three separate green circles -> count=3."""
        from tests.lib.ui_analyzer import UIAnalyzer
        from tests.lib.ui_colors import FRIENDLY_GREEN_BGR

        img = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.circle(img, (50, 50), 20, FRIENDLY_GREEN_BGR, -1)
        cv2.circle(img, (150, 150), 20, FRIENDLY_GREEN_BGR, -1)
        cv2.circle(img, (250, 250), 20, FRIENDLY_GREEN_BGR, -1)

        analyzer = UIAnalyzer()
        count = analyzer.count_elements(img, FRIENDLY_GREEN_BGR)
        assert count == 3

    def test_count_zero_on_empty(self):
        """Black image -> count=0."""
        from tests.lib.ui_analyzer import UIAnalyzer
        from tests.lib.ui_colors import HOSTILE_RED_BGR

        img = np.zeros((300, 300, 3), dtype=np.uint8)
        analyzer = UIAnalyzer()
        count = analyzer.count_elements(img, HOSTILE_RED_BGR)
        assert count == 0


class TestRegionHasContent:
    """Test region content detection."""

    def test_region_with_content(self):
        """Region with bright pixels -> True."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((200, 200, 3), dtype=np.uint8)
        img[50:100, 50:100] = (200, 200, 200)

        analyzer = UIAnalyzer()
        assert analyzer.region_has_content(img, 50, 50, 50, 50) is True

    def test_empty_region(self):
        """All-black region -> False."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((200, 200, 3), dtype=np.uint8)
        analyzer = UIAnalyzer()
        assert analyzer.region_has_content(img, 50, 50, 50, 50) is False


class TestRegionHasText:
    """Test text detection via edge density."""

    def test_with_text(self):
        """Region with cv2.putText -> True."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 300, 3), dtype=np.uint8)
        cv2.putText(img, "SCORE: 1234", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

        analyzer = UIAnalyzer()
        assert analyzer.region_has_text(img, 0, 0, 300, 100) is True

    def test_empty_region(self):
        """Black region -> False."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 300, 3), dtype=np.uint8)
        analyzer = UIAnalyzer()
        assert analyzer.region_has_text(img, 0, 0, 300, 100) is False


class TestAnnotate:
    """Test bounding box annotation on images."""

    def test_draws_boxes(self):
        """Annotate green blobs -> output image differs from input."""
        from tests.lib.ui_analyzer import UIAnalyzer, BlobInfo
        from tests.lib.ui_colors import FRIENDLY_GREEN_BGR

        img = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(img, (100, 100), 20, FRIENDLY_GREEN_BGR, -1)

        blobs = [BlobInfo(center_x=100, center_y=100, area=1256, bbox=(80, 80, 40, 40))]

        analyzer = UIAnalyzer()
        annotated = analyzer.annotate(img, blobs)

        # Annotated should differ from original (has bounding boxes drawn)
        assert not np.array_equal(annotated, img)
        # Original should not be mutated
        assert img[0, 0, 0] == 0

    def test_label_fn_adds_text(self):
        """Custom label function annotates blobs with text."""
        from tests.lib.ui_analyzer import UIAnalyzer, BlobInfo

        img = np.zeros((200, 200, 3), dtype=np.uint8)
        blobs = [BlobInfo(center_x=100, center_y=100, area=1000, bbox=(80, 80, 40, 40))]

        analyzer = UIAnalyzer()
        annotated = analyzer.annotate(img, blobs, label_fn=lambda b: f"A={b.area}")

        # Should have drawn text. Check that some pixels near the bbox are non-zero.
        # The label region is above the bbox, typically around y=75..80
        roi = annotated[60:80, 70:160]
        assert roi.any(), "Expected label text near the bbox"

    def test_empty_blobs_no_change(self):
        """Annotating with no blobs returns a copy identical to original."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[10:20, 10:20] = (100, 100, 100)

        analyzer = UIAnalyzer()
        annotated = analyzer.annotate(img, [])

        assert np.array_equal(annotated, img)
        # Still a copy, not the same object
        assert annotated is not img


class TestCheck:
    """Test the composite check() method."""

    def test_all_pass(self):
        """All assertions True -> all passed_checks True."""
        from tests.lib.ui_analyzer import UIAnalyzer, AnalysisResult

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[20:80, 20:80] = (200, 200, 200)

        analyzer = UIAnalyzer()
        result = analyzer.check(
            name="test_all_pass",
            img=img,
            img_path="/tmp/test.png",
            assertions={
                "has_content": lambda: analyzer.content_percentage(img) > 0,
                "not_blank": lambda: analyzer.region_has_content(img, 20, 20, 60, 60),
            },
        )

        assert isinstance(result, AnalysisResult)
        assert result.passed_checks["has_content"] is True
        assert result.passed_checks["not_blank"] is True
        assert result.cherry_picked is False

    def test_failure_detected(self):
        """One assertion False -> that check False, rest True."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 100, 3), dtype=np.uint8)

        analyzer = UIAnalyzer()
        result = analyzer.check(
            name="test_failure",
            img=img,
            img_path="/tmp/test.png",
            assertions={
                "is_blank": lambda: analyzer.content_percentage(img) == 0.0,
                "has_green": lambda: analyzer.count_elements(img, (161, 255, 5)) > 0,
            },
        )

        assert result.passed_checks["is_blank"] is True
        assert result.passed_checks["has_green"] is False

    def test_cherry_pick_flag(self):
        """cherry_pick parameter controls cherry_picked field."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        analyzer = UIAnalyzer()

        result = analyzer.check(
            name="test_cherry",
            img=img,
            img_path="/tmp/test.png",
            assertions={"always_true": lambda: True},
            cherry_pick="best_frame_3",
        )
        assert result.cherry_picked is True

    def test_no_fleet_graceful(self):
        """fleet=None -> no crash, vision_advisory is None."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        analyzer = UIAnalyzer(fleet=None)

        result = analyzer.check(
            name="test_no_fleet",
            img=img,
            img_path="/tmp/test.png",
            assertions={"pass": lambda: True},
            vision_prompt="Is this a map?",
        )

        assert result.vision_advisory is None
        assert result.passed_checks["pass"] is True

    def test_vision_advisory_with_fleet(self):
        """When fleet is provided and vision_prompt set, advisory is populated."""
        from unittest.mock import MagicMock
        from tests.lib.ui_analyzer import UIAnalyzer

        mock_fleet = MagicMock()
        mock_fleet.generate.return_value = {
            "response": "YES, I see a tactical map.",
            "host": "local",
            "elapsed_ms": 150,
        }

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        analyzer = UIAnalyzer(fleet=mock_fleet)

        result = analyzer.check(
            name="test_with_fleet",
            img=img,
            img_path="/tmp/test.png",
            assertions={"pass": lambda: True},
            vision_prompt="Is this a map?",
        )

        assert result.vision_advisory is not None
        assert "map" in result.vision_advisory.lower()

    def test_result_has_timestamp(self):
        """AnalysisResult has a reasonable timestamp."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        analyzer = UIAnalyzer()

        before = time.time()
        result = analyzer.check(
            name="test_ts",
            img=img,
            img_path="/tmp/test.png",
            assertions={"ok": lambda: True},
        )
        after = time.time()

        assert before <= result.timestamp <= after

    def test_result_has_opencv_metrics(self):
        """check() populates opencv_metrics dict."""
        from tests.lib.ui_analyzer import UIAnalyzer

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[20:80, 20:80] = (200, 200, 200)

        analyzer = UIAnalyzer()
        result = analyzer.check(
            name="test_metrics",
            img=img,
            img_path="/tmp/test.png",
            assertions={"ok": lambda: True},
        )

        assert isinstance(result.opencv_metrics, dict)
        assert "content_pct" in result.opencv_metrics
        assert "image_shape" in result.opencv_metrics


class TestBlobInfo:
    """Test the BlobInfo dataclass."""

    def test_construction(self):
        from tests.lib.ui_analyzer import BlobInfo
        blob = BlobInfo(center_x=10, center_y=20, area=300, bbox=(5, 15, 10, 10))
        assert blob.center_x == 10
        assert blob.center_y == 20
        assert blob.area == 300
        assert blob.bbox == (5, 15, 10, 10)


class TestSpreadMetrics:
    """Test the SpreadMetrics dataclass."""

    def test_construction(self):
        from tests.lib.ui_analyzer import SpreadMetrics
        sm = SpreadMetrics(
            span_x=100, span_y=200,
            centroid=(50, 100),
            bounding_box=(0, 0, 100, 200),
            std_dev=42.5,
        )
        assert sm.span_x == 100
        assert sm.span_y == 200
        assert sm.centroid == (50, 100)
        assert sm.std_dev == 42.5


class TestAnalysisResult:
    """Test the AnalysisResult dataclass."""

    def test_construction(self):
        from tests.lib.ui_analyzer import AnalysisResult
        result = AnalysisResult(
            image_path="/tmp/test.png",
            opencv_metrics={"content_pct": 45.0},
            annotations=[],
            cherry_picked=False,
            vision_advisory=None,
            passed_checks={"check1": True, "check2": False},
            timestamp=time.time(),
        )
        assert result.image_path == "/tmp/test.png"
        assert result.passed_checks["check1"] is True
        assert result.passed_checks["check2"] is False
