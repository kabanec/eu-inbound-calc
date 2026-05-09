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
