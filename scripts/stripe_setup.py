"""Idempotent Stripe catalog setup (TEST mode only).

Creates or updates, keyed by stable product ids and price lookup_keys:
  Veklom Pro             $99/month   lookup_key veklom_pro_monthly
  Veklom Team            $399/month  lookup_key veklom_team_monthly
  Veklom Credits Top-up  $50/$100/$500 one-time
                         lookup_keys veklom_topup_50 / _100 / _500
                         price metadata credits=<n> (internal; see
                         TOPUP_CREDITS_PER_USD, a flagged placeholder)
No Enterprise product (custom contracts).

Usage (reads STRIPE_SECRET_KEY from the environment; never prints it):
    python -m scripts.stripe_setup [--dry-run]
Refuses to run with a live key.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.entitlements.config import get_entitlement_settings  # noqa: E402
from core.entitlements.stripe_billing import LOOKUP_KEYS, TOPUP_USD, StripeClient  # noqa: E402

PRODUCTS = {
    "veklom_pro": "Veklom Pro",
    "veklom_team": "Veklom Team",
    "veklom_credits_topup": "Veklom Credits Top-up",
}


def catalog() -> list[dict]:
    per_usd = get_entitlement_settings().TOPUP_CREDITS_PER_USD
    items = [
        {"lookup_key": LOOKUP_KEYS["pro"], "product": "veklom_pro", "unit_amount": 9900,
         "interval": "month", "metadata": {"plan": "pro"}},
        {"lookup_key": LOOKUP_KEYS["team"], "product": "veklom_team", "unit_amount": 39900,
         "interval": "month", "metadata": {"plan": "team"}},
    ]
    for kind, usd in TOPUP_USD.items():
        items.append({"lookup_key": LOOKUP_KEYS[kind], "product": "veklom_credits_topup",
                      "unit_amount": usd * 100, "interval": None,
                      "metadata": {"kind": kind, "credits": str(usd * per_usd),
                                   "credits_basis": "TOPUP_CREDITS_PER_USD placeholder"}})
    return items


def ensure_product(client: StripeClient, product_id: str, name: str, dry_run: bool, log) -> None:
    try:
        existing = client.request("GET", f"/v1/products/{product_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        existing = None
    if existing is None:
        log(f"create product {product_id} ({name})")
        if not dry_run:
            client.request("POST", "/v1/products", {"id": product_id, "name": name},
                           idempotency_key=f"veklom-setup-product-{product_id}")
    elif existing.get("name") != name or not existing.get("active", True):
        log(f"update product {product_id}")
        if not dry_run:
            client.request("POST", f"/v1/products/{product_id}", {"name": name, "active": True})
    else:
        log(f"product {product_id} ok")


def _matches(price: dict, item: dict) -> bool:
    recurring = price.get("recurring") or {}
    product = price.get("product")
    product_id = product.get("id") if isinstance(product, dict) else product
    return (
        price.get("unit_amount") == item["unit_amount"]
        and price.get("currency") == "usd"
        and product_id == item["product"]
        and (recurring.get("interval") if recurring else None) == item["interval"]
    )


def ensure_price(client: StripeClient, item: dict, dry_run: bool, log) -> None:
    current = client.price_for_lookup_key(item["lookup_key"])
    if current is not None and _matches(current, item):
        if {k: (current.get("metadata") or {}).get(k) for k in item["metadata"]} != item["metadata"]:
            log(f"update metadata {item['lookup_key']}")
            if not dry_run:
                client.request("POST", f"/v1/prices/{current['id']}", {"metadata": item["metadata"]})
        else:
            log(f"price {item['lookup_key']} ok")
        return
    log(f"create price {item['lookup_key']}" + (" (replacing lookup_key)" if current else ""))
    if dry_run:
        return
    params = {"product": item["product"], "currency": "usd", "unit_amount": item["unit_amount"],
              "lookup_key": item["lookup_key"], "transfer_lookup_key": True, "metadata": item["metadata"]}
    if item["interval"]:
        params["recurring"] = {"interval": item["interval"]}
    client.request("POST", "/v1/prices", params)
    if current is not None:
        client.request("POST", f"/v1/prices/{current['id']}", {"active": False})


def run(client: StripeClient | None = None, *, dry_run: bool = False, log=print) -> None:
    if client is None:
        key = os.environ.get("STRIPE_SECRET_KEY", "")
        if key.startswith(("sk_live_", "rk_live_")):
            raise SystemExit("refusing to run with a live Stripe key (test mode only)")
        client = StripeClient(key, allow_live=False)
    for product_id, name in PRODUCTS.items():
        ensure_product(client, product_id, name, dry_run, log)
    for item in catalog():
        ensure_price(client, item, dry_run, log)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
