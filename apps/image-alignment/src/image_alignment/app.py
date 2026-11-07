"""Local playground: uv run playground."""

from __future__ import annotations

import argparse
import os

import gradio as gr

from image_alignment.pipeline import align_images
from image_alignment.pipeline_types import AlignmentResult
from image_alignment.samples import load_sample_images

PLANAR_NOTE = (
    "A homography fits a plane: a document, a poster, or a camera rotating in front of a flat wall. "
    "It does not explain a 3D scene with parallax."
)


def _present(result: AlignmentResult):
    headline = "Aligned" if result.ok else "Not aligned"
    status = f"**{headline}.** {result.message}"
    ratio = "—" if result.match_count == 0 else f"{result.inlier_ratio * 100:.1f}%"
    overlap = "—" if result.overlap_mae is None else f"{result.overlap_mae:.1f}"
    stats = "\n".join(
        [
            f"- Reference keypoints: **{result.keypoints_reference}**",
            f"- Photo keypoints: **{result.keypoints_photo}**",
            f"- Matches: **{result.match_count}**",
            f"- Inliers: **{result.inlier_count}** ({ratio})",
            f"- Overlap error: **{overlap}** gray levels",
            f"- Runtime: **{result.runtime_ms:.0f} ms**",
            f"- {result.detector} · {result.matcher} · {result.method}"
            + (" · ECC" if result.ecc_applied else ""),
        ]
    )
    slider = None
    if result.ok and result.reference is not None and result.warped is not None:
        slider = (result.reference, result.warped)
    return (
        status,
        stats,
        result.keypoints_reference_image,
        result.keypoints_photo_image,
        result.matches_image,
        result.inliers_image,
        result.warped,
        slider,
        result.difference,
    )


def _empty(message: str):
    blank = _present(
        AlignmentResult(
            ok=False,
            message=message,
            keypoints_reference=0,
            keypoints_photo=0,
            match_count=0,
            inlier_count=0,
            inlier_ratio=0.0,
            runtime_ms=0.0,
            overlap_mae=None,
            detector="—",
            matcher="—",
            method="—",
            ecc_applied=False,
            homography=None,
            reference=None,
            keypoints_reference_image=None,
            keypoints_photo_image=None,
            matches_image=None,
            inliers_image=None,
            warped=None,
            difference=None,
        )
    )
    return blank


def run_alignment(reference, photo, detector, matcher, features, ratio, ransac, method, ecc):
    if reference is None or photo is None:
        return _empty("Load a reference image and a photo. Drop files onto the panels, or load the sample pair.")
    result = align_images(
        reference,
        photo,
        detector=detector,
        matcher=matcher,
        max_features=int(features),
        ratio=float(ratio),
        ransac_threshold=float(ransac),
        method=method,
        ecc=bool(ecc),
    )
    return _present(result)


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Image Alignment Playground", analytics_enabled=False) as demo:
        gr.Markdown(
            f"""
# Image Alignment Playground

Match keypoints, separate inliers from outliers, and warp a photo onto a reference.

{PLANAR_NOTE}
"""
        )
        with gr.Row():
            with gr.Column(scale=4):
                reference = gr.Image(label="Reference — upload or drop", type="numpy", format="png")
                photo = gr.Image(label="Photo — upload or drop", type="numpy", format="png")
                reference_state = gr.State()
                photo_state = gr.State()
                with gr.Row():
                    sample_button = gr.Button("Load sample pair")
                    align_button = gr.Button("Align", variant="primary")
                detector = gr.Radio(["ORB", "SIFT", "AKAZE"], value="ORB", label="Detector")
                matcher = gr.Radio(["BFMatcher", "FLANN"], value="BFMatcher", label="Matcher")
                features = gr.Slider(200, 4000, value=1500, step=100, label="Features")
                ratio = gr.Slider(0.40, 0.95, value=0.75, step=0.01, label="Ratio test")
                ransac = gr.Slider(1.0, 10.0, value=3.0, step=0.5, label="RANSAC reprojection (px)")
                method = gr.Radio(["RANSAC", "USAC_MAGSAC"], value="RANSAC", label="Estimator")
                ecc = gr.Checkbox(value=False, label="Refine with ECC")
                stats = gr.Markdown()
            with gr.Column(scale=8):
                status = gr.Markdown()
                gr.Markdown("### 1. Keypoints")
                with gr.Row():
                    keypoints_reference = gr.Image(label="Reference keypoints", type="numpy", format="png")
                    keypoints_photo = gr.Image(label="Photo keypoints", type="numpy", format="png")
                gr.Markdown("### 2. Matches after the ratio test")
                matches = gr.Image(label="Match lines", type="numpy", format="png")
                gr.Markdown("### 3. Inliers and outliers\n\nGreen lines survived RANSAC. Red lines did not.")
                inliers = gr.Image(label="Inliers and outliers", type="numpy", format="png")
                gr.Markdown("### 4. Warped photo")
                warped = gr.Image(label="Photo warped onto the reference", type="numpy", format="png")
                gr.Markdown("### 5. Compare\n\nDrag the slider. The difference is the absolute error on the overlap, boosted 3×. Gray is outside the photo.")
                compare = gr.ImageSlider(label="Reference versus aligned photo", format="png")
                difference = gr.Image(label="Difference", type="numpy", format="png")

        controls = [detector, matcher, features, ratio, ransac, method, ecc]
        outputs = [
            status,
            stats,
            keypoints_reference,
            keypoints_photo,
            matches,
            inliers,
            warped,
            compare,
            difference,
        ]

        def show_pair(reference_image, photo_image, detector, matcher, features, ratio, ransac, method, ecc):
            presented = run_alignment(
                reference_image,
                photo_image,
                detector,
                matcher,
                features,
                ratio,
                ransac,
                method,
                ecc,
            )
            return (reference_image, photo_image, reference_image, photo_image, *presented)

        def startup():
            reference_image, photo_image = load_sample_images()
            return show_pair(reference_image, photo_image, "ORB", "BFMatcher", 1500, 0.75, 3.0, "RANSAC", False)

        def align_stored(reference_image, photo_image, detector, matcher, features, ratio, ransac, method, ecc):
            return run_alignment(
                reference_image,
                photo_image,
                detector,
                matcher,
                features,
                ratio,
                ransac,
                method,
                ecc,
            )

        def load_sample(detector, matcher, features, ratio, ransac, method, ecc):
            reference_image, photo_image = load_sample_images()
            return show_pair(
                reference_image, photo_image, detector, matcher, features, ratio, ransac, method, ecc
            )

        pair_outputs = [reference, photo, reference_state, photo_state, *outputs]
        demo.load(startup, outputs=pair_outputs)
        sample_button.click(load_sample, inputs=controls, outputs=pair_outputs)
        align_button.click(align_stored, inputs=[reference_state, photo_state, *controls], outputs=outputs)
        reference.upload(show_pair, inputs=[reference, photo_state, *controls], outputs=pair_outputs)
        photo.upload(show_pair, inputs=[reference_state, photo, *controls], outputs=pair_outputs)
        for choice in (detector, matcher, method, ecc):
            choice.change(align_stored, inputs=[reference_state, photo_state, *controls], outputs=outputs)
        for slider in (features, ratio, ransac):
            slider.release(align_stored, inputs=[reference_state, photo_state, *controls], outputs=outputs)
    return demo


def main() -> None:
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    parser = argparse.ArgumentParser(description="Open the image alignment playground.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "7860")))
    args = parser.parse_args()
    theme = gr.themes.Base(primary_hue="zinc", neutral_hue="zinc")
    build_demo().launch(server_name=args.host, server_port=args.port, share=False, theme=theme)
