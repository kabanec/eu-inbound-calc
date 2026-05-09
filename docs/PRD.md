# Product Requirements Document — EU Inbound Calculator

**Status:** Draft v0.1
**Owner:** [Product/Engineering]
**Last updated:** 9 May 2026
**Legal basis:** Council Reg. (EU) 2026/382, Commission Delegated Reg. C(2026)2760

## 1. Problem

International e-commerce sellers shipping to the EU need a deterministic, auditable
landed-cost calculator that:

1. Implements the new €3 simplified duty correctly (item grouping, FTA exclusion,
   declarant hierarchy)
2. Wraps an existing Avalara getQuote integration **without breaking the legacy contract**
3. Returns the right answer when callers omit fields (the typical case for early integrators)
4. Suggests cheaper compliant shipping strategies for a given basket

## 2. Scope

**In scope (v0.1):**

- Core duty calculation per DA C(2026)2760 (€3 vs standard tariff vs FTA)
- VAT routing (IOSS / special arrangements / standard import / OSS B2B)
- Union handling fee + national fees (FR, IT, RO)
- Strategy advisor (5 alternative strategies, ranked by landed cost)
- Avalara getQuote payload acceptance with surgical EU-2026 field additions
- Explicit defaults for every optional field, with deterministic fallback

**Out of scope (v0.1):**

- HS classification (delegated to Avalara Item Classification or pre-classified input)
- Origin determination (delegated to upstream)
- Live currency conversion (assume EUR throughout v0.1)
- Multi-stop / transit-through-EU shipments
- Excise goods (alcohol, tobacco, fuel)

## 3. Default and fallback behavior — explicit table

This is the master reference for what happens when the caller omits a field.

### 3.1 Required fields (no fallback — calculator rejects with HTTP 400)

| Field | Why no fallback |
|------|----------------|
| `destination_ms` | Drives VAT rate, national fee, and CN/HS6 territoriality — no defensible default |
| `items[]` (≥ 1 item) | Empty consignment is meaningless |
| `items[].hs6` OR `items[].itemCode` (with prior classification) | Item identity is required to count €3 lines |

### 3.2 Optional fields with deterministic fallback

For each parameter, the calculator emits a `default_applied` warning in the response
so downstream auditors can see what the engine assumed.

| Parameter | Default if missing | Heuristic / accuracy | Failure mode if heuristic is wrong |
|-----------|--------------------|----------------------|------------------------------------|
| `transaction_date` | `today()` | Server clock; 100% accurate for "now" queries | Wrong phase logic if caller is asking about a future scenario without specifying date |
| `consignment_value_eur` | `sum(items[].qty * items[].unit_value_eur)` | Auto-derived; 100% if items have values | Misses freight/insurance if those should be in CIF; we operate on intrinsic value per Reg. 2026/382, so this is correct |
| `b2b` | `False` | Assumes B2C distance sale (~85% of getQuote inbound EU population per Avalara reference) | Misses Customs Procedure 42 → wrongly applies €3 to a B2B import → caller overcharges customer |
| `ioss_registered` | `True` if `(NOT b2b) AND (consignment_value_eur ≤ 150)`, else `False` | Council statistic: 93% of B2C low-value imports are IOSS-registered | Underestimates duty in 7% non-IOSS B2C cases (where standard tariff applies) — slight under-collection |
| `buyer_agent` | `False` | Assumes direct distance sale (forwarders/agents are <2% of e-commerce flows) | Misclassifies forwarder/reshipper traffic as IOSS-eligible → applies €3 instead of standard tariff |
| `postal_designated_op` | `False` | Assumes commercial channel (postal share is shrinking, ~25% of EU inbound) | Underestimates €3 trigger if non-IOSS postal flow is not flagged → applies standard tariff when €3 should apply (under-collection) |
| `channel` | `"express"` | Most common channel in the e-commerce population | Information-only field; does not branch the calculation |
| `incoterm` | `None` | Information-only; **never** used to infer IOSS/B2B status | None — explicitly non-branching |
| `items[].origin` | `"UNKNOWN"` | Treated as non-FTA origin (conservative) | Loses FTA preference if origin was actually FTA-eligible → overcharges duty (caller-acceptable error) |
| `items[].fta_proof_held` | `False` | Conservative — no claimed proof | Loses FTA exclusion → applies €3 to a goods that should be on standard tariff with FTA preference (over-collection ~€3 per item) |
| `items[].standard_duty_rate` | `0.00` (FREE) | Optimistic — assumes no MFN duty | Underestimates duty for textiles (8-12%), footwear (8%), some electronics — under-collection. Calculator emits `MISSING_TARIFF_RATE` warning. |
| `items[].fta_duty_rate` | `0.00` (FULLY PREFERENTIAL) | Optimistic when FTA proof is held | Underestimates duty for staged FTAs (e.g. CETA TRQ-administered tariff lines) — under-collection |
| `items[].description` | `""` (empty string) | Treated as a unique grouping key per item | Splits items unnecessarily into separate €3 lines (defensible — empty desc IS distinct, but suboptimal) |
| `items[].qty` | `1` | Single unit | Under-counts line value if caller forgot qty |

### 3.3 Edge cases requiring explicit handling

These trigger warnings, not errors:

| Condition | Response |
|-----------|----------|
| `b2b=True` AND `ioss_registered=True` | Warning: "IOSS is B2C-only per VAT Directive Art. 369l. Forcing IOSS=False." |
| `buyer_agent=True` AND `ioss_registered=True` | Warning: "Buyer agent breaks the distance-sale construct. Forcing IOSS=False." |
| `consignment_value_eur > 150` AND `ioss_registered=True` | Warning: "Value exceeds IOSS €150 cap. Forcing IOSS=False." |
| `transaction_date < 2026-07-01` | Warning: "Pre-€3 regime. Calculator returns standard tariff with €150 de minimis still applicable." |
| `transaction_date >= 2028-07-01` | Warning: "Post-CDH sunset. €3 simplified regime no longer applies; standard tariff path used." |
| `items[].standard_duty_rate == 0.00` and not `fta_proof_held` | Warning: "MISSING_TARIFF_RATE — duty rate defaulted to 0%. Result is unreliable for non-€3 path." |

### 3.4 Output shape — defaults reflected in response

Every response includes:

```json
{
  "duty_total_eur": "...",
  ...,
  "defaults_applied": [
    {"field": "ioss_registered", "default": true, "rationale": "B2C ≤ €150 → 93% IOSS-registered population"},
    {"field": "items[0].standard_duty_rate", "default": 0.0, "rationale": "MISSING_TARIFF_RATE — caller did not supply"}
  ],
  "compliance_warnings": [...]
}
```

This makes the engine auditable — a customs broker reviewing a quote can see
which assumptions drove the result.

## 4. Functional requirements

### FR-1: Decision tree (in strict precedence order)

1. **Phase**: `transaction_date >= 2028-07-01` → standard tariff (CDH live)
2. **Hard exits to standard tariff**:
   - `consignment_value_eur > 150`
   - `b2b == True` (Customs Procedure 42 explicitly excluded — DA Recital 5)
   - `buyer_agent == True` (breaks distance-sale construct of IOSS Art. 14(4))
3. **Per-item FTA exclusion** (DA Art. 1(1)(a)):
   - If `fta_proof_held == True` AND `origin` ∈ FTA partners
   - → `standard_tariff_fta` regime, €3 NOT applied
4. **€3 trigger**: `ioss_registered == True` OR `postal_designated_op == True`
   - → €3 per `(hs6, description, origin)` group
5. **Else**: standard tariff with special-arrangements VAT routing

### FR-2: Item grouping per DA Art. 1(1)(b)(61)

An "item" = one or more goods sharing the 3-tuple `(tariff_classification, description, origin)`.
- Identical tuples collapse to one declaration line → €3 once
- Different in any of the 3 → separate items → €3 each

### FR-3: Avalara getQuote interoperability

- Engine accepts a payload that is a **superset** of the Avalara getQuote request
- Existing getQuote callers work unchanged (engine derives missing EU-2026 fields from defaults)
- New callers can supply EU-2026 fields explicitly via dedicated extension fields

See BRD §3 for the surgical field additions.

### FR-4: Strategy advisor

For a given basket, the advisor MUST evaluate and rank by landed cost ascending:

1. **status_quo** — ship as configured
2. **consolidate_descriptions** — normalize descriptions to collapse same-HS6+origin lines
3. **split_parcels** — one parcel per HS6+description+origin group (almost always worse)
4. **push_above_150** — increase parcel value above €150 to escape €3 regime
5. **drop_ioss_use_fta** — non-IOSS postal with FTA preference (only if all items FTA-eligible)
6. **b2b_eu_warehouse** — bulk import + EU domestic fulfillment

Each strategy returns landed cost, complexity score (1-5), and risk notes.

## 5. Non-functional requirements

| ID | Requirement |
|----|------------|
| NFR-1 | p95 latency < 200 ms for ≤ 20 items |
| NFR-2 | Stateless — horizontally scalable |
| NFR-3 | All monetary math via `Decimal` with HALF_UP rounding to 2 dp |
| NFR-4 | Reference data (rates, fees, FTA partners, dates) reloadable without code change (in-memory at v0.1, externalize to DB at v0.2) |
| NFR-5 | Deterministic — same input ⇒ same output (no time-of-day, no random) |
| NFR-6 | Audit trail — every response includes `defaults_applied` and `legal_references` arrays |

## 6. Open questions

1. **Union handling fee amount** — Commission has not yet published implementing act with the fee. v0.1 assumes €2 from 1 Nov 2026 (working assumption). When act is published, update `reference/fees.py` only.
2. **National fees post-Nov 2026** — FR / IT / RO have not committed to withdrawal. v0.1 keeps them live indefinitely; `transaction_date`-keyed config supports future-dated withdrawal without code change.
3. **Product identifier surfacing in H7** — Annex B amendment specifies "Supporting Document" data element. Engine returns the identifiers in the response; integration with declarant systems (Avalara CCS or partner) is v0.2.
4. **Returns / invalidation pathway** — DA point 12 closes Article 148(3) for ≤ €150 distance sales. Refunds module is v0.2.

## 7. Acceptance criteria

- [ ] `pytest backend/tests` all green (target: 40+ tests)
- [ ] Each row of §3.2 default table covered by ≥ 1 test
- [ ] Each row of §3.3 edge case covered by ≥ 1 test
- [ ] Avalara getQuote payload from `docs/samples/avalara_getquote.json` produces correct landed cost
- [ ] `/api/health` returns 200 in production
- [ ] Render auto-deploy from `main` branch confirmed working
