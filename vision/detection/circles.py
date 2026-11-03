from __future__ import annotations

from .annotation import annotate_frame as annotate_frame

from .models import CircleDetection

from .enhancement import EnhancementConfig, FrameEnhancer

from math import hypot

import cv2
import numpy as np


def _clamp_roi(x: int, y: int, radius: int, width: int, height: int, scale: float = 1.5) -> tuple[int, int, int, int]:
    pad = max(int(radius * scale), 12)
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(width, x + pad)
    y2 = min(height, y + pad)
    return x1, y1, x2, y2


def _estimate_circularity(gray: np.ndarray, x: int, y: int, radius: int) -> float:
    height, width = gray.shape[:2]
    x1, y1, x2, y2 = _clamp_roi(x, y, radius, width, height)
    roi = gray[y1:y2, x1:x2]
    if roi.size == 0:
        return 0.0

    roi_blurred = cv2.GaussianBlur(roi, (5, 5), 0)
    _, thresh = cv2.threshold(roi_blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        _, thresh = cv2.threshold(roi_blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return 0.0

    local_x = x - x1
    local_y = y - y1
    best = 0.0
    min_area = max(np.pi * (radius * 0.45) ** 2, 20.0)
    max_area = np.pi * (radius * 1.8) ** 2

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        if cv2.pointPolygonTest(contour, (float(local_x), float(local_y)), False) < 0:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        circularity = float((4.0 * np.pi * area) / (perimeter * perimeter))
        if circularity > best:
            best = circularity

    return best


def _estimate_edge_profile(edges: np.ndarray, x: int, y: int, radius: int) -> tuple[float, float, float]:
    height, width = edges.shape[:2]
    if radius <= 0:
        return 0.0, 0.0, 1.0

    band = max(2, radius // 14)
    hit_count = 0
    sample_count = 96
    sector_count = 24
    sector_hits = np.zeros(sector_count, dtype=np.uint8)

    for sample_index, theta in enumerate(np.linspace(0, 2.0 * np.pi, sample_count, endpoint=False)):
        px = int(round(x + radius * np.cos(theta)))
        py = int(round(y + radius * np.sin(theta)))
        if px < 0 or py < 0 or px >= width or py >= height:
            continue

        x1 = max(0, px - band)
        y1 = max(0, py - band)
        x2 = min(width, px + band + 1)
        y2 = min(height, py + band + 1)
        if np.any(edges[y1:y2, x1:x2] > 0):
            hit_count += 1
            sector_index = min(sector_count - 1, (sample_index * sector_count) // sample_count)
            sector_hits[sector_index] = 1

    support = float(hit_count / sample_count)
    coverage = float(np.count_nonzero(sector_hits) / sector_count)

    longest_gap = 0
    current_gap = 0
    doubled_hits = np.concatenate((sector_hits, sector_hits))
    for hit in doubled_hits:
        if hit:
            longest_gap = max(longest_gap, current_gap)
            current_gap = 0
        else:
            current_gap += 1
    longest_gap = min(sector_count, max(longest_gap, current_gap))
    max_gap_ratio = float(longest_gap / sector_count)
    return support, coverage, max_gap_ratio


def _estimate_radial_error_ratio(contour: np.ndarray, x: int, y: int, radius: int) -> float:
    if radius <= 0 or contour is None or len(contour) < 5:
        return 1.0
    points = contour.reshape(-1, 2).astype(np.float32)
    distances = np.sqrt(((points[:, 0] - float(x)) ** 2) + ((points[:, 1] - float(y)) ** 2))
    if distances.size == 0:
        return 1.0
    return float(np.std(distances) / max(float(radius), 1.0))


def _estimate_ring_contrast(gray: np.ndarray, x: int, y: int, radius: int) -> float:
    height, width = gray.shape[:2]
    if radius <= 4:
        return 0.0

    yy, xx = np.ogrid[:height, :width]
    distances = np.sqrt((xx - float(x)) ** 2 + (yy - float(y)) ** 2)
    ring_half_band = max(2.0, radius * 0.08)
    inner_band = max(2.0, radius * 0.18)
    outer_band = max(2.0, radius * 0.18)

    ring_mask = np.abs(distances - float(radius)) <= ring_half_band
    inner_mask = (distances >= max(0.0, float(radius) - inner_band * 1.2)) & (distances <= max(1.0, float(radius) - inner_band))
    outer_mask = (distances >= float(radius) + outer_band) & (distances <= float(radius) + outer_band * 1.8)

    if not np.any(ring_mask) or not np.any(inner_mask) or not np.any(outer_mask):
        return 0.0

    ring_mean = float(np.mean(gray[ring_mask]))
    inner_mean = float(np.mean(gray[inner_mask]))
    outer_mean = float(np.mean(gray[outer_mask]))
    contrast = abs(ring_mean - (inner_mean + outer_mean) * 0.5) / 255.0
    return max(0.0, min(1.0, contrast))


def _build_contour_masks(normalized: np.ndarray) -> list[np.ndarray]:
    blurred = cv2.GaussianBlur(normalized, (7, 7), 1.4)
    _, otsu_binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, otsu_binary_inv = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        51,
        4,
    )
    adaptive_inv = cv2.bitwise_not(adaptive)
    edges = cv2.Canny(blurred, 45, 135)
    kernel = np.ones((5, 5), dtype=np.uint8)
    closed_edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    return [otsu_binary, otsu_binary_inv, adaptive, adaptive_inv, closed_edges]


def _resize_for_detection(gray: np.ndarray, max_width: int = 448) -> tuple[np.ndarray, float]:
    height, width = gray.shape[:2]
    if width <= max_width:
        return gray, 1.0
    scale = max_width / float(width)
    resized = cv2.resize(
        gray,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def _passes_large_circle_filter(
    x: int,
    y: int,
    radius: int,
    width: int,
    height: int,
    min_radius: int,
    max_radius: int,
    min_width_ratio: float,
    min_short_side_ratio: float,
) -> bool:
    short_side = float(min(width, height))
    long_side = float(max(width, height))
    diameter = int(radius * 2)
    min_target_diameter = short_side * float(min_short_side_ratio)
    max_target_diameter = long_side
    max_target_radius = max(1, int(short_side) - 1)
    if radius < min_radius or radius > max_radius:
        return False
    if radius >= max_target_radius:
        return False
    if diameter < min_target_diameter or diameter > max_target_diameter:
        return False
    if diameter < (width * float(min_width_ratio)):
        return False
    if x - radius < 0 or y - radius < 0 or x + radius >= width or y + radius >= height:
        return False
    return True


def detect_circles(
    frame,
    dp: float,
    min_dist: float,
    param1: float,
    param2: float,
    min_radius: int,
    max_radius: int,
    min_circularity: float,
    min_edge_support: float,
    center_reject_margin_px: int,
    max_candidates: int,
    min_contour_area_ratio: float,
    max_contour_area_ratio: float,
    min_fill_ratio: float,
    max_radial_error_ratio: float,
    enhancer: FrameEnhancer | None = None,
    detection_width: int = 384,
) -> tuple[list[CircleDetection], np.ndarray, np.ndarray]:
    del center_reject_margin_px
    del max_candidates

    prepared_enhancer = enhancer or FrameEnhancer(EnhancementConfig())
    enhanced_frame, normalized = prepared_enhancer.enhance(frame)
    height, width = normalized.shape[:2]

    detect_gray, detect_scale = _resize_for_detection(
        normalized,
        max_width=max(128, int(detection_width)),
    )
    detect_height, detect_width = detect_gray.shape[:2]
    detect_min_radius = max(1, int(round(min_radius * detect_scale)))
    detect_max_radius = max(detect_min_radius, int(round(max_radius * detect_scale)))

    detect_edges = cv2.Canny(detect_gray, 60, 160)
    detect_blurred = cv2.GaussianBlur(detect_gray, (9, 9), 1.6)
    circles = cv2.HoughCircles(
        detect_blurred,
        cv2.HOUGH_GRADIENT,
        dp=float(dp),
        minDist=max(8.0, float(min_dist) * detect_scale),
        param1=float(param1),
        param2=float(param2),
        minRadius=detect_min_radius,
        maxRadius=detect_max_radius,
    )

    center_x = width // 2
    center_y = height // 2
    short_side = float(min(width, height))
    results: list[CircleDetection] = []
    inverse_scale = 1.0 / detect_scale if detect_scale > 0 else 1.0
    min_width_ratio = 0.40
    min_short_side_ratio = 0.40

    if circles is not None:
        rounded = np.round(circles[0, :]).astype(int)
        for x, y, radius in rounded:
            x = int(round(x * inverse_scale))
            y = int(round(y * inverse_scale))
            radius = int(round(radius * inverse_scale))
            if not _passes_large_circle_filter(
                x,
                y,
                radius,
                width,
                height,
                min_radius,
                max_radius,
                min_width_ratio,
                min_short_side_ratio,
            ):
                continue

            detect_x = int(round(x * detect_scale))
            detect_y = int(round(y * detect_scale))
            detect_radius = max(1, int(round(radius * detect_scale)))
            circularity = _estimate_circularity(detect_gray, detect_x, detect_y, detect_radius)
            edge_support, angular_coverage, max_gap_ratio = _estimate_edge_profile(
                detect_edges, detect_x, detect_y, detect_radius
            )
            ring_contrast = _estimate_ring_contrast(detect_gray, detect_x, detect_y, detect_radius)
            diameter_ratio = (radius * 2.0) / short_side if short_side > 0 else 0.0
            if circularity < max(0.52, float(min_circularity)) and edge_support < float(min_edge_support):
                continue
            if angular_coverage < 0.58:
                continue
            if max_gap_ratio > 0.34:
                continue
            if ring_contrast < 0.05 and edge_support < max(float(min_edge_support) + 0.08, 0.30):
                continue

            distance = hypot(x - center_x, y - center_y)
            score = (
                (0.30 * circularity)
                + (0.28 * edge_support)
                + (0.20 * angular_coverage)
                + (0.18 * ring_contrast)
                + (0.04 * max(0.0, 1.0 - max_gap_ratio))
                - (distance / max(width, height))
            )
            results.append(
                CircleDetection(
                    x=x,
                    y=y,
                    radius=radius,
                    distance_to_center=distance,
                    circularity=round(circularity, 4),
                    edge_support=round(edge_support, 4),
                    fill_ratio=0.0,
                    radial_error_ratio=round(max_gap_ratio, 4),
                    angular_coverage=round(angular_coverage, 4),
                    diameter_ratio=round(diameter_ratio, 4),
                    score=round(score, 4),
                    source="hough",
                )
            )

    contour_masks = _build_contour_masks(detect_gray)
    detect_frame_area = float(max(detect_width * detect_height, 1))
    for mask in contour_masks:
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if contour is None or len(contour) < 5:
                continue
            area = float(cv2.contourArea(contour))
            area_ratio = area / detect_frame_area
            if area_ratio < float(min_contour_area_ratio) or area_ratio > float(max_contour_area_ratio):
                continue

            perimeter = float(cv2.arcLength(contour, True))
            if perimeter <= 0.0:
                continue
            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            detect_radius = int(round(radius))
            detect_x = int(round(cx))
            detect_y = int(round(cy))
            if detect_radius < detect_min_radius or detect_radius > detect_max_radius:
                continue

            x = int(round(detect_x * inverse_scale))
            y = int(round(detect_y * inverse_scale))
            radius = int(round(detect_radius * inverse_scale))
            if not _passes_large_circle_filter(
                x,
                y,
                radius,
                width,
                height,
                min_radius,
                max_radius,
                min_width_ratio,
                min_short_side_ratio,
            ):
                continue

            circle_area = float(np.pi * (detect_radius ** 2))
            if circle_area <= 0.0:
                continue
            fill_ratio = area / circle_area
            circularity = float((4.0 * np.pi * area) / (perimeter * perimeter))
            edge_support, angular_coverage, max_gap_ratio = _estimate_edge_profile(
                detect_edges, detect_x, detect_y, detect_radius
            )
            radial_error_ratio = _estimate_radial_error_ratio(contour, detect_x, detect_y, detect_radius)
            ring_contrast = _estimate_ring_contrast(detect_gray, detect_x, detect_y, detect_radius)
            diameter_ratio = (radius * 2.0) / short_side if short_side > 0 else 0.0
            if fill_ratio < float(min_fill_ratio):
                continue
            if radial_error_ratio > float(max_radial_error_ratio):
                continue
            if angular_coverage < 0.60:
                continue
            if max_gap_ratio > 0.30:
                continue
            if circularity < max(0.56, float(min_circularity)) and edge_support < max(float(min_edge_support) * 0.9, 0.22):
                continue
            if ring_contrast < 0.04 and edge_support < max(float(min_edge_support) + 0.06, 0.28):
                continue

            distance = hypot(x - center_x, y - center_y)
            score = (
                (0.22 * min(circularity, 1.0))
                + (0.22 * min(edge_support, 1.0))
                + (0.20 * min(fill_ratio, 1.0))
                + (0.16 * min(angular_coverage, 1.0))
                + (0.10 * min(ring_contrast * 4.0, 1.0))
                + (0.08 * max(0.0, 1.0 - radial_error_ratio))
                + (0.04 * max(0.0, 1.0 - max_gap_ratio))
                - (distance / max(width, height))
            )
            results.append(
                CircleDetection(
                    x=x,
                    y=y,
                    radius=radius,
                    distance_to_center=distance,
                    circularity=round(circularity, 4),
                    edge_support=round(edge_support, 4),
                    fill_ratio=round(fill_ratio, 4),
                    radial_error_ratio=round(radial_error_ratio, 4),
                    angular_coverage=round(angular_coverage, 4),
                    diameter_ratio=round(diameter_ratio, 4),
                    score=round(score, 4),
                    source="contour",
                )
            )

    results.sort(key=lambda item: (-item.score, item.distance_to_center))
    deduped: list[CircleDetection] = []
    for candidate in results:
        if any(
            hypot(candidate.x - kept.x, candidate.y - kept.y) < max(candidate.radius, kept.radius) * 0.6
            for kept in deduped
        ):
            continue
        deduped.append(candidate)

    deduped.sort(key=lambda item: (-item.score, item.distance_to_center))
    return deduped, normalized, enhanced_frame


