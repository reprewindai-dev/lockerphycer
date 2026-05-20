# 🔐 Secret Rotation Checklist

Complete these IN ORDER before entering anything into Coolify.
Check each box as you go.

---

## Step 1 — Rotate Secrets (do this first)

- [ ] **Coolify API Token** — Coolify → Profile → API Tokens → delete `3|0xtTas...`
- [ ] **Sentry DSN** — sentry.io → Settings → Projects → Client Keys → rotate
- [ ] **Sentry SCIM Token** — sentry.io → Settings → Auth Tokens → revoke `9f41a85b...`
- [ ] **Resend API Keys** (all 4) — resend.com → API Keys → delete all, create 2 new:
  - One named `veklom-main` → goes in `RESEND_API_KEY`
  - One named `veklom-smtp` → goes in `RESEND_SMTP_KEY` (for Alertmanager email)
- [ ] **Grafana API Token** — grafana.com → My Account → Access Policies → revoke all, create new with scopes:
  - `metrics:write` `logs:write` `traces:write` `profiles:write` `alerts:write`
  - This ONE token goes in: `GRAFANA_API_TOKEN`, `PROMETHEUS_API_TOKEN`, `PROMETHEUS_PASSWORD`, `LOKI_PASSWORD`, `ALERTMANAGER_PASSWORD`, `PYROSCOPE_PASSWORD`, `SIGIL_API_TOKEN`
- [ ] **SERPAPI Key** — serpapi.com → Dashboard → API Key → regenerate
- [ ] **Grafana Sigil Token** — same rotation as Grafana above (it was a Grafana token)
- [ ] **SSH Key** — Coolify → Keys & Tokens → SSH Keys → delete `agentworkwindsurf`, add new keypair

---

## Step 2 — Generate New App Secrets

Run these 3 commands on any machine, copy the output:

```bash
openssl rand -hex 32   # → SECRET_KEY
openssl rand -hex 32   # → AI_CITIZENSHIP_SECRET  
openssl rand -hex 32   # → ENCRYPTION_KEY
```

Also choose:
- A strong Postgres password → `POSTGRES_PASSWORD` + update `DATABASE_URL`
- A strong Redis password → `REDIS_PASSWORD` + update `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`

---

## Step 3 — Fill in `infra/coolify.env.template`

Replace every `ROTATE_FIRST` and `FILL_IN` with your new values.

---

## Step 4 — Paste into Coolify

1. Coolify → Your App → Environment Variables
2. Paste the entire filled-in template
3. Click Save
4. Redeploy

---

## Step 5 — Upload Alert Rules to Grafana Cloud

```bash
export GRAFANA_API_TOKEN=your_new_token
bash infra/scripts/upload-alerts.sh
```

---

## Step 6 — Verify Everything Works

- [ ] App starts without errors in Coolify logs
- [ ] https://api.veklom.com/health returns `{"status": "healthy"}`
- [ ] Sentry receives a test event (visit `/sentry-debug` once, then delete the route)
- [ ] Grafana dashboard shows metrics at https://reprewindaidev.grafana.net
- [ ] Celery beat scheduler shows 0 skipped jobs after fix

---

## Quick Reference — Service Logins

| Service | Login Email | URL |
|---|---|---|
| Sentry | pluggedfinds41@gmail.com | sentry.io |
| Resend | (your email) | resend.com |
| GitHub | reprewindai@gmail.com | github.com |
| Grafana Cloud | (your email) | grafana.com |
| SERPAPI | (your email) | serpapi.com |

## Grafana Cloud Instance IDs (safe to keep, not secrets)

| Service | URL | User/ID |
|---|---|---|
| Grafana | https://reprewindaidev.grafana.net | 1652772 |
| Prometheus | prometheus-prod-32-prod-ca-east-0.grafana.net | 3229768 |
| Loki | logs-prod-018.grafana.net | 1610559 |
| Alertmanager | alertmanager-prod-ca-east-0.grafana.net | 1612824 |
| Pyroscope | profiles-prod-006.grafana.net | 1652772 |
| OTLP | otlp-gateway-prod-ca-east-0.grafana.net/otlp | 1652772 |
| Sigil AI Obs | sigil-prod-ca-east-0.grafana.net | 1652772 |
