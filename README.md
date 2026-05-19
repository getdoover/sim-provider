# M2M One Integration

A Doover **integration** (organisation-scoped app) that periodically reconciles each assigned
device's SIM card with an **M2M One Control Centre** account.

## What it does

On every scheduled run the integration:

1. Iterates every device it has been granted access to via `dv_proc_extended_permissions`.
2. Reads the device's `dv-hardware` channel and pulls the SIM ICCID out of the `modem` snapshot.
3. Calls the configured M2M One Control Centre REST API to fetch device details and current
   billing-cycle usage for that ICCID.
4. Writes the consolidated result back to that device's `m2m-simcard` channel — both as a
   replaced aggregate (current state) and as an appended message (history).

The result includes a top-level `in_account` flag — `true` if the ICCID is registered against
the configured M2M One account, `false` if the API returned not-found, and `unknown` if the
lookup failed for any other reason.

## Structure

```
README.md
pyproject.toml
doover_config.json
build.sh
src/integration/
  __init__.py        # lambda handler entrypoint
  application.py     # M2MOneIntegrationApplication.on_schedule
  app_config.py      # config schema
  m2mone_client.py   # aiohttp wrapper for Control Centre REST API
tests/
  test_imports.py
```

## API

The M2M One Control Centre runs on a Cisco Jasper Control Center backend. The default base
URL (`https://rws.jasper.com/rws/api/v1`) and the **username + API key** Basic-auth credentials
must be configured on each install.

Endpoints used:

- `GET /devices/{iccid}` — SIM details (status, ratePlan, accountId, …)
- `GET /devices/{iccid}/ctdUsages` — current cycle data/SMS/voice usage

## Running locally

```bash
uv sync
uv run pytest -v
uv run export-config_integration   # regenerate doover_config.json
```

## Deployment

```bash
./build.sh                          # builds package.zip for the lambda
doover app publish --profile dv2    # publishes config
```
