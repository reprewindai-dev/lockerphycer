"""
Locker Phycer - Main FastAPI Application
AI-Powered Security Platform
"""

from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import uvicorn
import logging
from datetime import datetime

from core.config.settings import settings
from core.database.database import engine, Base
from core.security.middleware import SecurityMiddleware
from apps.api.routers import auth, users, security, monitoring, ai
from apps.api.routers.verticals import router as verticals_router
from core.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logging.info(f"Starting {settings.APP_NAME} v{settings.VERSION}")
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logging.info("Application startup complete")
    
    yield
    
    # Shutdown
    logging.info("Application shutdown")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="AI-Powered Security Platform",
    version=settings.VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan
)

# Setup logging
setup_logging()

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS
)

app.add_middleware(SecurityMiddleware)


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "timestamp": datetime.utcnow().isoformat(),
                "path": str(request.url.path)
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logging.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "message": "Internal server error",
                "timestamp": datetime.utcnow().isoformat(),
                "path": str(request.url.path)
            }
        }
    )


# Health check endpoints
@app.get("/health", tags=["Health"])
async def health_check():
    """Basic health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": settings.VERSION,
        "service": settings.APP_NAME
    }


@app.get("/health/detailed", tags=["Health"])
async def detailed_health_check():
    """Detailed health check with system status"""
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
            "ai_services": await get_ai_services_status()
        }
    }


async def get_ai_services_status():
    """Check AI services status"""
    try:
        # Check if AI models are loaded
        from core.ai.model_manager import get_model_status
        return await get_model_status()
    except Exception:
        return {"status": "unhealthy", "message": "AI services unavailable"}


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": settings.VERSION,
        "docs": "/docs" if settings.DEBUG else "Documentation not available in production",
        "health": "/health"
    }


# ── Landing page ──────────────────────────────────────────────────────────────
_LANDING_DIR = Path(__file__).resolve().parent.parent / "web" / "landing"


@app.get("/landing", response_class=HTMLResponse, tags=["Landing"])
async def landing_page():
    """Serve the LockerSphere landing page."""
    index = _LANDING_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>Landing page not found</h1>", status_code=404)


# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(security.router, prefix="/api/v1/security", tags=["Security"])
app.include_router(monitoring.router, prefix="/api/v1/monitoring", tags=["Monitoring"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["AI Services"])
app.include_router(verticals_router, prefix="/api/v1/verticals", tags=["Verticals"])

from apps.api.routers.marketplace_catalog import router as marketplace_catalog_router
app.include_router(marketplace_catalog_router, prefix="/api/v1", tags=["Marketplace Catalog"])


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
