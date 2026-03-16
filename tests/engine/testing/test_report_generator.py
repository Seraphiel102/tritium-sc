# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TestReportGenerator — density, trend, HTML, persistence."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from engine.testing.report_generator import TestReportGenerator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_reports(tmp_path):
    """Return a TestReportGenerator that writes to a temp directory."""
    return TestReportGenerator(reports_dir=tmp_path)


@pytest.fixture
def sample_src(tmp_path):
    """Create a fake source tree for density testing."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha.py").write_text("# alpha")
    (src / "beta.py").write_text("# beta")
    (src / "gamma.py").write_text("# gamma")
    (src / "__init__.py").write_text("")
    # Nested module
    sub = src / "sub"
    sub.mkdir()
    (sub / "delta.py").write_text("# delta")
    (sub / "__init__.py").write_text("")
    return src


@pytest.fixture
def sample_tests(tmp_path):
    """Create a fake test tree that covers alpha and beta but not gamma/delta."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_alpha.py").write_text("def test_a(): pass")
    (tests / "test_beta.py").write_text("def test_b(): pass")
    (tests / "__init__.py").write_text("")
    return tests


# ---------------------------------------------------------------------------
# Tests — density and untested modules
# ---------------------------------------------------------------------------

class TestDensity:
    """Verify test density calculation and untested module detection."""

    def test_density_ratio(self, tmp_reports, sample_src, sample_tests):
        result = tmp_reports._compute_density(sample_src, sample_tests)
        # 5 source .py files (alpha, beta, gamma, sub/delta, sub/__init__, __init__)
        # but __init__ files start with _ so they're excluded from untested
        assert result["test_files"] == 3  # test_alpha, test_beta, __init__
        assert result["source_files"] > 0
        assert isinstance(result["density"], float)

    def test_untested_detected(self, tmp_reports, sample_src, sample_tests):
        result = tmp_reports._compute_density(sample_src, sample_tests)
        untested = result["untested_modules"]
        # gamma and delta should be untested (alpha and beta have test_ counterparts)
        untested_names = [Path(u).stem for u in untested]
        assert "gamma" in untested_names
        assert "delta" in untested_names
        assert "alpha" not in untested_names
        assert "beta" not in untested_names

    def test_missing_dirs(self, tmp_reports, tmp_path):
        result = tmp_reports._compute_density(
            tmp_path / "nonexistent_src", tmp_path / "nonexistent_tests"
        )
        assert result["source_files"] == 0
        assert result["density"] == 0
        assert result["untested_modules"] == []


# ---------------------------------------------------------------------------
# Tests — stdout fallback parser
# ---------------------------------------------------------------------------

class TestStdoutParser:
    """Verify fallback stdout parsing when json-report is unavailable."""

    def test_parse_summary_line(self, tmp_reports):
        stdout = "========= 42 passed, 3 failed, 7 skipped in 12.34s ========="
        result = tmp_reports._parse_stdout(stdout, 1, "test")
        assert result["passed"] == 42
        assert result["failed"] == 3
        assert result["skipped"] == 7
        assert result["total"] == 52  # 42 + 3 + 7

    def test_parse_all_passed(self, tmp_reports):
        stdout = "100 passed in 5.00s"
        result = tmp_reports._parse_stdout(stdout, 0, "test")
        assert result["passed"] == 100
        assert result["failed"] == 0
        assert result["total"] == 100

    def test_parse_empty(self, tmp_reports):
        result = tmp_reports._parse_stdout("", 0, "test")
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Tests — JSON report parser
# ---------------------------------------------------------------------------

class TestJsonReportParser:
    """Verify parsing of pytest-json-report output."""

    def test_parse_basic(self, tmp_reports):
        raw = {
            "summary": {"total": 10, "passed": 8, "failed": 1, "skipped": 1},
            "duration": 3.5,
            "tests": [
                {"nodeid": "tests/test_a.py::test_one", "outcome": "passed"},
                {"nodeid": "tests/test_a.py::test_two", "outcome": "failed"},
                {"nodeid": "tests/test_b.py::test_three", "outcome": "passed"},
            ],
        }
        result = tmp_reports._parse_json_report(raw, "test")
        assert result["total"] == 10
        assert result["passed"] == 8
        assert result["failed"] == 1
        assert result["duration_s"] == 3.5
        assert "tests/test_a.py" in result["by_module"]
        assert result["by_module"]["tests/test_a.py"]["passed"] == 1
        assert result["by_module"]["tests/test_a.py"]["failed"] == 1


# ---------------------------------------------------------------------------
# Tests — trend computation
# ---------------------------------------------------------------------------

class TestTrend:
    """Verify trend delta computation between reports."""

    def test_trend_deltas(self, tmp_reports):
        current = {"totals": {"total": 50, "passed": 45, "failed": 5, "duration_s": 10.0}}
        previous = {"totals": {"total": 40, "passed": 38, "failed": 2, "duration_s": 8.0}, "timestamp": "old"}
        trend = tmp_reports._compute_trend(current, previous)
        assert trend["total_delta"] == 10
        assert trend["passed_delta"] == 7
        assert trend["failed_delta"] == 3
        assert trend["duration_delta"] == 2.0
        assert trend["previous_timestamp"] == "old"


# ---------------------------------------------------------------------------
# Tests — persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    """Verify report save/load cycle."""

    def test_save_and_load(self, tmp_reports):
        report = {
            "timestamp": "2026-03-13T00:00:00+00:00",
            "duration_s": 5.0,
            "totals": {"total": 10, "passed": 10, "failed": 0},
            "projects": {},
        }
        path = tmp_reports._save_report(report)
        assert path.exists()

        loaded = tmp_reports._load_previous()
        assert loaded is not None
        assert loaded["totals"]["total"] == 10

    def test_latest_returns_none_empty(self, tmp_path):
        gen = TestReportGenerator(reports_dir=tmp_path / "empty_reports")
        assert gen.latest() is None


# ---------------------------------------------------------------------------
# Tests — HTML generation
# ---------------------------------------------------------------------------

class TestHtmlReport:
    """Verify HTML report generation."""

    def test_html_contains_key_elements(self, tmp_reports):
        report = {
            "timestamp": "2026-03-13T00:00:00+00:00",
            "duration_s": 5.0,
            "totals": {"total": 100, "passed": 95, "failed": 5, "skipped": 0},
            "trend": {"total_delta": 10, "passed_delta": 8, "failed_delta": 2, "duration_delta": 1.0},
            "projects": {
                "tritium-sc": {
                    "total": 80, "passed": 77, "failed": 3, "skipped": 0,
                    "duration_s": 4.0, "density": 0.85,
                    "untested_modules": ["app/foo.py"],
                    "by_module": {},
                },
                "tritium-lib": {
                    "total": 20, "passed": 18, "failed": 2, "skipped": 0,
                    "duration_s": 1.0, "density": 0.60,
                    "untested_modules": [],
                    "by_module": {},
                },
            },
        }
        html = tmp_reports.generate_html(report)
        assert "TRITIUM TEST REPORT" in html
        assert "100" in html  # total
        assert "95" in html   # passed
        assert "tritium-sc" in html
        assert "tritium-lib" in html
        assert "#0a0a0f" in html  # cyberpunk background
        assert "#00f0ff" in html  # cyan


# ---------------------------------------------------------------------------
# Tests — merge totals
# ---------------------------------------------------------------------------

class TestMergeTotals:
    """Verify merging of multiple project results."""

    def test_merge_two(self, tmp_reports):
        a = {"total": 10, "passed": 8, "failed": 1, "skipped": 1, "error": 0, "duration_s": 3.0}
        b = {"total": 5, "passed": 5, "failed": 0, "skipped": 0, "error": 0, "duration_s": 1.0}
        result = tmp_reports._merge_totals(a, b)
        assert result["total"] == 15
        assert result["passed"] == 13
        assert result["failed"] == 1
        assert result["duration_s"] == 4.0


# ---------------------------------------------------------------------------
# Tests — empty results
# ---------------------------------------------------------------------------

class TestEmptyResults:
    """Verify empty result generation."""

    def test_empty_default(self, tmp_reports):
        r = tmp_reports._empty_results("x")
        assert r["total"] == 0
        assert "run_error" not in r

    def test_empty_with_error(self, tmp_reports):
        r = tmp_reports._empty_results("x", error="timeout")
        assert r["run_error"] == "timeout"
