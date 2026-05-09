# EU Inbound Calculator

A landed-cost calculator for inbound EU low-value e-commerce shipments under
**Council Reg. (EU) 2026/382** + **Commission Delegated Reg. C(2026)2760**.

Wraps the Avalara `getQuote` cross-border payload format so existing
integrations work unchanged while new callers can opt into the EU-2026
fields explicitly.

## What it does

- Implements the €3 simplified duty per the Delegated Act decision tree
  (FTA exclusion, item grouping by `(HS6, description, origin)`, declarant
  hierarchy)
- Routes VAT correctly (IOSS / special arrangements / standard import / OSS B2B)
- Adds Union handling fee + national fees (FR €5/HS6, IT €2/parcel, RO ~€5/parcel)
- Compares 6 alternative shipping strategies, ranked by landed cost
- Surfaces every default it had to apply when caller-supplied fields are missing

## Documentation

- [docs/PRD.md](docs/PRD.md) — Product requirements with the explicit
  default/fallback table (PRD §3.2 is the master reference)
- [docs/BRD.md](docs/BRD.md) — Surgical Avalara getQuote field additions
- [docs/samples/](docs/samples/) — Three example payloads (legacy, full, minimal)

## Run

```bash
cd backend
pip install -r requirements.txt
FLASK_APP=app:create_app flask run --debug --port 5050
pytest -q
```

## Quick test

```bash
curl -s -X POST localhost:5050/api/calculate \
  -H "Content-Type: application/json" \
  -d @docs/samples/avalara_getquote_eu2026_full.json | jq .
```

## Endpoints

| Method | Path | Body |
|--------|------|------|
| GET | `/api/health` | — |
| POST | `/api/calculate` | Avalara getQuote payload |
| POST | `/api/strategy` | Avalara getQuote payload |

## Deploy

Connect this repo to Render — `render.yaml` is configured. Auto-deploy
runs CI on every push to `main`.

## Project layout

```
backend/
  app/
    __init__.py            # Flask factory
    routes/calculator.py
    services/
      avalara_adapter.py   # Avalara getQuote → internal model
      calculator.py        # DA C(2026)2760 decision tree
      defaults.py          # Single source of truth for fallback rules
      strategy.py          # Alternative shipping strategies
    models/schemas.py
    reference/data.py      # FTA partners, fees, dates, VAT rates
  tests/                   # 40+ tests (defaults / decision tree / API)
docs/
  PRD.md
  BRD.md
  samples/
.github/workflows/ci.yml
render.yaml
```

## Status

POC — v0.1. See PRD §6 for open questions (Union fee amount, post-Nov national fee policy, product identifier transport mechanism).
