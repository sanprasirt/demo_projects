"""Detect, match, and warp a photo of a planar scene onto a reference."""

from __future__ import annotations

import time

import cv2
import numpy as np

from image_alignment.draw import (
    INLIER,
    KEYPOINT_PHOTO,
    KEYPOINT_REFERENCE,
    MATCH,
    draw_correspondences,
    draw_keypoints,
)
from image_alignment.geometry import MIN_INLIERS, MIN_MATCHES, assess_homography, ratio_test
from image_alignment.pipeline_types import AlignmentResult, Correspondence

DETECTORS = ("ORB", "SIFT", "AKAZE")
MATCHERS = ("BFMatcher", "FLANN")
METHODS = {
    "RANSAC": "RANSAC",
    "USAC_MAGSAC": "USAC_MAGSAC",
}


def align_images(
    reference: np.ndarray,
    photo: np.ndarray,
    *,
    detector: str = "ORB",
    matcher: str = "BFMatcher",
    max_features: int = 1500,
    ratio: float = 0.75,
    ransac_threshold: float = 3.0,
    method: str = "RANSAC",
    ecc: bool = False,
    max_side: int = 1200,
) -> AlignmentResult:
    """Align ``photo`` to ``reference`` and return drawings plus stats.

    Both images are RGB ``uint8`` arrays. Coordinates in the result are in the
    resized images, and the warp is the size of the resized reference.
    """
    started = time.perf_counter()
    try:
        reference_rgb = _as_rgb(reference)
        photo_rgb = _as_rgb(photo)
    except ValueError as exc:
        return _finish(started, False, str(exc), detector, matcher, method)

    if detector not in DETECTORS:
        return _finish(started, False, f"Unknown detector {detector}.", detector, matcher, method)
    if matcher not in MATCHERS:
        return _finish(started, False, f"Unknown matcher {matcher}.", detector, matcher, method)
    if method not in METHODS:
        return _finish(started, False, f"Unknown estimator {method}.", detector, matcher, method)
    if max_features < MIN_MATCHES:
        return _finish(
            started,
            False,
            f"Ask for at least {MIN_MATCHES} features.",
            detector,
            matcher,
            method,
        )
    if ransac_threshold <= 0:
        return _finish(
            started,
            False,
            "The reprojection threshold must be positive.",
            detector,
            matcher,
            method,
        )

    try:
        ratio_test([], ratio)
    except ValueError as exc:
        return _finish(started, False, str(exc), detector, matcher, method)

    reference_rgb = _resize_max(reference_rgb, max_side)
    photo_rgb = _resize_max(photo_rgb, max_side)
    reference_gray = cv2.cvtColor(reference_rgb, cv2.COLOR_RGB2GRAY)
    photo_gray = cv2.cvtColor(photo_rgb, cv2.COLOR_RGB2GRAY)

    feature = _make_detector(detector, max_features)
    keypoints_reference, desc_reference = _detect(feature, reference_gray, max_features)
    keypoints_photo, desc_photo = _detect(feature, photo_gray, max_features)
    reference_points = [_point(kp) for kp in keypoints_reference]
    photo_points = [_point(kp) for kp in keypoints_photo]
    keypoints_reference_image = draw_keypoints(
        reference_rgb, reference_points, KEYPOINT_REFERENCE, "Reference"
    )
    keypoints_photo_image = draw_keypoints(photo_rgb, photo_points, KEYPOINT_PHOTO, "Photo")

    partial = dict(
        keypoints_reference=len(keypoints_reference),
        keypoints_photo=len(keypoints_photo),
        reference=reference_rgb,
        keypoints_reference_image=keypoints_reference_image,
        keypoints_photo_image=keypoints_photo_image,
    )

    if desc_reference is None or desc_photo is None or len(keypoints_reference) < MIN_MATCHES or len(keypoints_photo) < MIN_MATCHES:
        count_ref = len(keypoints_reference)
        count_photo = len(keypoints_photo)
        return _finish(
            started,
            False,
            (
                f"Not enough keypoints (reference {count_ref}, photo {count_photo}; "
                f"need at least {MIN_MATCHES} on each). Use a more textured planar pair "
                "or raise the feature cap."
            ),
            detector,
            matcher,
            method,
            **partial,
        )

    desc_reference = np.ascontiguousarray(desc_reference)
    desc_photo = np.ascontiguousarray(desc_photo)
    try:
        raw_pairs = _knn_match(desc_photo, desc_reference, matcher)
    except cv2.error:
        hint = " Try BFMatcher." if matcher == "FLANN" else ""
        return _finish(
            started,
            False,
            f"{matcher} could not match these descriptors.{hint}",
            detector,
            matcher,
            method,
            **partial,
        )

    good = []
    for match in ratio_test(_as_pairs(raw_pairs), ratio):
        if 0 <= match.queryIdx < len(keypoints_photo) and 0 <= match.trainIdx < len(keypoints_reference):
            good.append(match)

    correspondences = [
        Correspondence(
            photo_xy=_point(keypoints_photo[match.queryIdx]),
            reference_xy=_point(keypoints_reference[match.trainIdx]),
            distance=float(match.distance),
            inlier=False,
        )
        for match in good
    ]
    matches_image = draw_correspondences(
        reference_rgb,
        photo_rgb,
        correspondences,
        color=MATCH,
        total=len(correspondences),
    )
    partial.update(match_count=len(good), matches_image=matches_image)

    if len(good) < MIN_MATCHES:
        return _finish(
            started,
            False,
            (
                f"Not enough matches to estimate a homography (found {len(good)}, "
                f"need at least {MIN_MATCHES}). Raise the ratio threshold, ask for more "
                "features, or use a more textured planar pair."
            ),
            detector,
            matcher,
            method,
            **partial,
        )

    # Source points are on the photo. Destination points are on the reference.
    source = np.float32([keypoints_photo[match.queryIdx].pt for match in good]).reshape(-1, 1, 2)
    destination = np.float32([keypoints_reference[match.trainIdx].pt for match in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(
        source,
        destination,
        method=_method_flag(method),
        ransacReprojThreshold=float(ransac_threshold),
        maxIters=8000,
        confidence=0.999,
    )
    if mask is None:
        inlier_flags = np.zeros(len(good), dtype=bool)
    else:
        inlier_flags = mask.ravel().astype(bool)
        if inlier_flags.shape[0] != len(good):
            fitted = np.zeros(len(good), dtype=bool)
            count = min(len(good), inlier_flags.shape[0])
            fitted[:count] = inlier_flags[:count]
            inlier_flags = fitted

    judged = [
        Correspondence(
            photo_xy=item.photo_xy,
            reference_xy=item.reference_xy,
            distance=item.distance,
            inlier=bool(flag),
        )
        for item, flag in zip(correspondences, inlier_flags, strict=True)
    ]
    inliers_image = draw_correspondences(
        reference_rgb,
        photo_rgb,
        judged,
        split_inliers=True,
        total=len(judged),
    )
    inlier_count = int(inlier_flags.sum())
    partial.update(inlier_count=inlier_count, inliers_image=inliers_image, homography=homography)

    reason = assess_homography(
        homography,
        (photo_rgb.shape[1], photo_rgb.shape[0]),
        (reference_rgb.shape[1], reference_rgb.shape[0]),
    )
    if reason is not None or inlier_count < MIN_INLIERS:
        if reason is None:
            reason = (
                f"RANSAC kept only {inlier_count} inliers, which is not enough to trust the warp. "
                "Raise the feature cap or the reprojection threshold."
            )
        else:
            reason = f"{reason} Alignment was not applied."
        return _finish(started, False, reason, detector, matcher, method, **partial)

    assert homography is not None
    ecc_applied = False
    note = ""
    if ecc:
        refined, refined_ok = _refine_ecc(reference_gray, photo_gray, homography)
        if refined_ok:
            refined_reason = assess_homography(
                refined,
                (photo_rgb.shape[1], photo_rgb.shape[0]),
                (reference_rgb.shape[1], reference_rgb.shape[0]),
            )
            if refined_reason is None:
                homography = refined
                ecc_applied = True
                note = " ECC refined the warp."
            else:
                note = " ECC refinement was unstable, so the RANSAC homography is shown."
        else:
            note = " ECC did not converge, so the RANSAC homography is shown."

    warped, difference, overlap_mae = _warp(photo_rgb, reference_rgb, homography)
    message = f"The homography maps the photo onto the reference.{note}"
    partial.update(
        ecc_applied=ecc_applied,
        homography=homography,
        warped=warped,
        difference=difference,
        overlap_mae=overlap_mae,
    )
    return _finish(started, True, message, detector, matcher, method, **partial)


def _as_rgb(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim == 2:
        array = cv2.cvtColor(array, cv2.COLOR_GRAY2RGB)
    elif array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError("Images must have 1, 3, or 4 channels.")
    elif array.shape[2] == 4:
        array = cv2.cvtColor(array, cv2.COLOR_RGBA2RGB)
    if array.dtype != np.uint8:
        scaled = array.astype(np.float32)
        peak = float(scaled.max()) if scaled.size else 0.0
        if peak <= 1.0:
            scaled *= 255.0
        array = np.clip(scaled, 0, 255).astype(np.uint8)
    if min(array.shape[:2]) < 16:
        raise ValueError("The image is too small to align.")
    return np.ascontiguousarray(array)


def _resize_max(image: np.ndarray, max_side: int) -> np.ndarray:
    if max_side <= 0:
        return image
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image
    scale = max_side / longest
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def _make_detector(name: str, max_features: int) -> cv2.Feature2D:
    if name == "ORB":
        return cv2.ORB_create(nfeatures=max_features)
    if name == "SIFT":
        return cv2.SIFT_create(nfeatures=max_features)
    try:
        return cv2.AKAZE_create(max_points=max_features)
    except TypeError:
        return cv2.AKAZE_create()


def _detect(
    detector: cv2.Feature2D,
    gray: np.ndarray,
    max_features: int,
) -> tuple[list[cv2.KeyPoint], np.ndarray | None]:
    keypoints, descriptors = detector.detectAndCompute(gray, None)
    keypoints = list(keypoints or [])
    if len(keypoints) > max_features:
        order = sorted(range(len(keypoints)), key=lambda index: keypoints[index].response, reverse=True)
        order = order[:max_features]
        keypoints = [keypoints[index] for index in order]
        if descriptors is not None:
            descriptors = descriptors[order]
    return keypoints, descriptors


def _knn_match(desc_photo: np.ndarray, desc_reference: np.ndarray, matcher_name: str):
    if matcher_name == "BFMatcher":
        norm = cv2.NORM_HAMMING if desc_photo.dtype == np.uint8 else cv2.NORM_L2
        matcher = cv2.BFMatcher(norm, crossCheck=False)
        return matcher.knnMatch(desc_photo, desc_reference, k=2)

    # OpenCV's flann index enum. The 4.14 wheel does not re-export the names.
    lsh = int(getattr(cv2, "FLANN_INDEX_LSH", 6))
    kdtree = int(getattr(cv2, "FLANN_INDEX_KDTREE", 1))
    if desc_photo.dtype == np.uint8:
        index_params = dict(algorithm=lsh, table_number=6, key_size=12, multi_probe_level=1)
        search_params: dict = dict(checks=32)
        query = desc_photo
        train = desc_reference
    else:
        index_params = dict(algorithm=kdtree, trees=5)
        search_params = dict(checks=50)
        query = np.ascontiguousarray(desc_photo, dtype=np.float32)
        train = np.ascontiguousarray(desc_reference, dtype=np.float32)
    matcher = cv2.FlannBasedMatcher(index_params, search_params)
    return matcher.knnMatch(query, train, k=2)


def _as_pairs(raw) -> list[list]:
    pairs = []
    for item in raw:
        if isinstance(item, (list, tuple)):
            pairs.append(list(item))
        else:
            pairs.append([item])
    return pairs


def _method_flag(method: str) -> int:
    if method == "USAC_MAGSAC":
        return int(cv2.USAC_MAGSAC)
    return int(cv2.RANSAC)


def _refine_ecc(
    reference_gray: np.ndarray,
    photo_gray: np.ndarray,
    homography: np.ndarray,
) -> tuple[np.ndarray, bool]:
    warp = np.ascontiguousarray(homography, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 1e-4)
    reference_blur = cv2.GaussianBlur(reference_gray, (5, 5), 0)
    photo_blur = cv2.GaussianBlur(photo_gray, (5, 5), 0)
    try:
        # The warp maps the photo (input) onto the reference (template).
        _correlation, refined = cv2.findTransformECC(
            reference_blur,
            photo_blur,
            warp,
            cv2.MOTION_HOMOGRAPHY,
            criteria,
            None,
            5,
        )
    except cv2.error:
        return homography, False
    return refined.astype(np.float64), True


def _warp(
    photo: np.ndarray,
    reference: np.ndarray,
    homography: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    size = (reference.shape[1], reference.shape[0])
    warped = cv2.warpPerspective(
        photo,
        homography,
        size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    valid = np.full(photo.shape[:2], 255, np.uint8)
    mask = cv2.warpPerspective(
        valid,
        homography,
        size,
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    mask = cv2.erode(mask, np.ones((3, 3), np.uint8))
    absolute = cv2.absdiff(reference, warped)
    overlap = mask > 0
    if int(overlap.sum()) < 50:
        mae = float("nan")
    else:
        mae = float(absolute.mean(axis=2)[overlap].mean())
    difference = np.clip(absolute.astype(np.uint16) * 3, 0, 255).astype(np.uint8)
    difference[~overlap] = 127
    return warped, difference, mae


def _point(keypoint: cv2.KeyPoint) -> tuple[float, float]:
    return (float(keypoint.pt[0]), float(keypoint.pt[1]))


def _finish(
    started: float,
    ok: bool,
    message: str,
    detector: str,
    matcher: str,
    method: str,
    **fields,
) -> AlignmentResult:
    match_count = int(fields.get("match_count", 0))
    inlier_count = int(fields.get("inlier_count", 0))
    ratio = inlier_count / match_count if match_count else 0.0
    return AlignmentResult(
        ok=ok,
        message=message,
        keypoints_reference=int(fields.get("keypoints_reference", 0)),
        keypoints_photo=int(fields.get("keypoints_photo", 0)),
        match_count=match_count,
        inlier_count=inlier_count,
        inlier_ratio=ratio,
        runtime_ms=(time.perf_counter() - started) * 1000,
        overlap_mae=fields.get("overlap_mae"),
        detector=detector,
        matcher=matcher,
        method=method,
        ecc_applied=bool(fields.get("ecc_applied", False)),
        homography=fields.get("homography"),
        reference=fields.get("reference"),
        keypoints_reference_image=fields.get("keypoints_reference_image"),
        keypoints_photo_image=fields.get("keypoints_photo_image"),
        matches_image=fields.get("matches_image"),
        inliers_image=fields.get("inliers_image"),
        warped=fields.get("warped"),
        difference=fields.get("difference"),
    )
