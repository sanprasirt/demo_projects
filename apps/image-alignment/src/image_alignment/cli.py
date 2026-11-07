"""Command line: uv run align reference.jpg photo.jpg -o aligned.png"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

from image_alignment.pipeline import DETECTORS, MATCHERS, align_images
from image_alignment.samples import read_rgb


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Align a photo of a planar scene to a reference image."
    )
    parser.add_argument("reference", type=Path, help="Reference image, the plane to match.")
    parser.add_argument("photo", type=Path, help="Photo of that same plane.")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Where to write the warped photo.")
    parser.add_argument("--detector", choices=DETECTORS, default="ORB")
    parser.add_argument("--matcher", choices=MATCHERS, default="BFMatcher")
    parser.add_argument("--features", type=int, default=1500, help="Maximum keypoints per image.")
    parser.add_argument("--ratio", type=float, default=0.75, help="Lowe ratio test threshold.")
    parser.add_argument("--ransac", type=float, default=3.0, help="Reprojection threshold in pixels.")
    parser.add_argument("--method", choices=("RANSAC", "USAC_MAGSAC"), default="RANSAC")
    parser.add_argument("--ecc", action="store_true", help="Refine the homography with ECC.")
    parser.add_argument("--max-side", type=int, default=1200, help="Resize the long side before matching. 0 keeps the original size.")
    parser.add_argument("--diff", type=Path, help="Also write the boosted overlap difference.")
    args = parser.parse_args(argv)

    try:
        reference = read_rgb(args.reference)
        photo = read_rgb(args.photo)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result = align_images(
        reference,
        photo,
        detector=args.detector,
        matcher=args.matcher,
        max_features=args.features,
        ratio=args.ratio,
        ransac_threshold=args.ransac,
        method=args.method,
        ecc=args.ecc,
        max_side=args.max_side,
    )
    if not result.ok or result.warped is None:
        print(f"error: {result.message}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = cv2.imwrite(str(args.output), cv2.cvtColor(result.warped, cv2.COLOR_RGB2BGR))
    if not written:
        print(f"error: could not write {args.output}", file=sys.stderr)
        return 1
    if args.diff is not None and result.difference is not None:
        args.diff.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.diff), cv2.cvtColor(result.difference, cv2.COLOR_RGB2BGR))

    print(
        f"{result.inlier_count}/{result.match_count} inliers "
        f"({result.inlier_ratio:.1%}) in {result.runtime_ms:.0f} ms -> {args.output}"
    )
    return 0


def main() -> None:
    sys.exit(run())
