"""Shared records for the alignment pipeline and the drawings."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Correspondence:
    photo_xy: tuple[float, float]
    reference_xy: tuple[float, float]
    distance: float
    inlier: bool


@dataclass
class AlignmentResult:
    ok: bool
    message: str
    keypoints_reference: int
    keypoints_photo: int
    match_count: int
    inlier_count: int
    inlier_ratio: float
    runtime_ms: float
    overlap_mae: float | None
    detector: str
    matcher: str
    method: str
    ecc_applied: bool
    homography: np.ndarray | None
    reference: np.ndarray | None
    keypoints_reference_image: np.ndarray | None
    keypoints_photo_image: np.ndarray | None
    matches_image: np.ndarray | None
    inliers_image: np.ndarray | None
    warped: np.ndarray | None
    difference: np.ndarray | None
