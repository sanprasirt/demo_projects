"""Paths and loaders for the bundled sample pair."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

def samples_dir() -> Path:
    packaged = Path(__file__).resolve().parents[2] / "samples"
    if (packaged / "reference.png").exists():
        return packaged
    local = Path.cwd() / "samples"
    if (local / "reference.png").exists():
        return local
    return packaged


def sample_paths() -> tuple[Path, Path]:
    directory = samples_dir()
    return directory / "reference.png", directory / "photo.png"


def read_rgb(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Cannot read image: {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def load_sample_images() -> tuple[np.ndarray, np.ndarray]:
    reference_path, photo_path = sample_paths()
    return read_rgb(reference_path), read_rgb(photo_path)
