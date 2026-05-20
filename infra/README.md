# Veklom Observability Infrastructure

All Grafana Cloud Canada East (`prod-ca-east-0`, `aws ca-central-1`).

## Instances

| Service | URL | User/ID |
|---|---|---|
| Grafana | https://reprewindaidev.grafana.net | Instance ID: 1652772 |
| Prometheus (Mimir) | https://prometheus-prod-32-prod-ca-east-0.grafana.net/api/prom | 3229768 |
| Loki | https://logs-prod-018.grafana.net | 1610559 |
| Alertmanager | https://alertmanager-prod-ca-east-0.grafana.net | 1612824 |

**Password for all:** Your Grafana.com API Token (same token, set as `GRAFANA_API_TOKEN` in Coolify)

## Coolify Env Vars Required

```
GRAFANA_API_TOKEN=        # Grafana.com API token — used for Prometheus, Loki, Alertmanager
PROMETHEUS_API_TOKEN=     # Same token (separate var for clarity)
SLACK_WEBHOOK_URL=        # Slack incoming webhook for alert routing
RESEND_SMTP_KEY=          # Resend SMTP key (re_N26pKTux_... — rotate first)
```

## Deploy Observability Stack

```bash
# From your server / Coolify terminal:
docker compose -f docker-compose.yml -f infra/docker/docker-compose.observability.yml up -d
```

## Upload Alert Rules to Grafana Cloud

```bash
export GRAFANA_API_TOKEN=your_token
bash infra/scripts/upload-alerts.sh
```

## File Structure

```
infra/
├── alerts/
│   └── rules.yml                          # Prometheus alert rules
├── docker/
│   ├── alertmanager/alertmanager.yml      # Alert routing (Slack + email)
│   ├── loki/loki-config.yaml             # Local Loki
│   ├── nginx/nginx.conf                   # Reverse proxy
│   ├── postgres/init.sql                  # DB init
│   ├── prometheus/prometheus.yml          # Metrics scrape + remote_write
│   ├── promtail/config.yml               # Log shipping to Loki
│   ├── redis/redis.conf                   # Redis config
│   └── docker-compose.observability.yml  # Full observability stack
└── scripts/
    └── upload-alerts.sh                   # Push rules to Grafana Cloud
```
