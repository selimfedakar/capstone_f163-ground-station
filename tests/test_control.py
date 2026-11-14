"""Unit tests for control value clamping (contract 3)."""

from server.app.state import clamp_unit


def test_clamp_within_range():
    assert clamp_unit(0.5) == 0.5
    assert clamp_unit(-0.5) == -0.5
    assert clamp_unit(0.0) == 0.0
    assert clamp_unit(1.0) == 1.0
    assert clamp_unit(-1.0) == -1.0


def test_clamp_above_range():
    assert clamp_unit(1.5) == 1.0
    assert clamp_unit(100.0) == 1.0


def test_clamp_below_range():
    assert clamp_unit(-1.5) == -1.0
    assert clamp_unit(-42.0) == -1.0


def test_clamp_invalid_defaults_to_zero():
    assert clamp_unit(None) == 0.0
    assert clamp_unit("nope") == 0.0
    assert clamp_unit(float("nan")) == 0.0


def test_clamp_string_number():
    assert clamp_unit("0.3") == 0.3
    assert clamp_unit("2.0") == 1.0
