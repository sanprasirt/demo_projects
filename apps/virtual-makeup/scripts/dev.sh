#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

if ! .venv/bin/python -c "import fastapi, mediapipe, cv2, PIL" >/dev/null 2>&1; then
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
fi

MODEL="$ROOT/models/face_landmarker.task"
if [[ ! -f "$MODEL" ]]; then
  mkdir -p "$ROOT/models"
  curl -fsSL -o "$MODEL" \
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
fi

if ! ldconfig -p 2>/dev/null | grep -q 'libEGL.so'; then
  echo "MediaPipe needs libEGL. On Debian/Ubuntu: sudo apt-get install -y libegl1" >&2
fi

export GLOG_minloglevel="${GLOG_minloglevel:-2}"
export TF_CPP_MIN_LOG_LEVEL="${TF_CPP_MIN_LOG_LEVEL:-2}"
PORT="${PORT:-8000}"
exec .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port "$PORT"
