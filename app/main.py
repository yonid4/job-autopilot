from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="Job Autopilot v2")
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
