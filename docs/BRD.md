# Business Requirements Document — Avalara getQuote Integration

**Status:** Draft v0.1
**Companion to:** PRD.md
**Last updated:** 9 May 2026

## 1. Background

Avalara AvaTax Cross-Border (`getQuote` family of calls — both the
`CreateOrAdjustTransaction` with `type: SalesInvoice` + cross-border profile,
and the dedicated landed-cost quote endpoint) already supports inbound
landed-cost calculation. It does NOT yet support the new EU 2026 regime
introduced by Council Reg. (EU) 2026/382 + DA C(2026)2760.

The integration goal is to wrap getQuote so that:

- Existing callers work unchanged (defaults handle EU-2026 fields)
- New callers can override defaults with explicit EU-2026 inputs
- The wrapper enforces correct decision precedence even when getQuote
  would have returned a legacy answer

## 2. Existing Avalara getQuote contract (relevant fields only)

The fields below are already present in the Avalara cross-border request
schema and are consumed unchanged by this calculator:

```json
{
  "companyCode": "AVALARA-DEMO",
  "type": "SalesInvoice",
  "code": "ORDER-12345",
  "date": "2026-08-01",
  "currencyCode": "EUR",
  "customerCode": "CUST-001",
  "shippingTerms": "DDP",
  "addresses": {
    "shipFrom": {"country": "CN", "..." : "..."},
    "shipTo":   {"country": "DE", "..." : "..."}
  },
  "lines": [
    {
      "number": "1",
      "itemCode": "TSHIRT-001",
      "description": "Cotton t-shirt",
      "hsCode": "610910",
      "countryOfOrigin": "CN",
      "quantity": 2,
      "amount": 24.00,
      "taxCode": "PC040100"
    }
  ]
}
```

Mapping to the calculator's internal `Consignment` / `Item` model is
1:1 for these fields.

## 3. Surgical EU-2026 field additions

These are the **minimum** new fields required to drive the §FR-1 decision
tree from the PRD. Each is optional; the calculator falls back per
PRD §3.2 if omitted.

### 3.1 Transaction-level extension (`euReform2026` namespace)

```json
{
  ...standard getQuote fields...,
  "euReform2026": {
    "iossNumber": "IM3720000123",
    "platformIossNumber": null,
    "buyerAgent": false,
    "postalDesignatedOperator": false,
    "shipmentChannel": "express",
    "customsProcedureCode": null,
    "nonAlterationConfirmed": false
  }
}
```

| Field | Type | Drives | PRD default if missing |
|------|------|--------|------------------------|
| `iossNumber` | string\|null | `ioss_registered` | True if B2C ≤ €150, else False |
| `platformIossNumber` | string\|null | Art. 14a deemed-supplier path; declarant = "platform" | None |
| `buyerAgent` | bool | Hard exit from €3 regime | False |
| `postalDesignatedOperator` | bool | €3 trigger via postal route + declarant = "postal_operator" | False |
| `shipmentChannel` | enum: postal/express/general_cargo | Information; cross-validates `postalDesignatedOperator` | "express" |
| `customsProcedureCode` | string\|null | "42" → forces B2B path; otherwise inferred | None |
| `nonAlterationConfirmed` | bool | Direct-transport / non-alteration assertion. Set `true` when goods transited a third country under customs supervision with non-alteration documentation; gates FTA preferential treatment per Access2Markets rule. | False |

### 3.2 Customer-level extension (already partially in getQuote)

Avalara getQuote has `customerUsageType` (P/E/M/etc.) which approximates
B2B vs B2C, but it is not reliable enough for the legal B2B/B2C
distinction. The wrapper introduces:

```json
"customer": {
  ...,
  "euReform2026": {
    "isBusinessBuyer": false,
    "vatNumber": null
  }
}
```

| Field | Type | Drives | Default if missing |
|------|------|--------|---------------------|
| `isBusinessBuyer` | bool | `b2b` flag → CP42 path / hard exit | False (B2C) |
| `vatNumber` | string\|null | If supplied, auto-set `isBusinessBuyer=True` | None |

### 3.3 Line-level extensions (`euReform2026` namespace under each line)

```json
{
  "lines": [
    {
      ...standard line...,
      "euReform2026": {
        "ftaProofType": null,
        "ftaProofReference": null,
        "productIdentifiers": {
          "merchantId": "MER-TSHIRT-001",
          "manufacturerId": null,
          "gtin": "8901234567890"
        }
      }
    }
  ]
}
```

| Field | Type | Drives | Default if missing |
|------|------|--------|---------------------|
| `ftaProofType` | enum: REX/EUR1/EURMED/STATEMENT/null | If non-null AND `countryOfOrigin` ∈ FTA partners → FTA exclusion from €3 | null (no FTA) |
| `ftaProofReference` | string\|null | Audit trail for the FTA proof | null |
| `productIdentifiers.merchantId` | string\|null | Mandatory for declarations from 1 Nov 2026 | null (warning emitted post-deadline) |
| `productIdentifiers.manufacturerId` | string\|null | Same | null |
| `productIdentifiers.gtin` | string\|null | Standardised identifier — preferred where available | null |

### 3.4 Why these specific fields and not others

The calculator deliberately does NOT introduce:

- ❌ A `b2c` flag — derived from `isBusinessBuyer == False`, single source of truth
- ❌ A `forceE3` override — defeats the legal decision tree
- ❌ An `incoterm` branching field — incoterm is information-only, never branches
- ❌ A `vatRate` override — destination MS is the legal driver
- ❌ Per-line `iossNumber` — IOSS is consignment-level by VAT Directive Art. 369l

This keeps the field count low. Total surgical additions: **10 new fields**
(8 truly new, 2 cross-validating existing fields).

## 4. Backwards compatibility

| Scenario | Behavior |
|----------|----------|
| Caller sends legacy getQuote payload (no `euReform2026` namespaces) | Calculator runs full default chain per PRD §3.2; returns answer with `defaults_applied` listing every default the engine had to use |
| Caller sends getQuote payload with `transaction_date < 2026-07-01` | Pre-€3 regime; standard tariff with €150 de minimis; `euReform2026` fields ignored |
| Caller sends partial `euReform2026` (only some fields) | Each missing field falls back per PRD §3.2 independently |
| Avalara getQuote returns a duty figure | Wrapper computes its own duty per the new regime; if they disagree, the wrapper's figure prevails and `legacy_avalara_duty_eur` is included for reference |

## 5. Avalara API contract considerations

- **Authentication**: existing AvaTax API token is sufficient for getQuote pass-through
- **Rate limits**: wrapper adds zero new external API calls in fast path; FTA partner list and VAT rates are in-memory
- **Error mapping**: getQuote 4xx → wrapper returns 400 with `avalara_error` field; getQuote 5xx → wrapper returns 502
- **Timeouts**: wrapper enforces a 5s timeout on getQuote; on timeout, wrapper degrades to local calculation only with `degraded_mode: true` in response

## 6. Sample payloads

See `docs/samples/`:

- `avalara_getquote_legacy.json` — pure legacy getQuote, no EU-2026 fields
- `avalara_getquote_eu2026_full.json` — fully populated with all extensions
- `avalara_getquote_eu2026_minimal.json` — only IOSS number supplied, rest default

## 7. Field accuracy expectations

For each surgical field, the table below states the engine's expected accuracy
when the field is **omitted** (caller relies on default).

| Field omitted | Population accuracy |
|---------------|---------------------|
| `iossNumber` | 93% (Council statistic) |
| `buyerAgent` | ~98% (forwarders rare in e-commerce) |
| `postalDesignatedOperator` | ~70% (postal share decreasing) |
| `isBusinessBuyer` | ~85% (B2C dominates inbound EU) |
| `ftaProofType` | ~95% (FTA proof rare on parcel-level) |
| `productIdentifiers.*` | n/a until 1 Nov 2026 (warning-only) |

These figures inform the priority of upstream data sourcing: `iossNumber`,
`postalDesignatedOperator`, and `isBusinessBuyer` are the highest-value
fields to capture explicitly because their default-failure modes affect duty.

## 8. Phased rollout

| Phase | Date | Scope |
|-------|------|-------|
| **0** | 9 May 2026 | This POC: Flask + Render, single repo, default-driven |
| **1** | 1 Jul 2026 | First production traffic; €3 regime live |
| **2** | 1 Nov 2026 | Product identifier capture mandatory; Union handling fee live |
| **3** | 1 Jul 2028 | CDH cutover; €3 deprecated; full HS-based duty |
