# SIM Provider

Doover apps for fleet SIM-card visibility:

| App | Type | What it does |
|-----|------|---------------|
| **M2M One SIM Provider** (`sim_provider_m2mone`) | Integration | On a schedule, looks up every assigned device's SIM ICCID in an M2M One Control Centre account and writes the result (status + month-to-date usage) to that device's `sim-card` channel. |
| **Fleet SIM Usage Dashboard** (`sim_dashboard`) | Org-level app | Reads the `sim-card` channel across every device it has permission to see and renders totals, heavy users, and a per-SIM table. |

More provider integrations (Telstra IoT, KORE, etc.) can be added as new `src/sim_provider_<name>/` packages — they only need to agree on the shared `sim-card` payload shape so the dashboard treats them uniformly.

## Shared payload

Every provider writes the same shape to `sim-card`:

```jsonc
{
  "iccid": "8961...",
  "status": "in_account" | "not_in_account" | "error",
  "in_account": true,
  "details": { /* provider-specific row */ },
  "usage": {
    "month_to_date_data_mb": 123.4,
    "month_to_date_sms": 0,
    "month_to_date_voice": 0
    /* … */
  },
  "error": null,
  "provider": "m2mone",
  "checked_at": 1716057600000,
  "configured_account_id": "100020620"
}
```

The aggregate is replaced on every successful run and a matching message is appended for history.

## Structure

```
README.md
pyproject.toml
doover_config.json
build.sh
src/sim_provider_m2mone/
  __init__.py        # lambda handler
  application.py     # M2MOneSimProviderApp.on_schedule
  app_config.py
  m2mone_client.py   # aiohttp wrapper for the Jasper Control Center REST API
src/sim_dashboard/
  __init__.py
  application.py     # SimDashboardApp.on_deployment (pings connection)
  app_config.py
  app_ui.py          # remote-component UI schema
widget/              # rsbuild + module-federation widget bundle (FleetSimUsageWidget)
tests/
```

## Running locally

```bash
uv sync
uv run pytest -v

# regenerate doover_config.json (split across 3 commands)
uv run export-config-m2mone
uv run export-config-dashboard
uv run export-ui-dashboard

# build the widget
npm --prefix widget install
npm --prefix widget run build
```

## Deployment

```bash
./build.sh                          # builds package.zip for the lambdas
doover app publish --profile dv2    # publishes both apps + widget
```
