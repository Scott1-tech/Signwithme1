"""FastAPI application entry point."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, contracts, dates, download, review, signatures, templates
from app.config import settings
from app.core.exceptions import AppError

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Template-driven contract review, comparison and signing for FMCSA-regulated carriers.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Content-SHA256"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "message": exc.message, "details": exc.details},
    )


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


@app.get("/ready", tags=["ops"])
def ready() -> dict:
    """Readiness probe: the database must actually answer."""
    from sqlalchemy import text

    from app.core.database import engine

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}


for module in (auth, templates, contracts, review, signatures, dates, download):
    app.include_router(module.router)
