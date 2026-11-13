from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOKS = ROOT / "runbooks"
GUARDRAILS = ROOT / "guardrails"
NEMO = GUARDRAILS / "nemo"
UI = Path(__file__).resolve().parent / "ui"
