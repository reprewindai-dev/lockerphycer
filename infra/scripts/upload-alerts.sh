#!/bin/bash
# upload-alerts.sh — Push Prometheus rules + Alertmanager config to Grafana Cloud
# Run this after rotating your Grafana API token
#
# Usage:
#   export GRAFANA_API_TOKEN=your_new_token
#   ./infra/scripts/upload-alerts.sh

set -e

METRICS_URL="https://prometheus-prod-32-prod-ca-east-0.grafana.net"
METRICS_USER="3229768"

ALERT_URL="https://alertmanager-prod-ca-east-0.grafana.net"
ALERT_USER="1612824"

if [ -z "$GRAFANA_API_TOKEN" ]; then
  echo "❌ ERROR: GRAFANA_API_TOKEN is not set."
  echo "   Run: export GRAFANA_API_TOKEN=your_token"
  exit 1
fi

echo "📤 Uploading Prometheus alert rules to Grafana Cloud Metrics..."
mimirtool rules load \
  --address="$METRICS_URL" \
  --id="$METRICS_USER" \
  --key="$GRAFANA_API_TOKEN" \
  infra/alerts/rules.yml

echo "✅ Rules uploaded."

echo "📤 Uploading Alertmanager config to Grafana Cloud Alertmanager..."
mimirtool alertmanager load \
  --address="$ALERT_URL" \
  --id="$ALERT_USER" \
  --key="$GRAFANA_API_TOKEN" \
  infra/docker/alertmanager/alertmanager.yml

echo "✅ Alertmanager config uploaded."
echo ""
echo "🎉 Done. Your rules and alerts are live in Grafana Cloud Canada East."
echo "   Dashboard: https://reprewindaidev.grafana.net"
