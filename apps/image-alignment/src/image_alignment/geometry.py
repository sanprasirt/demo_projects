"""Ratio test and homography checks that do not need OpenCV."""

from __future__ import annotations

import math
from typing import Sequence, TypeVar

import numpy as np

T = TypeVar("T")

MIN_MATCHES = 8
MIN_INLIERS = 8


def ratio_test(pairs: Sequence[Sequence[T]], ratio: float) -> list[T]:
    """Keep a nearest neighbor when it is closer than ``ratio`` times the second.

    A pair of zero distances is a perfect tie between identical descriptors, so
    it is kept. Any other tie loses, which is Lowe's strict inequality.
    """
    if not 0 < ratio <= 1:
        raise ValueError("Ratio threshold must be between 0 and 1.")

    kept: list[T] = []
    for pair in pairs:
        if len(pair) < 2:
            continue
        best = pair[0]
        second = pair[1]
        best_distance = float(best.distance)  # type: ignore[attr-defined]
        second_distance = float(second.distance)  # type: ignore[attr-defined]
        if second_distance <= 0:
            if best_distance <= 0:
                kept.append(best)
            continue
        if best_distance < ratio * second_distance:
            kept.append(best)
    return kept


def _apply(homography: np.ndarray, x: float, y: float) -> tuple[float, float] | None:
    u = homography[0, 0] * x + homography[0, 1] * y + homography[0, 2]
    v = homography[1, 0] * x + homography[1, 1] * y + homography[1, 2]
    w = homography[2, 0] * x + homography[2, 1] * y + homography[2, 2]
    if not math.isfinite(w) or abs(w) < 1e-8:
        return None
    return (u / w, v / w)


def _signed_area(points: Sequence[tuple[float, float]]) -> float:
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return area / 2


def _cross(origin: tuple[float, float], end: tuple[float, float], point: tuple[float, float]) -> float:
    return (end[0] - origin[0]) * (point[1] - origin[1]) - (end[1] - origin[1]) * (point[0] - origin[0])


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def sign(value: float) -> int:
        if abs(value) < 1e-9:
            return 0
        return 1 if value > 0 else -1

    d1 = sign(_cross(a, b, c))
    d2 = sign(_cross(a, b, d))
    d3 = sign(_cross(c, d, a))
    d4 = sign(_cross(c, d, b))
    return d1 * d2 < 0 and d3 * d4 < 0


def assess_homography(
    homography: np.ndarray | None,
    source_size: tuple[int, int],
    destination_size: tuple[int, int],
) -> str | None:
    """Return a short reason the homography cannot be used, or None.

    ``source_size`` and ``destination_size`` are ``(width, height)``. The check
    rejects non-finite values, a near-zero determinant, a flipped or folded
    quad, and a warp that collapses or explodes the photo.
    """
    if homography is None or homography.shape != (3, 3):
        return "Homography estimation failed."
    matrix = np.asarray(homography, dtype=np.float64)
    if not np.isfinite(matrix).all():
        return "The homography has non-finite values."
    if abs(matrix[2, 2]) < 1e-12:
        return "The homography is degenerate (zero scale)."

    normalized = matrix / matrix[2, 2]
    determinant = float(np.linalg.det(normalized))
    if not math.isfinite(determinant) or abs(determinant) < 1e-8:
        return "The homography is degenerate (the matched points are nearly collinear)."

    width, height = source_size
    corners = ((0.0, 0.0), (float(width), 0.0), (float(width), float(height)), (0.0, float(height)))
    mapped: list[tuple[float, float]] = []
    for x, y in corners:
        point = _apply(normalized, x, y)
        if point is None or not math.isfinite(point[0]) or not math.isfinite(point[1]):
            return "The homography sends part of the photo to infinity."
        mapped.append(point)

    area = _signed_area(mapped)
    if area <= 0:
        return "The homography flips the photo."
    if _segments_intersect(mapped[0], mapped[1], mapped[2], mapped[3]) or _segments_intersect(
        mapped[1], mapped[2], mapped[3], mapped[0]
    ):
        return "The homography folds the photo."

    source_area = float(width * height)
    if area < source_area * 0.02 or area > source_area * 40:
        return "The homography collapses or explodes the photo."

    destination_area = float(destination_size[0] * destination_size[1])
    if destination_area <= 0:
        return "The reference image is empty."
    return None
