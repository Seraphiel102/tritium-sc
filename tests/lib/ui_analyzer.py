# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Generalized UI analysis framework — OpenCV-only, no vision model required.

Provides deterministic image analysis tools for visual test verification.
Uses the same OpenCV techniques as visual_assert.py and test_battle_proof.py
but in a standalone, reusable form.

Design principles:
  - OpenCV is primary. Every method works without model access.
  - LLM (via fleet) is advisory-only in the check() method.
  - All color inputs are BGR tuples (OpenCV native format).
  - Works with synthetic images for unit testing (no browser needed).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


@dataclass
class BlobInfo:
    """A single detected color blob."""
    center_x: int
    center_y: int
    area: int
    bbox: tuple[int, int, int, int]  # x, y, w, h


@dataclass
class SpreadMetrics:
    """Spatial distribution metrics for a set of blobs."""
    span_x: int
    span_y: int
    centroid: tuple[int, int]
    bounding_box: tuple[int, int, int, int]  # x, y, w, h
    std_dev: float


@dataclass
class AnalysisResult:
    """Result of a composite check() call."""
    image_path: str
    opencv_metrics: dict
    annotations: list[dict]
    cherry_picked: bool
    vision_advisory: str | None
    passed_checks: dict[str, bool]
    timestamp: float


class UIAnalyzer:
    """Orchestrates UI analysis checks using OpenCV.

    Instantiate without arguments for pure OpenCV analysis. Optionally
    pass a fleet (OllamaFleet) for advisory LLM queries in check().
    """

    def __init__(self, fleet=None, vision_model: str = "llava:7b"):
        self.fleet = fleet
        self.vision_model = vision_model

    def detect_blobs(
        self,
        img: np.ndarray,
        bgr: tuple[int, int, int],
        tolerance: int = 40,
        min_area: int = 20,
    ) -> list[BlobInfo]:
        """Detect contiguous blobs of a specific BGR color.

        Uses cv2.inRange to create a binary mask, then cv2.findContours
        to identify distinct regions. Filters by minimum contour area.

        Args:
            img: BGR image (numpy array).
            bgr: Target color in BGR format.
            tolerance: Per-channel tolerance for color matching.
            min_area: Minimum contour area in pixels to keep.

        Returns:
            List of BlobInfo with center, area, and bounding box.
        """
        lower = np.array(
            [max(0, c - tolerance) for c in bgr], dtype=np.uint8
        )
        upper = np.array(
            [min(255, c + tolerance) for c in bgr], dtype=np.uint8
        )
        mask = cv2.inRange(img, lower, upper)
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        blobs: list[BlobInfo] = []
        for c in contours:
            area = int(cv2.contourArea(c))
            if area < min_area:
                continue
            M = cv2.moments(c)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
            else:
                x, y, w, h = cv2.boundingRect(c)
                cx = x + w // 2
                cy = y + h // 2
            x, y, w, h = cv2.boundingRect(c)
            blobs.append(BlobInfo(center_x=cx, center_y=cy, area=area, bbox=(x, y, w, h)))

        return blobs

    def measure_spread(self, blobs: list[BlobInfo]) -> SpreadMetrics:
        """Compute spatial distribution metrics for a set of blobs.

        Args:
            blobs: List of BlobInfo instances.

        Returns:
            SpreadMetrics with span, centroid, bounding box, and std deviation.
        """
        if not blobs:
            return SpreadMetrics(
                span_x=0,
                span_y=0,
                centroid=(0, 0),
                bounding_box=(0, 0, 0, 0),
                std_dev=0.0,
            )

        xs = [b.center_x for b in blobs]
        ys = [b.center_y for b in blobs]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max_x - min_x
        span_y = max_y - min_y

        centroid_x = sum(xs) // len(xs)
        centroid_y = sum(ys) // len(ys)

        # Standard deviation of blob positions (combined x and y)
        if len(blobs) == 1:
            std_dev = 0.0
        else:
            # Use population std dev of all coordinate values
            coords = []
            for b in blobs:
                coords.append(float(b.center_x))
                coords.append(float(b.center_y))
            mean_coord = sum(coords) / len(coords)
            variance = sum((c - mean_coord) ** 2 for c in coords) / len(coords)
            std_dev = math.sqrt(variance)

        return SpreadMetrics(
            span_x=span_x,
            span_y=span_y,
            centroid=(centroid_x, centroid_y),
            bounding_box=(min_x, min_y, span_x, span_y),
            std_dev=std_dev,
        )

    def content_percentage(
        self,
        img: np.ndarray,
        region: tuple[int, int, int, int] | None = None,
        threshold: int = 15,
    ) -> float:
        """Calculate percentage of non-black pixels.

        Args:
            img: BGR image.
            region: Optional (x, y, w, h) to limit measurement area.
            threshold: Grayscale value below which a pixel counts as black.

        Returns:
            Percentage of content pixels (0.0 to 100.0).
        """
        if region is not None:
            x, y, w, h = region
            roi = img[y:y + h, x:x + w]
        else:
            roi = img

        if roi.size == 0:
            return 0.0

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        content_pixels = int(np.count_nonzero(gray > threshold))
        total_pixels = gray.size
        return round(content_pixels / total_pixels * 100.0, 1)

    def count_elements(
        self,
        img: np.ndarray,
        bgr: tuple[int, int, int],
        tolerance: int = 40,
        min_area: int = 20,
    ) -> int:
        """Count distinct blobs of a specific color.

        Convenience wrapper around detect_blobs that returns just the count.
        """
        return len(self.detect_blobs(img, bgr, tolerance=tolerance, min_area=min_area))

    def region_has_content(
        self,
        img: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
        threshold: int = 10,
    ) -> bool:
        """Check if a rectangular region has non-trivial content.

        Args:
            img: BGR image.
            x, y, w, h: Region coordinates.
            threshold: Grayscale mean above which region counts as non-blank.

        Returns:
            True if the region mean grayscale exceeds threshold.
        """
        region = img[y:y + h, x:x + w]
        if region.size == 0:
            return False
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) > threshold

    def region_has_text(
        self,
        img: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> bool:
        """Check if a region has text-like content via edge density.

        Uses Canny edge detection. Text regions typically have >3% edge
        density due to the high-frequency character outlines.

        Args:
            img: BGR image.
            x, y, w, h: Region coordinates.

        Returns:
            True if edge density exceeds 3%.
        """
        region = img[y:y + h, x:x + w]
        if region.size == 0:
            return False
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = cv2.countNonZero(edges) / edges.size
        return edge_density > 0.03

    def annotate(
        self,
        img: np.ndarray,
        blobs: list[BlobInfo],
        label_fn: Callable[[BlobInfo], str] | None = None,
    ) -> np.ndarray:
        """Draw bounding boxes (and optional labels) on a copy of the image.

        Args:
            img: BGR image.
            blobs: List of BlobInfo to annotate.
            label_fn: Optional callable that takes a BlobInfo and returns
                a string label to draw above the bounding box.

        Returns:
            Annotated copy of the image (original is not mutated).
        """
        annotated = img.copy()
        for blob in blobs:
            x, y, w, h = blob.bbox
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 255), 2)
            if label_fn is not None:
                label = label_fn(blob)
                cv2.putText(
                    annotated,
                    label,
                    (x, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 255),
                    1,
                )
        return annotated

    def check(
        self,
        name: str,
        img: np.ndarray,
        img_path: str,
        assertions: dict[str, Callable[[], bool]],
        cherry_pick: str | None = None,
        vision_prompt: str | None = None,
    ) -> AnalysisResult:
        """Run a composite analysis check.

        Executes all assertion callables, collects basic OpenCV metrics,
        and optionally queries an LLM fleet for advisory feedback.

        Args:
            name: Human-readable check name.
            img: BGR image to analyze.
            img_path: Path to the screenshot file (for reporting).
            assertions: Dict of {check_name: callable} where each callable
                returns True/False.
            cherry_pick: If set, marks this result as cherry-picked (string
                identifies the selection reason).
            vision_prompt: If set and fleet is available, query the LLM for
                an advisory description.

        Returns:
            AnalysisResult with metrics, passed checks, and optional advisory.
        """
        timestamp = time.time()

        # Run all assertions
        passed_checks: dict[str, bool] = {}
        for check_name, check_fn in assertions.items():
            try:
                passed_checks[check_name] = bool(check_fn())
            except Exception:
                passed_checks[check_name] = False

        # Collect basic OpenCV metrics
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        content_pct = round(
            int(np.count_nonzero(gray > 15)) / gray.size * 100.0, 1
        )
        opencv_metrics = {
            "image_shape": (h, w),
            "content_pct": content_pct,
            "mean_brightness": round(float(gray.mean()), 1),
        }

        # Optional LLM advisory
        vision_advisory: str | None = None
        if vision_prompt and self.fleet is not None:
            try:
                resp = self.fleet.generate(
                    self.vision_model,
                    vision_prompt,
                    image_path=Path(img_path) if img_path else None,
                )
                vision_advisory = resp.get("response")
            except Exception:
                vision_advisory = None

        return AnalysisResult(
            image_path=img_path,
            opencv_metrics=opencv_metrics,
            annotations=[],
            cherry_picked=cherry_pick is not None,
            vision_advisory=vision_advisory,
            passed_checks=passed_checks,
            timestamp=timestamp,
        )
