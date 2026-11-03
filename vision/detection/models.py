from __future__ import annotations
from dataclasses import dataclass

ELLIPSE_VERTICAL_RADIUS_SCALE = 2.0

@dataclass
class CircleDetection:
    x: int
    y: int
    radius: int
    distance_to_center: float
    circularity: float
    edge_support: float
    fill_ratio: float
    radial_error_ratio: float
    angular_coverage: float
    diameter_ratio: float
    score: float
    source: str

