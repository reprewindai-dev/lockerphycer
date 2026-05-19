"""
Veklom Sovereign AI Hub — Main FastAPI Application
Backend source of truth: lockerphycer
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import uvicorn
import logging
import os
from datetime import datetime
from pathlib import Path

from core.config.settings import settings
from core.database.database import engine, Base
from apps.api.routers import auth, users, security, monitoring, ai
from apps.api.routers import workspace, marketplace, billing, gpc, platform_pulse, feedback, command_center
from core.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logging.info(f"Starting {settings.APP_NAME} v{settings.VERSION}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("Application startup complete — all tables created")
    yield
    logging.info("Application shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    description="Veklom Sovereign AI Hub — Playground, GPC, Models, Tool Hub, Pipelines, Governance, Vault, Deployments, Monitoring, Billing",
    version=settings.VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

setup_logging()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "timestamp": datetime.utcnow().isoformat(),
                "path": str(request.url.path),
            }
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "message": "Internal server error",
                "timestamp": datetime.utcnow().isoformat(),
                "path": str(request.url.path),
            }
        },
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": settings.VERSION,
        "service": settings.APP_NAME,
    }


@app.get("/health/detailed", tags=["Health"])
async def detailed_health_check():
    from core.database.database import get_db_status
    from core.utils.redis_client import get_redis_status

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": settings.VERSION,
        "service": settings.APP_NAME,
        "components": {
            "database": await get_db_status(),
            "redis": await get_redis_status(),
            "ai_services": await get_ai_services_status(),
        },
    }


async def get_ai_services_status():
    try:
        from core.ai.model_manager import get_model_status
        return await get_model_status()
    except Exception:
        return {"status": "unavailable", "message": "AI services offline"}


# ---------------------------------------------------------------------------
# API Routers — source of truth endpoints
# ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(security.router, prefix="/api/v1/security", tags=["Security"])
app.include_router(monitoring.router, prefix="/api/v1/monitoring", tags=["Monitoring"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["AI Services"])
app.include_router(workspace.router, prefix="/api/v1/workspace", tags=["Workspace"])
app.include_router(marketplace.router, prefix="/api/v1/marketplace", tags=["Marketplace"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(gpc.router, prefix="/api/v1/gpc", tags=["GPC"])
app.include_router(platform_pulse.router, prefix="/api/v1/platform", tags=["Platform"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["Feedback"])
app.include_router(command_center.router, prefix="/api/v1/command-center", tags=["Command Center"])


# ---------------------------------------------------------------------------
# Static frontend serving
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
WORKSPACE_DIR = STATIC_DIR / "workspace"


@app.get("/", tags=["Frontend"], response_class=HTMLResponse)
async def landing_page():
    """Serve the Veklom landing page"""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html")
    return HTMLResponse("<h1>Veklom Sovereign AI Hub</h1><p>Frontend not built yet.</p>")


# Mount landing-page static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Workspace: serve the real Veklom frontend build (StaticFiles with html=True
# handles index.html fallback and trailing-slash redirect automatically)
if WORKSPACE_DIR.exists():
    app.mount("/workspace", StaticFiles(directory=str(WORKSPACE_DIR), html=True), name="workspace")


if __name__ == "__main__":
    uvicorn.run(
        "apps.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
