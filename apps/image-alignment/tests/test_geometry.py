from types import SimpleNamespace

import cv2
import numpy as np

from image_alignment.geometry import assess_homography, ratio_test


def _match(distance: float) -> SimpleNamespace:
    return SimpleNamespace(distance=distance)


def test_ratio_test_keeps_a_clear_nearest_neighbor():
    kept = ratio_test([[_match(10), _match(20)]], 0.75)
    assert len(kept) == 1
    assert kept[0].distance == 10


def test_ratio_test_drops_an_ambiguous_pair_and_keeps_a_perfect_tie():
    kept = ratio_test(
        [
            [_match(10), _match(12)],
            [_match(0), _match(0)],
            [_match(5)],
        ],
        0.75,
    )
    assert [item.distance for item in kept] == [0]


def test_identity_homography_is_usable():
    assert assess_homography(np.eye(3), (200, 100), (200, 100)) is None


def test_nan_and_zero_homographies_are_rejected():
    broken = np.eye(3)
    broken[1, 1] = np.nan
    assert assess_homography(broken, (200, 100), (200, 100)) is not None
    assert assess_homography(np.zeros((3, 3)), (200, 100), (200, 100)) is not None


def test_exploding_homography_is_rejected():
    scaled = np.diag([100.0, 100.0, 1.0])
    assert assess_homography(scaled, (200, 100), (200, 100)) is not None


def test_mild_perspective_is_accepted_and_a_bowtie_is_not():
    source = np.float32([[0, 0], [300, 0], [300, 200], [0, 200]])
    mild = np.float32([[10, 20], [280, 5], [290, 190], [0, 180]])
    bowtie = np.float32([[0, 0], [100, 0], [0, 100], [100, 100]])
    assert assess_homography(cv2.getPerspectiveTransform(source, mild), (300, 200), (300, 200)) is None
    small = np.float32([[0, 0], [100, 0], [100, 100], [0, 100]])
    assert assess_homography(cv2.getPerspectiveTransform(small, bowtie), (100, 100), (100, 100)) is not None
