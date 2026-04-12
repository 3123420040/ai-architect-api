from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as api_router
from app.core.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Phase 3 package-centric API candidate for KTC KTS",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=str(settings.storage_dir)), name="media")
app.include_router(api_router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "api",
        "app": settings.app_name,
        "environment": settings.app_env,
        "viewer_3d_enabled": settings.feature_flag_viewer_3d,
    }
