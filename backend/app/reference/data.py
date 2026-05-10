"""Reference data — phase dates, FTA partner list, fees, VAT rates.

Sourced from:
- Council Regulation (EU) 2026/382 of 11 February 2026
- Commission Delegated Regulation C(2026)2760 of 30 April 2026
- Council Directive 2006/112/EC
- Member State finance acts (FR LdF 2026, IT LdB 2026, RO OG 2025/137)

Last verified: 9 May 2026.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

# Phase dates ---------------------------------------------------------------
DATE_E3_START = date(2026, 7, 1)
DATE_PRODUCT_ID_MANDATORY = date(2026, 11, 1)
DATE_UNION_HANDLING_FEE = date(2026, 11, 1)
DATE_E3_SUNSET = date(2028, 7, 1)
DATE_SPECIAL_ARRANGEMENTS_END = date(2028, 7, 1)

# Core duty parameters ------------------------------------------------------
LOW_VALUE_THRESHOLD_EUR = Decimal("150.00")
E3_PER_ITEM_EUR = Decimal("3.00")

# FTA / customs union partners ----------------------------------------------
# Goods originating from these countries with valid FTA proof are EXCLUDED
# from the €3 regime per DA Art. 1(1)(a).
FTA_PARTNERS = frozenset({
    "TR", "AD", "SM",  # Customs unions
    "NO", "IS", "LI",  # EEA
    "GB", "CH", "KR", "JP", "CA", "VN", "SG", "MX", "CL", "ZA",
    "UA", "MD", "GE", "PE", "CO", "EC",
    "CR", "GT", "HN", "NI", "PA", "SV",
})

# National handling fees (live as of May 2026) ------------------------------
NATIONAL_FEES = {
    "FR": {
        "amount_eur": Decimal("2.00"),
        "basis": "per_hs6_line",
        "since": date(2026, 3, 1),
        "in_vat_base": False,
        "source": "Loi de finances pour 2026, Law n° 2026-103, Article 82",
        "source_url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000051224559",
        "official_name": "Taxe sur les petits colis (TPC)",
    },
    "IT": {
        "amount_eur": Decimal("2.00"),
        "basis": "per_parcel",
        "since": date(2026, 1, 1),
        "suspended_until": date(2026, 7, 1),  # introduced in law but suspended until Jul 1
        "in_vat_base": False,
        "source": "Italian Budget Law 2026, Law no. 199/2025, Article 1, paragraphs 126-128",
        "source_url": "https://www.gazzettaufficiale.it/eli/id/2025/12/31/25G00233/SG",
        "applies_to": "B2C and B2B",
    },
    "RO": {
        "amount_eur": Decimal("4.90"),  # 25 RON at reference exchange rate
        "basis": "per_parcel",
        "since": date(2026, 1, 1),
        "in_vat_base": False,
        "source": "Romanian Parliament, Law adopted 18 Nov 2025 (fiscal package)",
        "source_url": "https://taxsummaries.pwc.com/romania/corporate/other-taxes",
        "applies_to": "B2C only",
    },
}

UNION_HANDLING_FEE_EUR = Decimal("2.00")  # Effective 1 Nov 2026 (DATE_UNION_HANDLING_FEE); working assumption pending implementing act (Reg. (EU) 2026/382)

# Standard EU VAT rates (destination-MS), May 2026 --------------------------
VAT_RATES = {
    "AT": Decimal("0.20"), "BE": Decimal("0.21"), "BG": Decimal("0.20"),
    "HR": Decimal("0.25"), "CY": Decimal("0.19"), "CZ": Decimal("0.21"),
    "DK": Decimal("0.25"), "EE": Decimal("0.22"), "FI": Decimal("0.255"),
    "FR": Decimal("0.20"), "DE": Decimal("0.19"), "GR": Decimal("0.24"),
    "HU": Decimal("0.27"), "IE": Decimal("0.23"), "IT": Decimal("0.22"),
    "LV": Decimal("0.21"), "LT": Decimal("0.21"), "LU": Decimal("0.17"),
    "MT": Decimal("0.18"), "NL": Decimal("0.21"), "PL": Decimal("0.23"),
    "PT": Decimal("0.23"), "RO": Decimal("0.21"), "SK": Decimal("0.23"),
    "SI": Decimal("0.22"), "ES": Decimal("0.21"), "SE": Decimal("0.25"),
}

DECLARATION_TYPES = {
    "H1": "Standard release for free circulation",
    "H6": "Postal consignment (≤ €1,000)",
    "H7": "Low-value consignment ≤ €150 (simplified dataset)",
}
