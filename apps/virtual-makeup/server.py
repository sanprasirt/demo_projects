"""Local web UI for virtual makeup."""

from __future__ import annotations

import io
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from makeup.pipeline import MAX_SIDE, NoFaceError, apply_image, load_landmarker, look_from_hex

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SAMPLES = ROOT / "samples"
MAX_BYTES = 12 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_landmarker()
    yield


app = FastAPI(title="Virtual makeup", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")


@app.exception_handler(NoFaceError)
async def no_face_handler(_request, exc: NoFaceError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


def decode_image(raw: bytes) -> np.ndarray:
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image is larger than 12 MB")
    try:
        pil = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        pil.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Could not read that image") from exc
    rgb = np.asarray(pil)
    if rgb.size == 0:
        raise HTTPException(status_code=400, detail="Could not read that image")
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


@app.post("/api/apply")
async def apply_makeup(
    image: UploadFile = File(...),
    lipstick_color: str = Form("#c81d3a"),
    lipstick_intensity: float = Form(0.78),
    blush_color: str = Form("#f07a90"),
    blush_intensity: float = Form(0.72),
    eyeshadow_color: str = Form("#7a4e86"),
    eyeshadow_intensity: float = Form(0.70),
):
    raw = await image.read()
    bgr = decode_image(raw)
    try:
        look = look_from_hex(
            lipstick_color,
            lipstick_intensity,
            blush_color,
            blush_intensity,
            eyeshadow_color,
            eyeshadow_intensity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    painted = apply_image(bgr, look)
    ok, encoded = cv2.imencode(".jpg", painted, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise HTTPException(status_code=500, detail="Could not encode the result")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")
