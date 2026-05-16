from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core import database


@asynccontextmanager
async def lifespan(app):
    database.init_db()
    yield


app = FastAPI(title="Job Autopilot v2", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
