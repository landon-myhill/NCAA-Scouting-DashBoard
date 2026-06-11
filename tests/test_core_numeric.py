"""Tests for core.numeric parsing helpers."""
import pytest

from core.numeric import flt, pct, safe_stat, height_inches


@pytest.mark.parametrize("val,expected", [
    ("12.5", 12.5), (12.5, 12.5), (None, None), ("", None),
    ("—", None), ("-", None), ("N/A", None), (".", None), ("  7 ", 7.0),
])
def test_flt(val, expected):
    assert flt(val) == expected


def test_flt_default():
    assert flt("garbage", default=0) == 0
    assert flt(None, default=-1) == -1


@pytest.mark.parametrize("val,expected", [
    (0.452, 45.2), (45.2, 45.2), (1.0, 100.0), (0, 0.0), (None, None),
])
def test_pct(val, expected):
    assert pct(val) == expected


def test_safe_stat():
    s = {"PPG": 12.0, "RPG": None}
    assert safe_stat(s, "PPG") == 12.0
    assert safe_stat(s, "RPG") == 0          # None -> default
    assert safe_stat(s, "MISSING") == 0
    assert safe_stat(s, "MISSING", default=5) == 5
    assert safe_stat(None, "X") == 0


@pytest.mark.parametrize("h,inches", [
    ("6'9\"", 81), ("6-9", 81), ("7'0\"", 84), ("5'11\"", 71),
    ("", 0), (None, 0), ("garbage", 0),
])
def test_height_inches(h, inches):
    assert height_inches(h) == inches
