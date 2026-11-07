# Image Alignment Playground

Align a photo of a flat surface to a reference image. The page detects keypoints, draws the matches, separates RANSAC inliers from outliers, warps the photo with the homography, and compares the result with the reference.

A homography fits a plane: a document, a poster, or a shot where the camera rotates in front of a flat wall. It does not explain a 3D scene with parallax. Points at different depths move differently, and one 3×3 matrix cannot follow all of them.

## Run

Requires [uv](https://docs.astral.sh/uv/) and the Python in `.python-version` (3.12).

```bash
cd apps/image-alignment
uv sync
uv run playground
```

Open http://127.0.0.1:7860

The sample poster and a skewed photo of it load on their own. Drop or upload another pair to replace them. The images stay in this process; the page does not upload them to a hosted service.

The same alignment is a command:

```bash
uv run align samples/reference.png samples/photo.png -o aligned.png
```

```bash
uv run pytest
```

Tests cover the ratio test, the homography checks, and alignment of the sample pair.

## Use

ORB, SIFT, and AKAZE are the detectors in the pinned `opencv-python` 4.14 build. The OpenCV 5 wheel does not export AKAZE, so this app stays on 4.x. Match with BFMatcher or FLANN. The ratio slider is Lowe's test. The reprojection slider is the RANSAC (or USAC_MAGSAC) pixel threshold. ECC, when checked, tries to refine the homography and keeps the RANSAC result if that refinement is unstable.

The stats are keypoint counts, match count, inlier count and ratio, overlap error, and runtime in milliseconds. If there are too few matches, or the homography is degenerate, the page says so and does not show a warp.

## Architecture

`image_alignment.pipeline.align_images` is the whole alignment. The Gradio page and the `align` command both call it.

1. Resize so the long side is at most 1200 px, then convert to gray.
2. Detect and describe with ORB, SIFT, or AKAZE. ORB and SIFT take the feature cap directly. AKAZE uses `max_points` when this OpenCV build has it, and the cap is applied again by response.
3. `knnMatch` with BFMatcher (Hamming for binary descriptors, L2 for SIFT) or FLANN (LSH for binary, a KD-tree for SIFT), then Lowe's ratio test.
4. `findHomography` from the photo points to the reference points, with RANSAC or USAC_MAGSAC.
5. Optional `findTransformECC` in homography mode, starting from that matrix.
6. `warpPerspective` into the reference frame. The difference view is the absolute error on the overlap, boosted 3×.

`image_alignment.geometry` holds the ratio test and the checks that reject a non-finite, flipped, folded, or exploded homography. Those functions are what the tests lock. Drawings live in `image_alignment.draw`.

## Samples

`samples/reference.png` and `samples/photo.png` are original images from `scripts/make_samples.py`. See `samples/SOURCE.md`.

## Next steps

An Advanced mode could run this same pair through ORB (this page), XFeat, and DISK+LightGlue on a Python GPU backend, and compare match count, inlier ratio, and warp error side by side. That mode is not built here.
