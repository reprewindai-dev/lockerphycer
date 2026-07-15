# Locker Phycer Production Operating Model

## Objective
Build a revenue-ready sovereign AI security control plane for regulated B2B teams that need AI routing, security telemetry, RBAC, wallet billing, audit evidence, and marketplace execution packs inside their own cloud boundary.

## System Components
- FastAPI API in `apps/api/main.py`
- Async SQLAlchemy persistence in `core/database`
- Normalized domain models in `db/models.py`
- JWT auth, RBAC, and admin guardrails in `core/security/auth.py`
- Billing and wallet ledger in `/api/v1/billing`
- Security event, monitoring, AI request, GPC, marketplace, actor, and agent-control routers under `/api/v1`
- Static premium web surfaces served from `apps/web/static`

## Revenue Model
- Community: free, 5 seats, 500 AI requests, 7-day logs.
- Growth: $299/month, 25 seats, 5,000 AI requests, 30-day logs.
- Sovereign: $799/month, 100 seats, 10,000 AI requests, 90-day logs, SSO/SAML positioning.
- Enterprise: custom contract, air-gapped deployment, managed operations, implementation fees.

Billing state is persisted at workspace level with Stripe customer/subscription identifiers and an append-only wallet transaction ledger.

## State & Data Handling
- Users have UUID primary keys and unique emails.
- Sessions are persisted and revocable.
- AI requests retain request metadata, cost, status, confidence, and completion timing.
- Security events retain severity, threat type, AI analysis, assignment, and resolution.
- Evidence, decision frames, actor runs, and agent runs retain proof/audit hashes for replayability.
- Customer data is designed to remain inside the customer's database/VPC.

## Failure & Degradation Rules
- `/health` returns process health.
- `/health/detailed` checks database, Redis configuration, and AI model manager status.
- Unhandled errors return generic 500 payloads while logging traceback server-side.
- Uptime checks and alerts are first-class tables for operator dashboards.

## Constraints
- No secrets in code.
- Use `.env` or platform secrets for all credentials.
- Do not enable wildcard CORS in production.
- Protect admin routes with `require_admin`.
- Preserve audit hashes and ledger records; never mutate them for cosmetic cleanup.

## Deployment Notes
- Local: `uvicorn apps.api.main:app --host 0.0.0.0 --port 8000`
- Container: `docker compose up --build`
- Production database: set `DATABASE_URL=postgresql://...`; the app converts it to asyncpg automatically.
- Required production secrets: `SECRET_KEY`, `DATABASE_URL`, `POSTGRES_PASSWORD`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, provider API keys as needed.
