"""Generate the original sample poster and a skewed photo of it.

Run from the app directory:

    uv run python scripts/make_samples.py

The poster is an abstract print: filled shapes in irregular places, so the
corners are unique. A regular grid or a checkerboard makes ORB, SIFT, and
AKAZE match the wrong copies of the same pattern.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

INK = (28, 27, 25)
PAPER = (245, 240, 230)
WHITE = (255, 252, 247)
SEAL = (168, 42, 36)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    poster = draw_poster()
    photo = photograph(poster)
    cv2.imwrite(str(OUT / "reference.png"), cv2.cvtColor(poster, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(OUT / "photo.png"), cv2.cvtColor(photo, cv2.COLOR_RGB2BGR))
    print(f"wrote {OUT / 'reference.png'} and {OUT / 'photo.png'}")


def draw_poster() -> np.ndarray:
    height, width = 960, 720
    image = np.full((height, width, 3), PAPER, np.uint8)
    ys, xs = np.mgrid[0:height, 0:width]
    field = np.sin(xs / 37.0) + np.sin(ys / 29.0) + np.sin((xs + ys) / 53.0)
    image = np.clip(image.astype(np.float32) + field[:, :, None] * 7, 0, 255).astype(np.uint8)

    rng = np.random.default_rng(4)
    for index in range(90):
        color = tuple(int(channel) for channel in rng.integers(12, 70, size=3))
        x = int(rng.integers(36, width - 36))
        y = int(rng.integers(170, height - 70))
        kind = index % 4
        if kind == 0:
            cv2.circle(image, (x, y), int(rng.integers(14, 42)), color, -1, lineType=cv2.LINE_AA)
        elif kind == 1:
            box_w = int(rng.integers(22, 74))
            box_h = int(rng.integers(16, 52))
            cv2.rectangle(
                image,
                (x, y),
                (min(width - 24, x + box_w), min(height - 24, y + box_h)),
                color,
                -1,
            )
        elif kind == 2:
            offsets = rng.integers(-34, 35, size=(3, 2))
            triangle = (np.array([x, y]) + offsets).astype(np.int32)
            cv2.fillConvexPoly(image, triangle.reshape(-1, 1, 2), color)
        else:
            end = (int(rng.integers(36, width - 36)), int(rng.integers(170, height - 70)))
            cv2.line(image, (x, y), end, color, int(rng.integers(3, 7)), lineType=cv2.LINE_AA)

    cv2.rectangle(image, (24, 24), (width - 25, 158), PAPER, -1)
    cv2.rectangle(image, (18, 18), (width - 19, height - 19), INK, 4)
    cv2.rectangle(image, (30, 30), (width - 31, height - 31), INK, 1)
    cv2.putText(image, "CEDAR & QUAY", (44, 84), cv2.FONT_HERSHEY_DUPLEX, 1.25, INK, 2, cv2.LINE_AA)
    cv2.putText(
        image,
        "NIGHT MARKET    PLATE 04",
        (46, 122),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (96, 72, 52),
        1,
        cv2.LINE_AA,
    )
    cv2.line(image, (44, 142), (width - 44, 142), INK, 1)
    cv2.putText(image, "PLANAR TARGET", (44, height - 58), cv2.FONT_HERSHEY_SIMPLEX, 0.5, INK, 1, cv2.LINE_AA)
    cv2.putText(
        image,
        "ONE PLANE  -  NO PARALLAX",
        (44, height - 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (96, 72, 52),
        1,
        cv2.LINE_AA,
    )
    cv2.circle(image, (width - 78, height - 58), 28, SEAL, -1, lineType=cv2.LINE_AA)
    cv2.circle(image, (width - 78, height - 58), 20, WHITE, 2, lineType=cv2.LINE_AA)
    cv2.putText(image, "NQ", (width - 94, height - 50), cv2.FONT_HERSHEY_DUPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
    return image


def photograph(poster: np.ndarray) -> np.ndarray:
    photo_w, photo_h = 960, 680
    desk = _desk(photo_h, photo_w)
    source = np.float32(
        [[0, 0], [poster.shape[1] - 1, 0], [poster.shape[1] - 1, poster.shape[0] - 1], [0, poster.shape[0] - 1]]
    )
    destination = np.float32([[80, 46], [890, 96], [840, 624], [48, 560]])
    homography = cv2.getPerspectiveTransform(source, destination)

    shadow = np.zeros_like(desk)
    shifted = np.round(destination + np.array([14, 16], dtype=np.float32)).astype(np.int32)
    cv2.fillConvexPoly(shadow, shifted.reshape(-1, 1, 2), (42, 38, 34))
    shadow = cv2.GaussianBlur(shadow, (31, 31), 0)
    desk = np.clip(desk.astype(np.int16) - shadow.astype(np.int16) // 2, 0, 255).astype(np.uint8)

    warped = cv2.warpPerspective(poster, homography, (photo_w, photo_h))
    mask = cv2.warpPerspective(
        np.full(poster.shape[:2], 255, np.uint8),
        homography,
        (photo_w, photo_h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    photo = desk.copy()
    region = mask > 0
    photo[region] = (warped.astype(np.int16) * 97 // 100)[region]
    rng = np.random.default_rng(7)
    noise = rng.integers(-5, 6, photo.shape, dtype=np.int16)
    return np.clip(photo.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _desk(height: int, width: int) -> np.ndarray:
    ramp = np.linspace(102, 124, height, dtype=np.float32)[:, None]
    desk = np.empty((height, width, 3), np.float32)
    desk[:, :, 0] = ramp - 10
    desk[:, :, 1] = ramp - 4
    desk[:, :, 2] = ramp + 4
    return np.clip(desk, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    main()
