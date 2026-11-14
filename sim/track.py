"""Closed stadium/oval track geometry and pure-pursuit helpers (contract 6).

The track is a stadium shape (two straights joined by two semicircles),
represented as a dense polyline of centerline points in a local planar (x, y)
metric frame (meters). The start/finish line is at the polyline origin
(index 0), crossed when the car passes it travelling forward along the loop.
"""

import math
from typing import List, Tuple

# Stadium dimensions (meters). RC-scale oval sized so an autopilot lap at the
# simulator's top speed completes in well under 10 s (keeps the smoke run fast).
STRAIGHT_LEN = 8.0
RADIUS = 3.0


def build_centerline(points_per_segment: int = 200) -> List[Tuple[float, float]]:
    """Build a closed stadium centerline as an ordered list of (x, y) points.

    Layout (counter-clockwise):
      - bottom straight: left -> right
      - right semicircle: bottom -> top
      - top straight: right -> left
      - left semicircle: top -> bottom
    Start/finish is the first point of the bottom straight.
    """
    pts: List[Tuple[float, float]] = []
    half = STRAIGHT_LEN / 2.0

    # Bottom straight, y = -RADIUS, x from -half to +half.
    for i in range(points_per_segment):
        f = i / points_per_segment
        pts.append((-half + f * STRAIGHT_LEN, -RADIUS))

    # Right semicircle, centered (half, 0), angle -pi/2 -> +pi/2.
    for i in range(points_per_segment):
        f = i / points_per_segment
        ang = -math.pi / 2 + f * math.pi
        pts.append((half + RADIUS * math.cos(ang), RADIUS * math.sin(ang)))

    # Top straight, y = +RADIUS, x from +half to -half.
    for i in range(points_per_segment):
        f = i / points_per_segment
        pts.append((half - f * STRAIGHT_LEN, RADIUS))

    # Left semicircle, centered (-half, 0), angle +pi/2 -> +3pi/2.
    for i in range(points_per_segment):
        f = i / points_per_segment
        ang = math.pi / 2 + f * math.pi
        pts.append((-half + RADIUS * math.cos(ang), RADIUS * math.sin(ang)))

    return pts


def track_length(centerline: List[Tuple[float, float]]) -> float:
    total = 0.0
    n = len(centerline)
    for i in range(n):
        x0, y0 = centerline[i]
        x1, y1 = centerline[(i + 1) % n]
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def nearest_index(centerline: List[Tuple[float, float]], x: float, y: float) -> int:
    best_i = 0
    best_d = float("inf")
    for i, (px, py) in enumerate(centerline):
        d = (px - x) ** 2 + (py - y) ** 2
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def lookahead_point(
    centerline: List[Tuple[float, float]],
    near_i: int,
    lookahead_pts: int,
) -> Tuple[float, float]:
    n = len(centerline)
    return centerline[(near_i + lookahead_pts) % n]
