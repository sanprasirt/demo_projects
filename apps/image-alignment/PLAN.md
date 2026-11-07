# Plan

## Goal

One person opens a local page, loads a reference image and a photo of that same flat surface, and sees the photo aligned to the reference. OpenCV.js (WASM) detects keypoints, matches them, estimates a homography with RANSAC, and warps the photo. No GPU and no server upload.

## MVP

In:

- One pair at a time, in the browser on this machine.
- Upload or drag-drop both images. A bundled sample pair (an original poster and a skewed photo of it) loads on its own.
- One page that shows keypoints, ratio-test matches, RANSAC inliers and outliers, the warped photo, and a before/after slider plus a difference view.
- Controls: detector (ORB, plus AKAZE or BRISK only after the chosen OpenCV.js build is checked and actually exposes them), feature cap, Lowe ratio, RANSAC reprojection threshold.
- Stats: keypoint counts, match count, inlier count and ratio, runtime in milliseconds.
- A clear failure message when there are too few matches or the homography is degenerate.
- A short note that a homography fits planar scenes (documents, posters, rotating-camera shots) and not 3D scenes with parallax.
- `bun install && bun run dev` from `apps/image-alignment/`.
- Tests for the ratio test, the homography sanity check, and alignment of the sample pair.

Out:

- Accounts, saved projects, or more than one user.
- A server, image upload API, or GPU inference.
- XFeat, DISK, LightGlue, or any learned matcher.
- Video, live camera, or more than two images.
- Bundle adjustment, multi-plane models, or parallax-aware warps.

## Tasks

1. Scaffold a Vite React app with the shadcn/ui minimalist preset and `bunfig.toml` before the first install.
2. Generate an original sample poster and a perspective photo of it, and record that they are original.
3. Run ORB (and any other verified detector) in OpenCV.js: detect, ratio-test match, RANSAC homography, warp.
4. Draw the five stages on one page, including the failure state, and show the stats.
5. Test the ratio test, degeneracy checks, and the sample-pair warp.

## Stack

- Bun: the monorepo starts every demo with `bun install && bun run dev`.
- Vite, React, and TypeScript (`shadcn init --template vite`): one page, no server.
- shadcn/ui preset `baKhJQ` (nova, zinc, neutral, Geist, default radius, Lucide): the minimalist preset for a JavaScript UI. Zinc surfaces, a neutral accent, and compact nova controls.
- OpenCV.js via `@techstark/opencv-js`: official features2d and calib3d bindings in WASM, including `findHomography` and `warpPerspective`. Detectors are read off the loaded build; nothing is offered that the build does not expose.
- A Web Worker for detection and the warp, so the page stays responsive. Drawing stays on the main thread.
- `bun test` for the ratio test, homography checks, and the sample alignment. No UI snapshots.

## Deferred

- Advanced mode: the same pair through ORB, XFeat, and DISK+LightGlue on a Python GPU backend, compared on match count, inliers, and warp error.
- A git hook. `bun test` is one command; a repo-wide hook is outside this app.
- Live camera, video files, and multi-plane alignment.
