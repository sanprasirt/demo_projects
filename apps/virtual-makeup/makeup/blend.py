"""Blend a solid colour into a mask while keeping skin texture in the lightness channel."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class RegionStyle:
    color_bgr: tuple[int, int, int]
    intensity: float
    lightness: float = 0.25


@dataclass(frozen=True)
class MakeupLook:
    lipstick: RegionStyle
    blush: RegionStyle
    eyeshadow: RegionStyle


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """Return BGR from a ``#RRGGBB`` string."""
    text = value.strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6 or any(char not in "0123456789abcdefABCDEF" for char in text):
        raise ValueError("colour must be #RRGGBB")
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    return (blue, green, red)


def _clamp_unit(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(number):
        return 0.0
    return min(1.0, max(0.0, number))


def blend_region(
    image_bgr: np.ndarray,
    mask: np.ndarray,
    color_bgr: tuple[int, int, int],
    intensity: float,
    lightness: float = 0.25,
) -> np.ndarray:
    """Move LAB a/b toward ``color_bgr`` where ``mask`` is bright.

    Lightness stays close to the photo so pores and highlights remain.
    ``lightness`` is how far L may move toward the pigment (0 keeps L).
    """
    strength = _clamp_unit(intensity)
    if strength <= 0.0 or mask.max() == 0:
        return image_bgr

    color = np.uint8([[list(color_bgr)]])
    color_lab = cv2.cvtColor(color, cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
    image_lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    alpha = (mask.astype(np.float32) / 255.0) * strength
    light = alpha * _clamp_unit(lightness)

    mixed = image_lab.copy()
    mixed[:, :, 0] = image_lab[:, :, 0] * (1.0 - light) + color_lab[0] * light
    mixed[:, :, 1] = image_lab[:, :, 1] * (1.0 - alpha) + color_lab[1] * alpha
    mixed[:, :, 2] = image_lab[:, :, 2] * (1.0 - alpha) + color_lab[2] * alpha
    return cv2.cvtColor(np.clip(mixed, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def apply_regions(image_bgr: np.ndarray, masks: dict[str, np.ndarray], look: MakeupLook) -> np.ndarray:
    """Paint eyeshadow, then blush, then lipstick so the lips stay on top."""
    out = image_bgr.copy()
    out = blend_region(
        out, masks["eyeshadow"], look.eyeshadow.color_bgr, look.eyeshadow.intensity, look.eyeshadow.lightness
    )
    out = blend_region(out, masks["blush"], look.blush.color_bgr, look.blush.intensity, look.blush.lightness)
    out = blend_region(
        out, masks["lipstick"], look.lipstick.color_bgr, look.lipstick.intensity, look.lipstick.lightness
    )
    return out
