const PRESETS = {
  classic: {
    lipstick: ["#c81d3a", 78],
    blush: ["#f07a90", 72],
    eyeshadow: ["#7a4e86", 70],
  },
  berry: {
    lipstick: ["#8e2452", 82],
    blush: ["#d9899c", 50],
    eyeshadow: ["#5c3a6e", 60],
  },
  rose: {
    lipstick: ["#c46a74", 70],
    blush: ["#f0b7aa", 55],
    eyeshadow: ["#c4a484", 45],
  },
};

const before = document.querySelector("#before");
const after = document.querySelector("#after");
const afterEmpty = document.querySelector("#after-empty");
const status = document.querySelector("#status");
const applyButton = document.querySelector("#apply");
const photoInput = document.querySelector("#photo");
const preview = document.querySelector("#preview");
const cameraActions = document.querySelector("#camera-actions");
const cameraButton = document.querySelector("#camera");
const liveInput = document.querySelector("#live");

const state = { file: null, stream: null, busy: false, liveTimer: null };

function setStatus(text) {
  status.textContent = text;
}

function showBefore(file) {
  state.file = file;
  before.src = URL.createObjectURL(file);
  after.hidden = true;
  afterEmpty.hidden = false;
}

function bindRange(inputId, outputId) {
  const input = document.querySelector(inputId);
  const output = document.querySelector(outputId);
  const sync = () => {
    output.textContent = `${input.value}%`;
  };
  input.addEventListener("input", sync);
  sync();
}

function readLook() {
  return {
    lipstick_color: document.querySelector("#lipstick-color").value,
    lipstick_intensity: Number(document.querySelector("#lipstick-intensity").value) / 100,
    blush_color: document.querySelector("#blush-color").value,
    blush_intensity: Number(document.querySelector("#blush-intensity").value) / 100,
    eyeshadow_color: document.querySelector("#eyeshadow-color").value,
    eyeshadow_intensity: Number(document.querySelector("#eyeshadow-intensity").value) / 100,
  };
}

function applyPreset(name) {
  const preset = PRESETS[name];
  for (const [region, [color, intensity]] of Object.entries(preset)) {
    document.querySelector(`#${region}-color`).value = color;
    document.querySelector(`#${region}-intensity`).value = String(intensity);
    document.querySelector(`#${region}-out`).textContent = `${intensity}%`;
  }
}

async function loadSample() {
  setStatus("Loading sample…");
  const response = await fetch("/samples/face.jpg");
  if (!response.ok) {
    setStatus("Sample photo is missing.");
    return;
  }
  const blob = await response.blob();
  showBefore(new File([blob], "face.jpg", { type: "image/jpeg" }));
  setStatus("Sample ready.");
}

async function applyMakeup() {
  if (!state.file || state.busy) return;
  state.busy = true;
  applyButton.disabled = true;
  setStatus("Finding landmarks…");
  const body = new FormData();
  body.append("image", state.file);
  const look = readLook();
  for (const [key, value] of Object.entries(look)) {
    body.append(key, String(value));
  }
  try {
    const response = await fetch("/api/apply", { method: "POST", body });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      setStatus(payload.detail || "Could not apply makeup.");
      return;
    }
    const blob = await response.blob();
    after.src = URL.createObjectURL(blob);
    after.hidden = false;
    afterEmpty.hidden = true;
    setStatus("Makeup applied.");
  } catch {
    setStatus("Could not reach the makeup server.");
  } finally {
    state.busy = false;
    applyButton.disabled = false;
  }
}

function stopLive() {
  if (state.liveTimer) {
    clearInterval(state.liveTimer);
    state.liveTimer = null;
  }
}

function stopCamera() {
  stopLive();
  liveInput.checked = false;
  if (state.stream) {
    for (const track of state.stream.getTracks()) track.stop();
    state.stream = null;
  }
  preview.srcObject = null;
  preview.hidden = true;
  cameraActions.hidden = true;
  cameraButton.textContent = "Start camera";
}

async function grabFrame() {
  const canvas = document.createElement("canvas");
  canvas.width = preview.videoWidth || 640;
  canvas.height = preview.videoHeight || 480;
  canvas.getContext("2d").drawImage(preview, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
  if (!blob) return;
  state.file = new File([blob], "camera.jpg", { type: "image/jpeg" });
  before.src = URL.createObjectURL(blob);
  await applyMakeup();
}

async function startCamera() {
  if (state.stream) {
    stopCamera();
    setStatus("Camera off.");
    return;
  }
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 960 } },
      audio: false,
    });
  } catch {
    setStatus("Camera is unavailable in this browser.");
    return;
  }
  preview.srcObject = state.stream;
  preview.hidden = false;
  cameraActions.hidden = false;
  cameraButton.textContent = "Stop camera";
  setStatus("Camera on. Capture a frame, or turn on Live.");
}

document.querySelector("#look").addEventListener("submit", (event) => {
  event.preventDefault();
  applyMakeup();
});

photoInput.addEventListener("change", () => {
  const file = photoInput.files && photoInput.files[0];
  if (!file) return;
  showBefore(file);
  setStatus("Photo ready.");
});

document.querySelector("#sample").addEventListener("click", loadSample);
cameraButton.addEventListener("click", startCamera);
document.querySelector("#capture").addEventListener("click", grabFrame);

liveInput.addEventListener("change", () => {
  stopLive();
  if (!liveInput.checked || !state.stream) return;
  state.liveTimer = setInterval(() => {
    if (!state.busy) grabFrame();
  }, 800);
});

document.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => {
    applyPreset(button.dataset.preset);
    applyMakeup();
  });
});

bindRange("#lipstick-intensity", "#lipstick-out");
bindRange("#blush-intensity", "#blush-out");
bindRange("#eyeshadow-intensity", "#eyeshadow-out");

loadSample();
