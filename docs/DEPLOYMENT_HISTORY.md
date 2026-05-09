# Deployment History

Per deploy skill convention: every production push gets logged here.

## v0.1.0 — 2026-05-09

**Type:** initial | **Platforms:** Render | **Deployed by:** [your-handle]
**Commits:** initial commit
**Changes:**
- [feature] €3 simplified duty calculation per DA C(2026)2760
- [feature] FTA exclusion for €3 regime per DA Art. 1(1)(a)
- [feature] Item grouping by (HS6, description, origin) tuple
- [feature] Avalara getQuote payload adapter with surgical EU-2026 fields
- [feature] Centralized defaults engine (defaults.py — PRD §3.2 SoT)
- [feature] VAT routing across IOSS / special arrangements / standard / OSS B2B
- [feature] Union handling fee + FR/IT/RO national fees
- [feature] Strategy advisor — 6 alternatives ranked by landed cost
- [docs] PRD with explicit fallback behavior table (PRD §3.2)
- [docs] BRD with Avalara getQuote field additions

**Test coverage:** 3 test files, 40+ tests covering defaults / decision tree / API
**Rollback plan:** Revert via `git revert HEAD && git push origin main`, or use Render manual deploy to redeploy a previous commit.

## v0.2.0 — 2026-05-09

**Type:** minor | **Platforms:** Render + IONOS (Docker, port 8080) | **Deployed by:** CLI
**Changes:**
- [feature] Avalara `globalcompliance` integration — Avalara is now authoritative for D&T figures; €3 regime overrides when triggered
- [feature] `AvalaraError` propagates as HTTP 502 from `/api/calculate` and `/api/strategy`
- [feature] `avalara_request_id`, `avalara_total_eur`, `avalara_messages` in CalculationResult response
- [feature] Per-item `avalara_rate`, `avalara_is_preferential`, `avalara_details` in ItemBreakdown
- [feature] Direct-transport gate for FTA preference (ship_from == origin OR non_alteration_confirmed)
- [feature] Avalara baseline section in UI with Δ (engine vs Avalara), per-item rate, preferential flag, collapsible raw data
- [feature] Docker container on IONOS VPS at 74.208.74.249:8080 (`docker-compose.eu.yml`)
- [improvement] `standard_duty_rate` / `fta_duty_rate` on Item deprecated as calculation inputs (Avalara is now sole non-€3 source)
- [docs] PRD §FR-3 updated to Avalara-authoritative description; BRD §5 rewritten with actual contract
- [test] conftest.py autouse mock + test_avalara_client.py (9 tests) + test_route_avalara_failure.py (2 tests)

**Test coverage:** 6 test files, 73 tests
**Rollback plan:** `git revert` the Avalara integration commits; remove `avalara_client.py`; revert calculator.py import + calculate() to v0.1.0 version.
