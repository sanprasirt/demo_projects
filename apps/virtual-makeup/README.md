# Virtual makeup

Apply lipstick, blush, and eyeshadow to one front-facing face. The page runs locally, on CPU, with OpenCV masks and MediaPipe face landmarks.

The idea follows [Jayanth S's Virtual Makeup](https://github.com/Jayanths9/Virtual_Makeup) (live landmark makeup). That repository has no license, so this app is an independent implementation: lip and eye rings come from the published MediaPipe face-mesh contour, and the colour blend is a straightforward LAB mix.

## Run

Requires [Bun](https://bun.sh) and Python 3.11+.

```bash
cd apps/virtual-makeup
bun install && bun run dev
```

Open http://127.0.0.1:8000

The first start creates `.venv` and installs Python packages from `requirements.txt`. The face-landmarker model ships in `models/`. Set `PORT` to use another port.

MediaPipe’s wheel needs `libEGL`. If startup says `libEGL.so.1` is missing, install it (`sudo apt-get install -y libegl1` on Debian or Ubuntu).

```bash
bun run test
```

Tests cover landmark masks and the colour blend, not the web page.

## Use

The sample portrait loads on its own. Upload another front-facing photo, or start the camera and capture a frame. Pick a colour and an intensity for lipstick, blush, and eyeshadow, then apply. Live re-applies the current look to new camera frames.

The sample is a cropped CC0 portrait. See `samples/SOURCE.md`.
