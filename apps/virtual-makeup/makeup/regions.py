"""Masks for lipstick, blush, and eyeshadow from face-landmark pixels.

Index groups follow the published MediaPipe face mesh contour topology
(subject's left and right). The lower brow is chosen at runtime as the
brow chain closer to the eyelid, so a swapped chain cannot paint the forehead.
"""

from __future__ import annotations

import cv2
import numpy as np

# Lip cycles are the two disjoint loops in MediaPipe's lip contour.
LIP_OUTER = (
    61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
    409, 270, 269, 267, 0, 37, 39, 40, 185,
)
LIP_INNER = (
    78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308,
    415, 310, 311, 312, 13, 82, 81, 80, 191,
)

# Subject's right eye (viewer's left on an unmirrored photo).
RIGHT_EYE_UPPER = (33, 246, 161, 160, 159, 158, 157, 173)
RIGHT_EYE = (
    33, 246, 161, 160, 159, 158, 157, 173, 133,
    155, 154, 153, 145, 144, 163, 7,
)
RIGHT_BROW_A = (46, 53, 52, 65, 55)
RIGHT_BROW_B = (70, 63, 105, 66, 107)

# Subject's left eye.
LEFT_EYE_UPPER = (263, 466, 388, 387, 386, 385, 384, 398)
LEFT_EYE = (
    263, 466, 388, 387, 386, 385, 384, 398, 362,
    382, 381, 380, 374, 373, 390, 249,
)
LEFT_BROW_A = (276, 283, 282, 295, 285)
LEFT_BROW_B = (300, 293, 334, 296, 336)

NOSE_TIP = 1
SUBJECT_RIGHT_EYE_OUTER = 33
SUBJECT_LEFT_EYE_OUTER = 263
SUBJECT_RIGHT_MOUTH = 61
SUBJECT_LEFT_MOUTH = 291
SUBJECT_RIGHT_SIDE = 234
SUBJECT_LEFT_SIDE = 454


def _points(landmarks: np.ndarray) -> np.ndarray:
    pts = np.asarray(landmarks, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 468:
        raise ValueError("expected face landmarks as an (N, 2) pixel array, N >= 468")
    return pts


def _poly(points: np.ndarray, indices: tuple[int, ...]) -> np.ndarray:
    return np.round(points[list(indices)]).astype(np.int32)


def fill_polygon(height: int, width: int, poly: np.ndarray) -> np.ndarray:
    """Binary mask of a polygon. Points outside the frame are clipped by OpenCV."""
    mask = np.zeros((height, width), dtype=np.uint8)
    if len(poly) >= 3:
        cv2.fillPoly(mask, [np.ascontiguousarray(poly)], 255)
    return mask


def feather(mask: np.ndarray, radius: int) -> np.ndarray:
    radius = int(radius)
    if radius < 1:
        return mask
    radius = min(radius, max(1, min(mask.shape) // 4), 80)
    kernel = radius * 2 + 1
    return cv2.GaussianBlur(mask, (kernel, kernel), sigmaX=radius * 0.5)


def _shrink(poly: np.ndarray, keep: float) -> np.ndarray:
    center = poly.astype(np.float32).mean(axis=0)
    moved = center + (poly.astype(np.float32) - center) * float(keep)
    return np.round(moved).astype(np.int32)


def lip_mask(points: np.ndarray, width: int, height: int, feather_px: int) -> np.ndarray:
    """Lip band. A shrunken inner loop keeps the mouth opening bare."""
    pts = _points(points)
    outer = fill_polygon(height, width, _poly(pts, LIP_OUTER))
    inner = fill_polygon(height, width, _shrink(_poly(pts, LIP_INNER), keep=0.55))
    band = cv2.subtract(outer, inner)
    soft = feather(band, feather_px)
    mouth = cv2.erode(inner, np.ones((3, 3), np.uint8), iterations=1)
    soft[mouth > 0] = 0
    return soft


def _lower_brow(points: np.ndarray, chain_a: tuple[int, ...], chain_b: tuple[int, ...]) -> tuple[int, ...]:
    """Image y grows downward, so the chain nearer the eyelid has the larger y."""
    mean_a = float(points[list(chain_a), 1].mean())
    mean_b = float(points[list(chain_b), 1].mean())
    return chain_a if mean_a >= mean_b else chain_b


def _eyeshadow_one(
    points: np.ndarray,
    height: int,
    width: int,
    brow_a: tuple[int, ...],
    brow_b: tuple[int, ...],
    lid: tuple[int, ...],
    eye: tuple[int, ...],
) -> np.ndarray:
    brow = _lower_brow(points, brow_a, brow_b)
    cloud = np.concatenate([_poly(points, brow), _poly(points, lid)], axis=0)
    hull = cv2.convexHull(cloud).reshape(-1, 2)
    shadow = fill_polygon(height, width, hull)
    eyeball = fill_polygon(height, width, _poly(points, eye))
    core = cv2.erode(eyeball, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)
    return cv2.subtract(shadow, core)


def eyeshadow_mask(points: np.ndarray, width: int, height: int, feather_px: int) -> np.ndarray:
    pts = _points(points)
    right = _eyeshadow_one(pts, height, width, RIGHT_BROW_A, RIGHT_BROW_B, RIGHT_EYE_UPPER, RIGHT_EYE)
    left = _eyeshadow_one(pts, height, width, LEFT_BROW_A, LEFT_BROW_B, LEFT_EYE_UPPER, LEFT_EYE)
    soft = feather(cv2.add(right, left), feather_px)
    for eye in (RIGHT_EYE, LEFT_EYE):
        core = fill_polygon(height, width, _shrink(_poly(pts, eye), keep=0.72))
        soft[core > 0] = 0
    return soft


def cheek_centers(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Subject's right cheek, then subject's left, as (x, y) pixels."""
    pts = _points(points)

    def center(eye_i: int, mouth_i: int, side_i: int) -> np.ndarray:
        eye = pts[eye_i]
        mouth = pts[mouth_i]
        side = pts[side_i]
        nose = pts[NOSE_TIP]
        mid = (eye + mouth) * 0.5
        mixed = side * 0.38 + mid * 0.42 + nose * 0.20
        mixed = mixed.copy()
        mixed[1] += abs(float(mouth[1] - eye[1])) * 0.12
        return mixed

    subject_right = center(SUBJECT_RIGHT_EYE_OUTER, SUBJECT_RIGHT_MOUTH, SUBJECT_RIGHT_SIDE)
    subject_left = center(SUBJECT_LEFT_EYE_OUTER, SUBJECT_LEFT_MOUTH, SUBJECT_LEFT_SIDE)
    return subject_right, subject_left


def blush_mask(points: np.ndarray, width: int, height: int, feather_px: int) -> np.ndarray:
    pts = _points(points)
    mask = np.zeros((height, width), dtype=np.uint8)
    eye_dist = float(np.linalg.norm(pts[SUBJECT_RIGHT_EYE_OUTER] - pts[SUBJECT_LEFT_EYE_OUTER]))
    axis_x = max(6, int(round(eye_dist * 0.26)))
    axis_y = max(5, int(round(eye_dist * 0.17)))
    for center in cheek_centers(pts):
        cx = int(np.clip(round(float(center[0])), 0, width - 1))
        cy = int(np.clip(round(float(center[1])), 0, height - 1))
        cv2.ellipse(mask, (cx, cy), (axis_x, axis_y), 0, 0, 360, 255, thickness=-1)
    soft = feather(mask, max(feather_px, int(eye_dist * 0.12)))
    lips = fill_polygon(height, width, _poly(pts, LIP_OUTER))
    lips = cv2.dilate(lips, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)), iterations=1)
    soft[lips > 0] = 0
    for eye in (RIGHT_EYE, LEFT_EYE):
        soft[fill_polygon(height, width, _poly(pts, eye)) > 0] = 0
    return soft


def build_masks(points: np.ndarray, width: int, height: int) -> dict[str, np.ndarray]:
    """Feathered uint8 masks keyed by lipstick, blush, and eyeshadow."""
    pts = _points(points)
    face_h = float(np.linalg.norm(pts[:, 1].max() - pts[:, 1].min()))
    face_h = max(face_h, 32.0)
    return {
        "lipstick": lip_mask(pts, width, height, feather_px=max(2, int(face_h * 0.012))),
        "blush": blush_mask(pts, width, height, feather_px=max(4, int(face_h * 0.045))),
        "eyeshadow": eyeshadow_mask(pts, width, height, feather_px=max(2, int(face_h * 0.02))),
    }
