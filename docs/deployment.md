# Deployment

> **Last updated:** April 1, 2026

## Infrastructure

- **GCP VM**: GCP Compute Engine (e2-medium, ~$25/mo)
- **Container**: `ghostpour` on `proxy-tier` Docker network
- **Routing**: Nginx Proxy Manager routes `api.example.com` → `ghostpour:8000`
- **CI/CD**: Push to `main` → GitHub Actions builds image → pushes to GHCR → SSH deploys
- **Data**: SQLite DB persisted in `ghostpour-data` Docker volume at `/app/data/`
- **Server config**: `/opt/ghostpour/.env.prod` + `/opt/ghostpour/docker-compose.prod.yml` + `/opt/ghostpour/config/product-ids.yml`

## Private config files

Some config files are gitignored to keep customer-specific data out of the public repo:

| File | Purpose | Required? |
|------|---------|-----------|
| `.env.prod` | Secrets (JWT secret, API keys, admin key) | Yes |
| `config/product-ids.yml` | Real StoreKit product ID → tier mapping | Yes (for subscriptions) |

**`config/product-ids.yml`** overrides the placeholder `storekit_product_id` values in `tiers.yml` at startup. Format:

```yaml
standard: "com.yourapp.sub.standard.monthly"
pro: "com.yourapp.sub.pro.monthly"
ultra: "com.yourapp.sub.ultra.monthly"
ultra_max: "com.yourapp.sub.ultramax.monthly"
```

This file must exist on the production server. For Docker deploys, either:
- Mount it as a volume: `-v /opt/ghostpour/config/product-ids.yml:/app/config/product-ids.yml`
- Or copy it into the image during a local build

Without this file, `/v1/verify-receipt` and `/v1/sync-subscription` will reject real StoreKit purchases (they won't match the placeholder product IDs).

## Manual deploy

```bash
ssh into GCP VM
docker login ghcr.io
docker compose pull && up -d --force-recreate
```

## Admin Dashboard

Web UI at `/admin` with tabs:
- **Overview**: Today's stats, period summary, user counts by tier, allocation alerts (users >80%), trial funnel, cache savings, daily trend chart
- **Models**: Usage by provider/model (requests, tokens, cost, latency)
- **Users**: All users with tier badges, lifetime stats, inline set-tier dropdown, drill-down detail
- **Tiers**: Tier config cards with simulate button, per-feature state toggles (enabled/teaser/disabled)
- **Latency**: Response time percentiles (p50/p75/p90/p95/p99)
- **Providers**: API key management, credit balance checks
- **Errors**: Error summary by status/provider, recent error log table

Admin key: stored in `CZ_ADMIN_KEY` env var, persisted in browser localStorage.
