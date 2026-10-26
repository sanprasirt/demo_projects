"""Critical checks for landmark masks and colour blending."""

from __future__ import annotations

import numpy as np

from makeup.blend import MakeupLook, RegionStyle, apply_regions, blend_region, parse_hex_color
from makeup.regions import (
    LIP_INNER,
    LIP_OUTER,
    LEFT_BROW_A,
    LEFT_BROW_B,
    LEFT_EYE,
    LEFT_EYE_UPPER,
    RIGHT_BROW_A,
    RIGHT_BROW_B,
    RIGHT_EYE,
    RIGHT_EYE_UPPER,
    blush_mask,
    cheek_centers,
    eyeshadow_mask,
    lip_mask,
)


def _blank() -> np.ndarray:
    return np.zeros((478, 2), dtype=np.float32)


def _ring(points: np.ndarray, indices: tuple[int, ...], cx: float, cy: float, rx: float, ry: float) -> None:
    angles = np.linspace(0, 2 * np.pi, len(indices), endpoint=False)
    for index, angle in zip(indices, angles, strict=True):
        points[index, 0] = cx + rx * np.cos(angle)
        points[index, 1] = cy + ry * np.sin(angle)


def _along(points: np.ndarray, indices: tuple[int, ...], x0: float, x1: float, y: float) -> None:
    xs = np.linspace(x0, x1, len(indices))
    for index, x in zip(indices, xs, strict=True):
        points[index, 0] = x
        points[index, 1] = y


def test_lip_mask_spares_the_mouth_opening():
    points = _blank()
    _ring(points, LIP_OUTER, 150, 180, 46, 22)
    _ring(points, LIP_INNER, 150, 180, 24, 10)
    mask = lip_mask(points, 300, 320, feather_px=1)

    assert mask[180, 150] == 0
    outer = points[LIP_OUTER[0]]
    inner = points[LIP_INNER[0]]
    band = np.round((outer + inner) / 2).astype(int)
    assert mask[band[1], band[0]] > 100
    assert mask[10, 10] == 0


def test_eyeshadow_sits_between_lower_brow_and_lid():
    points = _blank()
    _along(points, RIGHT_BROW_B, 40, 120, 50)
    _along(points, RIGHT_BROW_A, 40, 120, 90)
    _along(points, RIGHT_EYE_UPPER, 40, 120, 130)
    _along(points, (133, 155, 154, 153, 145, 144, 163, 7), 40, 120, 165)
    _along(points, LEFT_BROW_B, 260, 340, 50)
    _along(points, LEFT_BROW_A, 260, 340, 90)
    _along(points, LEFT_EYE_UPPER, 260, 340, 130)
    _along(points, (362, 382, 381, 380, 374, 373, 390, 249), 260, 340, 165)

    mask = eyeshadow_mask(points, 420, 360, feather_px=1)
    assert mask[108, 80] > 100
    assert mask[65, 80] == 0
    assert mask[150, 80] == 0
    assert mask[20, 20] == 0


def test_blush_centers_fall_on_the_cheeks():
    points = _blank()
    points[1] = (200, 180)
    points[33] = (120, 140)
    points[263] = (280, 140)
    points[61] = (140, 240)
    points[291] = (260, 240)
    points[234] = (50, 200)
    points[454] = (350, 200)
    _ring(points, LIP_OUTER, 200, 300, 16, 8)
    _ring(points, RIGHT_EYE, 120, 140, 12, 8)
    _ring(points, LEFT_EYE, 280, 140, 12, 8)

    subject_right, subject_left = cheek_centers(points)
    assert subject_right[0] < points[1, 0] < subject_left[0]

    mask = blush_mask(points, 400, 400, feather_px=4)
    rx, ry = np.round(subject_right).astype(int)
    lx, ly = np.round(subject_left).astype(int)
    assert mask[ry, rx] > 100
    assert mask[ly, lx] > 100
    assert mask[20, 200] == 0


def test_zero_intensity_matches_the_photo():
    image = np.full((30, 30, 3), 140, np.uint8)
    image[5, 5] = (10, 20, 30)
    mask = np.full((30, 30), 255, np.uint8)
    look = MakeupLook(
        lipstick=RegionStyle((0, 0, 255), 0.0, 1.0),
        blush=RegionStyle((0, 255, 0), 0.0, 1.0),
        eyeshadow=RegionStyle((255, 0, 0), 0.0, 1.0),
    )
    out = apply_regions(image, {"lipstick": mask, "blush": mask, "eyeshadow": mask}, look)
    assert np.array_equal(out, image)
    assert out is not image


def test_full_intensity_moves_a_neutral_pixel_toward_red():
    image = np.full((20, 20, 3), 180, np.uint8)
    mask = np.full((20, 20), 255, np.uint8)
    out = blend_region(image, mask, (30, 40, 210), 1.0, lightness=0.2)
    pixel = out[10, 10]
    assert pixel[2] > pixel[0]
    assert not np.array_equal(out, image)


def test_parse_hex_color():
    assert parse_hex_color("#C81D3A") == (0x3A, 0x1D, 0xC8)
    assert parse_hex_color("00ff00") == (0, 255, 0)
    try:
        parse_hex_color("red")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
