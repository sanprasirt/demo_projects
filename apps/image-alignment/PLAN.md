# Plan

## Goal

One person opens a local page, loads a reference image and a photo of that same flat surface, and sees the photo aligned to the reference. Python and OpenCV detect keypoints, match them, estimate a homography, and warp the photo. The same function is available as a command. No GPU.

The owner switched this demo from a browser OpenCV.js build to Python. OpenCV.js 5 does not expose AKAZE or SIFT; `opencv-python` does.

## MVP

In:

- One pair at a time, on this machine.
- Upload or drag-drop both images in a local web UI. A bundled sample pair (an original poster and a skewed photo of it) loads on its own.
- One page that shows keypoints, ratio-test matches, RANSAC inliers and outliers, the warped photo, and a before/after comparison plus a difference view.
- Controls: detector (ORB, SIFT, AKAZE), matcher (BFMatcher or FLANN), feature cap, Lowe ratio, reprojection threshold, RANSAC or USAC_MAGSAC, optional ECC refinement.
- Stats: keypoint counts, match count, inlier count and ratio, runtime in milliseconds.
- A clear message when there are too few matches or the homography is degenerate.
- A note that a homography fits planar scenes (documents, posters, rotating-camera shots) and not 3D scenes with parallax.
- `uv sync`, then `uv run playground` and `uv run align ref.jpg photo.jpg -o out.png`.
- `uv run pytest` for the ratio test, the homography check, and alignment of the sample pair.

Out:

- Accounts, saved projects, or more than one user.
- A hosted upload service, or shipping images off the machine. The UI is a local process.
- XFeat, DISK, LightGlue, or any learned matcher.
- Video, a live camera, or more than two images.
- Bundle adjustment, multi-plane models, or parallax-aware warps.

## Tasks

1. Replace the JavaScript scaffold with a uv project (`pyproject.toml`, `uv.lock`, `.python-version`).
2. Generate an original sample poster and a perspective photo of it, and record that they are original.
3. Implement detect, ratio-test match, homography, optional ECC, and warp in an importable module, with a CLI.
4. Build one Gradio page for the five stages, the controls, the stats, and the failure state.
5. Test the ratio test, degeneracy checks, and the sample-pair warp.

## Stack

- uv: the owner asked for `uv sync` and `uv run`, with a pinned Python 3.12.
- `opencv-python` 4.14 (pinned below 5): ORB, SIFT, and AKAZE, plus `findHomography`, USAC, `warpPerspective`, and ECC. The 5.0 wheel does not export AKAZE. Confirmed against the installed package.
- NumPy: image arrays and the homography checks.
- Gradio: one local page with uploads, drag-drop, sliders, and image panes. A second frontend stack is unnecessary.
- pytest: the ratio test, the homography check, and the sample alignment. No UI snapshots.

## Deferred

- Advanced mode: the same pair through ORB, XFeat, and DISK+LightGlue on a Python GPU backend, compared on match count, inliers, and warp error.
- A git hook. `uv run pytest` is one command.
- Live camera, video files, and multi-plane alignment.
