from __future__ import annotations
import cv2
from .models import CircleDetection, ELLIPSE_VERTICAL_RADIUS_SCALE

def annotate_frame(frame, circles: list[CircleDetection], center_threshold_px: int):
    annotated = frame.copy()
    if annotated.ndim == 2:
        annotated = cv2.cvtColor(annotated, cv2.COLOR_GRAY2BGR)
    height, width = annotated.shape[:2]
    center_x = width // 2
    center_y = height // 2
    ellipse_radius_x = max(1, int(center_threshold_px))
    ellipse_radius_y = max(1, int(round(center_threshold_px * ELLIPSE_VERTICAL_RADIUS_SCALE)))

    cv2.line(annotated, (center_x - 20, center_y), (center_x + 20, center_y), (0, 255, 255), 2)
    cv2.line(annotated, (center_x, center_y - 20), (center_x, center_y + 20), (0, 255, 255), 2)
    cv2.ellipse(annotated, (center_x, center_y), (ellipse_radius_x, ellipse_radius_y), 0, 0, 360, (255, 255, 0), 1)

    for index, circle in enumerate(circles):
        color = (0, 255, 0) if index == 0 else (255, 128, 0)
        diameter = int(circle.radius * 2)
        cv2.circle(annotated, (circle.x, circle.y), circle.radius, color, 2)
        cv2.circle(annotated, (circle.x, circle.y), 4, (0, 0, 255), -1)
        cv2.putText(
            annotated,
            f"#{index + 1} d={circle.distance_to_center:.1f} D={diameter} e={circle.edge_support:.2f} a={circle.angular_coverage:.2f}",
            (circle.x + 8, max(24, circle.y - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            2,
        )
    return annotated

