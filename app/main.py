from fastapi import FastAPI
from pydantic import BaseModel
import time

app = FastAPI(title="simple-model-server")


class PredictRequest(BaseModel):
    x: float


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/predict")
def predict(req: PredictRequest) -> dict:
    # Dummy model: y = 2x + 1
    y = (2.0 * req.x) + 1.0
    return {"y": y}


@app.get("/burn")
def burn(ms: int = 250) -> dict:
    # Busy-loop for a bounded duration to create predictable CPU load for HPA testing.
    duration = max(1, min(ms, 2000)) / 1000.0
    end = time.perf_counter() + duration
    x = 0.0
    while time.perf_counter() < end:
        x += 1.0
    return {"burned_ms": int(duration * 1000), "counter": int(x)}
