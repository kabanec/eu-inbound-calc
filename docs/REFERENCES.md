# EU Customs & VAT — Primary Sources Registry

**Last verified:** 9 May 2026

This file is the canonical citation registry for the EU Inbound Calculator.
All legal references used in code (`reference/data.py`), tests, and the UI modal must be traceable to an entry here.

---

## EU Legislation

| Key | Short | Full title | EUR-Lex / Official link |
|-----|-------|-----------|-------------------------|
| `reg_2026_382` | Reg. (EU) 2026/382 | Council Regulation (EU) 2026/382 of 11 February 2026 amending Reg. (EU) No 952/2013 (Union Customs Code) — new customs framework for low-value e-commerce | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32026R0382 |
| `da_c_2026_2760` | DA C(2026)2760 | Commission Delegated Regulation C(2026)2760 of 30 April 2026 — €3 per-item simplified duty fee and eligibility conditions for the e-commerce simplified regime | https://ec.europa.eu/taxation_customs/customs/key-policies/e-commerce_en |
| `ucc_952_2013` | UCC Reg. 952/2013 | Regulation (EU) No 952/2013 of the European Parliament and of the Council of 9 October 2013 laying down the Union Customs Code | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32013R0952 |
| `da_2015_2446` | DA (EU) 2015/2446 | Commission Delegated Regulation (EU) 2015/2446 of 28 July 2015 supplementing the Union Customs Code — H6 postal declaration procedures, Art. 143(1)(d) CP42 | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32015R2446 |
| `dir_2006_112` | VAT Directive 2006/112/EC | Council Directive 2006/112/EC of 28 November 2006 on the common system of value added tax | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=celex%3A32006L0112 |
| `ioss_dir_2017_2455` | IOSS Dir. 2017/2455/EU | Council Directive (EU) 2017/2455 of 5 December 2017 introducing the Import One-Stop Shop (IOSS) for distance sales of imported goods | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32017L2455 |

---

## National Legislation

### France — Taxe sur les petits colis (TPC)

| Field | Value |
|-------|-------|
| **Key** | `fr_ldf_2026` |
| **Short** | FR LdF 2026, Art. 82 |
| **Full** | Loi de finances pour 2026, Law n° 2026-103, Article 82 |
| **Official name** | Taxe sur les petits colis (TPC) |
| **Amount** | €2.00 per distinct HS6 line |
| **Basis** | per_hs6_line |
| **Effective** | 1 March 2026 |
| **VAT base** | Excluded (not added to VAT base) |
| **Link** | https://www.legifrance.gouv.fr/loda/id/JORFTEXT000051224559 |

### Italy — €2/parcel flat fee

| Field | Value |
|-------|-------|
| **Key** | `it_budget_2026` |
| **Short** | IT Budget Law 2026 §126-128 |
| **Full** | Italian Budget Law 2026, Law no. 199/2025, Article 1, paragraphs 126-128 |
| **Amount** | €2.00 per parcel (flat, regardless of HS lines) |
| **Basis** | per_parcel |
| **Originally enacted** | 1 January 2026 |
| **Suspended until** | 1 July 2026 (suspension confirmed by Italian Parliament) |
| **Applies to** | B2C and B2B |
| **VAT base** | Excluded |
| **Link** | https://www.gazzettaufficiale.it/eli/id/2025/12/31/25G00233/SG |
| **Secondary source** | https://www.twobirds.com/en/insights/2025/italy/italy-budget-law-2026 |

### Romania — Logistics tax

| Field | Value |
|-------|-------|
| **Key** | `ro_og_2025` |
| **Short** | RO Fiscal Package Nov 2025 |
| **Full** | Romanian Parliament, Law adopted 18 November 2025 (fiscal package) |
| **Amount** | 25 RON ≈ **€4.90** at reference exchange rate |
| **Basis** | per_parcel |
| **Effective** | 1 January 2026 |
| **Applies to** | B2C only |
| **VAT base** | Excluded |
| **Link** | https://taxsummaries.pwc.com/romania/corporate/other-taxes |

> **Note on RON→EUR:** The 25 RON figure is law-fixed. The EUR equivalent (€4.90) is calculated at the NBR reference rate of ~5.10 RON/EUR as of Jan 2026. This does not float with the exchange rate — the law specifies RON, the calculator uses the fixed EUR equivalent at enactment.

---

## Amounts summary (May 2026)

| Country | Amount | Basis | Status |
|---------|--------|-------|--------|
| 🇫🇷 France | €2.00 | per HS6 line | ✅ Active from 1 Mar 2026 |
| 🇮🇹 Italy | €2.00 | per parcel | ⏸ Suspended → 1 Jul 2026 |
| 🇷🇴 Romania | €4.90 | per parcel | ✅ Active from 1 Jan 2026 |

---

## Key dates

| Date | Event |
|------|-------|
| 1 Jan 2026 | Romania logistics tax effective |
| 1 Mar 2026 | France TPC effective |
| 1 Jul 2026 | Italy fee effective (suspension lifts) · EU €3 regime launches |
| 1 Nov 2026 | Union handling fee live · Product identifier mandatory |
| 1 Jul 2028 | €3 simplified regime sunset |
