"""Track geometry: the server's default must be the simulator's track."""

import json
import math

import pytest

from server.app import track as server_track
from server.app.track import Track, default_track, load_track
from sim import car as sim_car
from sim import track as sim_track


def test_default_track_matches_the_simulator():
    """Lap timing is only right if both sides agree where the track is."""
    ours = default_track()
    theirs = sim_track.build_centerline()
    assert len(ours.centerline) == len(theirs)
    for (ax, ay), (bx, by) in zip(ours.centerline, theirs):
        assert ax == pytest.approx(bx, abs=1e-9)
        assert ay == pytest.approx(by, abs=1e-9)
    assert ours.length_m == pytest.approx(sim_track.track_length(theirs), abs=1e-6)
    assert (ours.anchor_lat, ours.anchor_lon) == (sim_car.ANCHOR_LAT, sim_car.ANCHOR_LON)


def test_gps_projection_matches_the_simulator_and_round_trips():
    track = default_track()
    lat, lon = sim_car.local_to_gps(3.2, -1.7)
    x, y = track.to_local(lat, lon)
    assert (x, y) == pytest.approx((3.2, -1.7), abs=1e-6)
    assert track.to_gps(x, y) == pytest.approx((lat, lon), abs=1e-9)


def test_length_is_two_straights_and_a_circle():
    track = default_track()
    expected = 2 * server_track.STRAIGHT_LEN + 2 * math.pi * server_track.RADIUS
    assert track.length_m == pytest.approx(expected, rel=1e-4)


def test_locate_gives_distance_along_and_from_the_centreline():
    track = default_track()
    # 2 m down the bottom straight, 0.3 m to the outside.
    s, dist, _ = track.locate(-2.0, -3.3)
    assert s == pytest.approx(2.0, abs=1e-6)
    assert dist == pytest.approx(0.3, abs=1e-6)
    assert not track.is_off_track(dist)
    # Middle of the infield: far from the surface.
    _, dist, _ = track.locate(0.0, 0.0)
    assert dist == pytest.approx(3.0, abs=1e-3)
    assert track.is_off_track(dist)


def test_locate_with_a_hint_agrees_with_a_full_search():
    track = default_track()
    hint = None
    for i in range(0, 400):
        x, y = track.point_at(i * 0.09)
        s_hint, d_hint, hint = track.locate(x + 0.1, y - 0.1, hint)
        s_full, d_full, _ = track.locate(x + 0.1, y - 0.1)
        assert s_hint == pytest.approx(s_full, abs=1e-9)
        assert d_hint == pytest.approx(d_full, abs=1e-9)


def test_stale_hint_falls_back_to_a_full_search():
    track = default_track()
    _, _, hint = track.locate(-4.0, -3.0)          # start line
    s, dist, _ = track.locate(4.0, 3.0, hint)      # far side of the track
    assert dist == pytest.approx(0.0, abs=1e-6)
    assert s == pytest.approx(track.length_m / 2, abs=0.05)


def test_load_track_from_json(tmp_path):
    spec = {
        "name": "Lab square",
        "anchor": {"lat": 41.0, "lon": 29.0},
        "width_m": 1.2,
        "centerline": [[0, 0], [10, 0], [10, 10], [0, 10]],
    }
    path = tmp_path / "track.json"
    path.write_text(json.dumps(spec))
    track = load_track(str(path))
    assert track.name == "Lab square"
    assert track.length_m == pytest.approx(40.0)
    assert track.point_at(15.0) == pytest.approx((10.0, 5.0))
    out = track.to_dict()
    assert out["anchor"] == {"lat": 41.0, "lon": 29.0}
    assert out["centerline"][2] == [10.0, 10.0]


def test_load_track_defaults_without_a_file(monkeypatch):
    monkeypatch.delenv("F163_TRACK", raising=False)
    assert load_track().name == default_track().name


def test_track_rejects_nonsense():
    with pytest.raises(ValueError):
        Track("x", 0, 0, 1.0, [(0, 0), (1, 0)])
    with pytest.raises(ValueError):
        Track("x", 0, 0, 0.0, [(0, 0), (1, 0), (1, 1)])
    with pytest.raises(ValueError):
        Track("x", 0, 0, 1.0, [(0, 0), (0, 0), (1, 1)])
