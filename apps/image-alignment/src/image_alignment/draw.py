"""Draw keypoints and match lines on RGB images."""

from __future__ import annotations

import cv2
import numpy as np

from image_alignment.pipeline_types import Correspondence

INK = (28, 27, 25)
MATCH = (36, 86, 158)
INLIER = (28, 130, 72)
OUTLIER = (186, 52, 44)
KEYPOINT_REFERENCE = (28, 86, 150)
KEYPOINT_PHOTO = (176, 84, 32)
PAPER = (244, 242, 238)


def draw_keypoints(
    image: np.ndarray,
    points: list[tuple[float, float]],
    color: tuple[int, int, int],
    label: str,
) -> np.ndarray:
    canvas = image.copy()
    for x, y in points:
        center = _clamp(x, y, canvas.shape[1], canvas.shape[0])
        cv2.circle(canvas, center, 4, INK, 1, lineType=cv2.LINE_AA)
        cv2.circle(canvas, center, 2, color, -1, lineType=cv2.LINE_AA)
    _label(canvas, label)
    return canvas


def draw_correspondences(
    reference: np.ndarray,
    photo: np.ndarray,
    pairs: list[Correspondence],
    *,
    color: tuple[int, int, int] | None = None,
    split_inliers: bool = False,
    total: int | None = None,
) -> np.ndarray:
    """Draw the reference and the photo side by side with match lines.

    When ``split_inliers`` is set, outliers are red and inliers are green.
    Otherwise every pair uses ``color``.
    """
    shown = pairs
    if split_inliers:
        outliers = [pair for pair in pairs if not pair.inlier]
        inliers = [pair for pair in pairs if pair.inlier]
        outliers = _closest(outliers, 40)
        inliers = _closest(inliers, 140)
        shown = outliers + inliers
    else:
        shown = _closest(list(pairs), 160)

    canvas, photo_x = _stack(reference, photo)
    _label(canvas, "Reference", 8)
    _label(canvas, "Photo", photo_x + 8)

    for pair in shown:
        line_color = color or MATCH
        if split_inliers:
            line_color = INLIER if pair.inlier else OUTLIER
        start = _clamp(pair.reference_xy[0], pair.reference_xy[1], reference.shape[1], canvas.shape[0])
        end = _clamp(
            pair.photo_xy[0] + photo_x,
            pair.photo_xy[1],
            canvas.shape[1],
            canvas.shape[0],
        )
        cv2.line(canvas, start, end, INK, 3, lineType=cv2.LINE_AA)
        cv2.line(canvas, start, end, line_color, 1, lineType=cv2.LINE_AA)
        cv2.circle(canvas, start, 2, line_color, -1, lineType=cv2.LINE_AA)
        cv2.circle(canvas, end, 2, line_color, -1, lineType=cv2.LINE_AA)

    full_count = total if total is not None else len(pairs)
    if full_count != len(shown):
        kind = "inliers and outliers" if split_inliers else "matches"
        _caption(canvas, f"Showing {len(shown)} of {full_count} {kind}")
    elif full_count == 0:
        _caption(canvas, "No matches")
    return canvas


def _stack(reference: np.ndarray, photo: np.ndarray, gap: int = 16) -> tuple[np.ndarray, int]:
    height = max(reference.shape[0], photo.shape[0])
    width = reference.shape[1] + gap + photo.shape[1]
    canvas = np.full((height, width, 3), PAPER, np.uint8)
    canvas[: reference.shape[0], : reference.shape[1]] = reference
    photo_x = reference.shape[1] + gap
    canvas[: photo.shape[0], photo_x : photo_x + photo.shape[1]] = photo
    return canvas, photo_x


def _closest(pairs: list[Correspondence], limit: int) -> list[Correspondence]:
    if len(pairs) <= limit:
        return pairs
    return sorted(pairs, key=lambda pair: pair.distance)[:limit]


def _clamp(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    return (
        min(max(int(round(x)), 0), max(width - 1, 0)),
        min(max(int(round(y)), 0), max(height - 1, 0)),
    )


def _label(image: np.ndarray, text: str, x: int = 8) -> None:
    (width, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(image, (x, 8), (x + width + 12, 30), (255, 255, 255), -1)
    cv2.putText(image, text, (x + 6, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, INK, 1, cv2.LINE_AA)


def _caption(image: np.ndarray, text: str) -> None:
    height, width = image.shape[:2]
    cv2.rectangle(image, (0, height - 28), (width, height), (255, 255, 255), -1)
    cv2.putText(image, text, (8, height - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.45, INK, 1, cv2.LINE_AA)
