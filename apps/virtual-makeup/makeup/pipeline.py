"""Detect one face and paint a makeup look. CPU only."""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from makeup.blend import MakeupLook, RegionStyle, apply_regions, parse_hex_color
from makeup.regions import build_masks

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "face_landmarker.task"
MAX_SIDE = 1024

_landmarker = None
_lock = threading.Lock()


class NoFaceError(Exception):
    """Raised when the landmarker finds no face."""


def load_landmarker():
    global _landmarker
    with _lock:
        if _landmarker is None:
            if not MODEL_PATH.is_file():
                raise FileNotFoundError(
                    f"Missing {MODEL_PATH.name}. Run bun run dev so it can be downloaded."
                )
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(MODEL_PATH),
                    delegate=mp.tasks.BaseOptions.Delegate.CPU,
                ),
                num_faces=1,
            )
            _landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
    return _landmarker


def limit_size(image_bgr: np.ndarray, max_side: int = MAX_SIDE) -> np.ndarray:
    height, width = image_bgr.shape[:2]
    scale = max_side / max(height, width)
    if scale >= 1:
        return image_bgr
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(image_bgr, size, interpolation=cv2.INTER_AREA)


def detect_points(image_bgr: np.ndarray) -> np.ndarray:
    """Pixel landmarks for the first face. Shape ``(N, 2)``."""
    landmarker = load_landmarker()
    rgb = np.ascontiguousarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    with _lock:
        result = landmarker.detect(mp_image)
    if not result.face_landmarks:
        raise NoFaceError("No face found. Use a front-facing photo with the face clearly visible.")
    height, width = image_bgr.shape[:2]
    landmarks = result.face_landmarks[0]
    return np.array([(lm.x * width, lm.y * height) for lm in landmarks], dtype=np.float32)


def look_from_hex(
    lipstick_color: str,
    lipstick_intensity: float,
    blush_color: str,
    blush_intensity: float,
    eyeshadow_color: str,
    eyeshadow_intensity: float,
) -> MakeupLook:
    return MakeupLook(
        lipstick=RegionStyle(parse_hex_color(lipstick_color), lipstick_intensity, lightness=0.40),
        blush=RegionStyle(parse_hex_color(blush_color), blush_intensity, lightness=0.10),
        eyeshadow=RegionStyle(parse_hex_color(eyeshadow_color), eyeshadow_intensity, lightness=0.28),
    )


def apply_image(image_bgr: np.ndarray, look: MakeupLook) -> np.ndarray:
    image = limit_size(image_bgr)
    points = detect_points(image)
    masks = build_masks(points, image.shape[1], image.shape[0])
    return apply_regions(image, masks, look)
