"""Track definition used by the server for lap timing, track limits and the map.

A track is a closed centreline in local metres, ordered in the driving
direction with point 0 on the start/finish line, plus the GPS anchor that maps
reported lat/lon onto it. Everything that needs to know where the track is
(lap detection, off-track time, the UI map via ``GET /api/track``) reads this
one object.

The default is the simulator's stadium. To run on a real track, describe it in
a JSON file and point ``F163_TRACK`` at it (see ``load_track``).
"""

import bisect
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

M_PER_DEG_LAT = 111_320.0

# Default stadium. Must match sim/track.py and sim/car.py; tests/test_track.py
# fails if the two drift apart.
STRAIGHT_LEN = 8.0
RADIUS = 3.0
ANCHOR_LAT = 41.0421
ANCHOR_LON = 29.0093
# The simulator has no walls; this is the racing-surface width used for track
# limits until Mechatronics confirms the real one.
DEFAULT_WIDTH_M = 1.6

# How far either side of the last known segment to look before falling back to
# a search of the whole centreline.
_LOCAL_WINDOW = 40
_LOCAL_ACCEPT_M = 2.0


@dataclass
class Track:
    name: str
    anchor_lat: float
    anchor_lon: float
    width_m: float
    centerline: List[Tuple[float, float]]
    length_m: float = field(init=False)

    def __post_init__(self) -> None:
        if len(self.centerline) < 3:
            raise ValueError("a track needs at least 3 centreline points")
        if self.width_m <= 0:
            raise ValueError("track width must be positive")
        n = len(self.centerline)
        self._n = n
        self._seg: List[Tuple[float, float, float, float, float, float]] = []
        self._cum: List[float] = []
        total = 0.0
        for i in range(n):
            ax, ay = self.centerline[i]
            bx, by = self.centerline[(i + 1) % n]
            dx, dy = bx - ax, by - ay
            len2 = dx * dx + dy * dy
            if len2 <= 0:
                raise ValueError(f"centreline points {i} and {(i + 1) % n} coincide")
            self._cum.append(total)
            self._seg.append((ax, ay, dx, dy, len2, math.sqrt(len2)))
            total += math.sqrt(len2)
        self.length_m = total
        self._m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(self.anchor_lat))

    # ---- projection ---------------------------------------------------
    def to_local(self, lat: float, lon: float) -> Tuple[float, float]:
        """Project lat/lon to local planar metres (x east, y north)."""
        return (
            (lon - self.anchor_lon) * self._m_per_deg_lon,
            (lat - self.anchor_lat) * M_PER_DEG_LAT,
        )

    def to_gps(self, x: float, y: float) -> Tuple[float, float]:
        """Inverse of ``to_local``: local metres to (lat, lon)."""
        return (
            self.anchor_lat + y / M_PER_DEG_LAT,
            self.anchor_lon + x / self._m_per_deg_lon,
        )

    def point_at(self, s: float) -> Tuple[float, float]:
        """The centreline point ``s`` metres after the start/finish line."""
        s %= self.length_m
        i = bisect.bisect_right(self._cum, s) - 1
        ax, ay, dx, dy, _len2, seglen = self._seg[i]
        u = (s - self._cum[i]) / seglen
        return ax + u * dx, ay + u * dy

    # ---- position along the lap ----------------------------------------
    def _best(self, x: float, y: float, indices) -> Tuple[float, float, int]:
        best_d2 = float("inf")
        best_s = 0.0
        best_i = 0
        for i in indices:
            ax, ay, dx, dy, len2, seglen = self._seg[i]
            u = ((x - ax) * dx + (y - ay) * dy) / len2
            if u < 0.0:
                u = 0.0
            elif u > 1.0:
                u = 1.0
            ex = x - (ax + u * dx)
            ey = y - (ay + u * dy)
            d2 = ex * ex + ey * ey
            if d2 < best_d2:
                best_d2 = d2
                best_s = self._cum[i] + u * seglen
                best_i = i
        return best_s, math.sqrt(best_d2), best_i

    def locate(self, x: float, y: float, hint: Optional[int] = None) -> Tuple[float, float, int]:
        """Nearest point on the centreline.

        Returns ``(s, distance, segment)``: ``s`` is metres from the
        start/finish line along the driving direction, ``distance`` is how far
        the point is from the centreline. ``hint`` is the segment returned for
        the previous sample; passing it keeps the search local and cheap.
        """
        if hint is not None:
            n = self._n
            local = [(hint + k) % n for k in range(-_LOCAL_WINDOW, _LOCAL_WINDOW + 1)]
            s, d, i = self._best(x, y, local)
            if d <= _LOCAL_ACCEPT_M:
                return s, d, i
        return self._best(x, y, range(self._n))

    def is_off_track(self, distance: float) -> bool:
        return distance > self.width_m / 2.0

    # ---- serialisation ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "anchor": {"lat": self.anchor_lat, "lon": self.anchor_lon},
            "width_m": self.width_m,
            "length_m": round(self.length_m, 3),
            "centerline": [[round(x, 3), round(y, 3)] for x, y in self.centerline],
        }


def stadium_centerline(points_per_segment: int = 200) -> List[Tuple[float, float]]:
    """Closed stadium, counter-clockwise, starting on the bottom straight."""
    pts: List[Tuple[float, float]] = []
    half = STRAIGHT_LEN / 2.0
    for i in range(points_per_segment):
        f = i / points_per_segment
        pts.append((-half + f * STRAIGHT_LEN, -RADIUS))
    for i in range(points_per_segment):
        ang = -math.pi / 2 + (i / points_per_segment) * math.pi
        pts.append((half + RADIUS * math.cos(ang), RADIUS * math.sin(ang)))
    for i in range(points_per_segment):
        f = i / points_per_segment
        pts.append((half - f * STRAIGHT_LEN, RADIUS))
    for i in range(points_per_segment):
        ang = math.pi / 2 + (i / points_per_segment) * math.pi
        pts.append((-half + RADIUS * math.cos(ang), RADIUS * math.sin(ang)))
    return pts


def default_track() -> Track:
    return Track(
        name="Simulator stadium",
        anchor_lat=ANCHOR_LAT,
        anchor_lon=ANCHOR_LON,
        width_m=DEFAULT_WIDTH_M,
        centerline=stadium_centerline(),
    )


def load_track(path: Optional[str] = None) -> Track:
    """Load the track from a JSON file, or return the default stadium.

    File shape (the same shape ``GET /api/track`` returns)::

        {"name": "BAU lab track",
         "anchor": {"lat": 41.0421, "lon": 29.0093},
         "width_m": 1.2,
         "centerline": [[x, y], ...]}   # metres, driving order, point 0 on the line
    """
    path = path or os.environ.get("F163_TRACK")
    if not path:
        return default_track()
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return Track(
        name=str(raw.get("name", os.path.basename(path))),
        anchor_lat=float(raw["anchor"]["lat"]),
        anchor_lon=float(raw["anchor"]["lon"]),
        width_m=float(raw["width_m"]),
        centerline=[(float(p[0]), float(p[1])) for p in raw["centerline"]],
    )
