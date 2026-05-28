"""
Veklom Sovereign AI Hub — Main FastAPI Application
Backend source of truth: lockerphycer
"""

from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import uvicorn
import logging
import os
from datetime import datetime

from core.config.settings import settings
from core.database.database import engine, Base

# ─── Sentry — Error Tracking & Performance Monitoring ─────────────────────────
# Must be initialised before any other imports that Sentry needs to instrument.
# Set SENTRY_DSN in your environment / .env to activate.  When SENTRY_DSN is
# absent the SDK is a silent no-op — nothing breaks in local dev.
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

_sentry_dsn = os.environ.get("SENTRY_DSN") or getattr(settings, "SENTRY_DSN", None)
_sentry_env = os.environ.get("SENTRY_ENVIRONMENT") or getattr(settings, "ENVIRONMENT", "production")

sentry_sdk.init(
    dsn=_sentry_dsn,
    environment=_sentry_env,
    release=getattr(settings, "VERSION", "0.1.0"),
    # ── Performance ──────────────────────────────────────────────────────────
    # traces_sample_rate=1.0 captures 100 % of transactions so performance
    # data appears in Sentry immediately.  Lower this (e.g. 0.1) in high-
    # traffic production once you have a baseline.
    traces_sample_rate=1.0,
    # profiles_sample_rate is relative to traces_sample_rate.
    # 1.0 = profile every sampled transaction.
    profiles_sample_rate=1.0,
    # ── Integrations ─────────────────────────────────────────────────────────
    integrations=[
        StarletteIntegration(transaction_style="endpoint"),
        FastApiIntegration(transaction_style="endpoint"),
        SqlalchemyIntegration(),
        LoggingIntegration(
            level=logging.INFO,        # Capture INFO and above as breadcrumbs
            event_level=logging.ERROR, # Send ERROR and above as Sentry events
        ),
    ],
    # Send user IP & request body context with each event
    send_default_pii=False,
)

if _sentry_dsn:
    logging.info("Sentry initialised — env=%s traces_sample_rate=1.0", _sentry_env)
else:
    logging.info("Sentry DSN not set — running without error/performance tracking")

# ─── OpenTelemetry / Grafana Cloud Instrumentation ────────────────────────────
# When running with `opentelemetry-instrument uvicorn ...` auto-instrumentation
# handles everything.  This block provides a programmatic fallback so the app
# can also boot normally and still push traces if the OTLP env vars are set.
def _setup_otel():
    try:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", None)
        if not endpoint:
            return

        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", settings.OTEL_SERVICE_NAME)})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        # Instrument will be called after `app` is created (see below)
        logging.info("OpenTelemetry programmatic init — traces → %s", endpoint)
    except ImportError:
        logging.info("OpenTelemetry SDK not installed — skipping programmatic tracing")
    except Exception as exc:
        logging.warning("OpenTelemetry init failed: %s", exc)

_setup_otel()

from apps.api.routers import auth, users, security, monitoring, ai
from apps.api.routers.auth import resolve_current_user

# Alias used by routes that accept either a JWT user or an API key.
# Provides a single dependency name for future extension to API-key auth.
get_current_user_or_api_key = resolve_current_user
from apps.api.routers import workspace, marketplace, billing, gpc, gpc_proxy, platform_pulse, feedback, command_center
from apps.api.routers.verticals import router as verticals_router
from apps.api.routers import terminal_ws
from apps.api.routers import agents as agents_router
from apps.api.routers import actors as actors_router
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

# Instrument FastAPI with OpenTelemetry (if SDK is available)
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)
except ImportError:
    pass

_cors_origins = (
    ["*"]
    if settings.DEBUG
    else [
        settings.FRONTEND_URL,
        "https://lockersphere.com",
        "https://app.lockersphere.com",
        "https://command.lockersphere.com",
        "https://veklom.com",
        "https://app.veklom.com",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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
    # Log the full traceback internally via exc_info — do NOT interpolate
    # str(exc) into the message to prevent raw exception details leaking
    # into log-aggregation sinks (CodeQL alert #8: information exposure
    # through an exception).
    logging.error("Unhandled exception on %s", request.url.path, exc_info=True)
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


# ── Landing page ──────────────────────────────────────────────────────────────
_LANDING_DIR = Path(__file__).resolve().parent.parent / "web" / "landing"


@app.get("/landing", response_class=HTMLResponse, tags=["Landing"])
async def lockersphere_landing():
    """Serve the LockerSphere landing page."""
    index = _LANDING_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>Landing page not found</h1>", status_code=404)


# ---------------------------------------------------------------------------
# API Routers — source of truth endpoints
# ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(security.router, prefix="/api/v1/security", tags=["Security"])
app.include_router(monitoring.router, prefix="/api/v1/monitoring", tags=["Monitoring"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["AI Services"])
app.include_router(verticals_router, prefix="/api/v1/verticals", tags=["Verticals"])
app.include_router(workspace.router, prefix="/api/v1/workspace", tags=["Workspace"])
app.include_router(marketplace.router, prefix="/api/v1/marketplace", tags=["Marketplace"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(gpc.router, prefix="/api/v1/gpc", tags=["GPC"])
app.include_router(gpc_proxy.router, prefix="/gpc-engine", tags=["GPC Proxy"])
app.include_router(platform_pulse.router, prefix="/api/v1/platform", tags=["Platform"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["Feedback"])
app.include_router(command_center.router, prefix="/api/v1/command-center", tags=["Command Center"])
app.include_router(agents_router.router, prefix="/api/v1/agents", tags=["Agent Workforce"])
app.include_router(actors_router.router, prefix="/api/v1", tags=["Execution Packs"])
app.include_router(terminal_ws.router, tags=["Terminal WebSocket"])

from apps.api.routers.marketplace_catalog import router as marketplace_catalog_router
app.include_router(marketplace_catalog_router, prefix="/api/v1", tags=["Marketplace Catalog"])


# ---------------------------------------------------------------------------
# Static frontend serving
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
WORKSPACE_DIR = STATIC_DIR / "workspace"
CC_DIR = STATIC_DIR / "command-center"


@app.get("/", tags=["Frontend"], response_class=HTMLResponse)
async def veklom_landing():
    """Serve the Veklom landing page"""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html")
    return HTMLResponse("<h1>Veklom Sovereign AI Hub</h1><p>Frontend not built yet.</p>")


# Mount landing-page static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Command Center terminal static files (must be mounted before workspace catch-all)
if CC_DIR.exists():
    app.mount("/command-center", StaticFiles(directory=str(CC_DIR), html=True), name="command-center")


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
