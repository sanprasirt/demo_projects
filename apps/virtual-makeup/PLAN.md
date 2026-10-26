# Plan

## Goal

A single person can open one local page, load a front-facing face photo (or a webcam still), and see lipstick, blush, and eyeshadow in colours and intensities they choose. Landmarks come from MediaPipe. Masks and blending stay in OpenCV. CPU only.

## MVP

In:

- One face at a time, in the browser on this machine.
- Upload a photo, or capture a webcam frame (optional live re-apply).
- Lipstick, blush, and eyeshadow, each with a colour and an intensity.
- A CC0 sample portrait so the page works with no upload.
- `bun install && bun run dev` from `apps/virtual-makeup/`.
- Tests for the landmark-to-mask and blend math only.

Out:

- Accounts, saved looks, sharing, or more than one user.
- Video-file upload, 30 fps streaming, or a phone app.
- Eyeliner, eyebrows, skin smoothing, background blur, or shade matching.
- GPU inference.

## Tasks

1. Mask lipstick (outer lip minus the mouth), blush (cheek ellipses), and eyeshadow (lower brow to lid) from landmark pixels, with tests.
2. Blend each mask in LAB so colour changes and skin texture stays.
3. Run the MediaPipe face landmarker on CPU and serve one FastAPI page.
4. Add the sample photo, `bunfig.toml`, and `bun run dev`.

## Stack

- Bun scripts: the monorepo starts every demo with `bun run dev`.
- Python, FastAPI, and uvicorn: one process serves the page and the landmark API. A React scaffold would be a second app for a single form.
- `mediapipe` Face Landmarker plus `opencv` (pulled in by MediaPipe): CPU landmarks and the mask blend, which is the whole demo.
- pytest: the mask and blend functions are the only logic worth locking.
- Plain CSS using the neutral minimalist tokens (zinc surfaces, 8px radius, system font): the shadcn/ui minimalist preset targets a React app, and this page is one form.

## Deferred

- shadcn/ui React preset, if a later demo needs a component kit.
- A git hook that runs `bun run test`. The check is one command; a repo-wide hook is outside this app.
- Eyeliner, brows, skin smoothing, background blur, preset files, and multi-face.
