from pathlib import Path

import cv2
import numpy as np
import pytest

from image_alignment.cli import run
from image_alignment.pipeline import align_images
from image_alignment.samples import read_rgb, sample_paths

REFERENCE_PATH, PHOTO_PATH = sample_paths()


def test_opencv_exposes_the_detectors_and_usac():
    assert hasattr(cv2, "ORB_create")
    assert hasattr(cv2, "SIFT_create")
    assert hasattr(cv2, "AKAZE_create")
    assert hasattr(cv2, "USAC_MAGSAC")
    created = cv2.SIFT_create(nfeatures=8)
    created.detectAndCompute(np.zeros((32, 32), np.uint8), None)
    cv2.AKAZE_create()


@pytest.mark.parametrize("detector", ["ORB", "SIFT", "AKAZE"])
def test_sample_pair_aligns(detector: str):
    reference = read_rgb(REFERENCE_PATH)
    photo = read_rgb(PHOTO_PATH)
    result = align_images(reference, photo, detector=detector, max_features=1500)
    assert result.ok, result.message
    assert result.inlier_count >= 10
    assert result.inlier_ratio >= 0.2
    assert result.warped is not None
    assert result.warped.shape == reference.shape
    assert result.overlap_mae is not None
    assert result.overlap_mae < 26
    assert result.runtime_ms > 0


def test_flann_sift_and_usac_ecc_still_align():
    reference = read_rgb(REFERENCE_PATH)
    photo = read_rgb(PHOTO_PATH)
    flann = align_images(reference, photo, detector="SIFT", matcher="FLANN", max_features=1200)
    assert flann.ok, flann.message
    refined = align_images(
        reference,
        photo,
        detector="ORB",
        method="USAC_MAGSAC",
        ecc=True,
        max_features=1200,
    )
    assert refined.ok, refined.message
    assert refined.overlap_mae is not None
    assert refined.overlap_mae < 30


def test_blank_photo_fails_without_a_warp():
    reference = read_rgb(REFERENCE_PATH)
    blank = np.full_like(reference, 235)
    result = align_images(reference, blank, detector="ORB", max_features=800)
    assert not result.ok
    assert result.warped is None
    assert result.message


def test_identical_reference_aligns_tightly():
    reference = read_rgb(REFERENCE_PATH)
    result = align_images(reference, reference.copy(), detector="ORB", max_features=800)
    assert result.ok, result.message
    assert result.inlier_ratio > 0.8
    assert result.overlap_mae is not None
    assert result.overlap_mae < 8


def test_cli_writes_the_warp(tmp_path: Path):
    output = tmp_path / "aligned.png"
    code = run([str(REFERENCE_PATH), str(PHOTO_PATH), "-o", str(output), "--features", "1000"])
    assert code == 0
    written = cv2.imread(str(output), cv2.IMREAD_COLOR)
    assert written is not None
    reference = read_rgb(REFERENCE_PATH)
    assert written.shape[0] == reference.shape[0]
    assert written.shape[1] == reference.shape[1]


def test_cli_reports_failure(tmp_path: Path):
    output = tmp_path / "nope.png"
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((180, 180, 3), 240, np.uint8))
    code = run([str(REFERENCE_PATH), str(blank), "-o", str(output)])
    assert code == 1
    assert not output.exists()
