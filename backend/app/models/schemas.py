"""Input/output dataclasses for the calculator."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

Channel = Literal["postal", "express", "general_cargo"]
Regime = Literal[
    "e3_simplified", "standard_tariff", "standard_tariff_fta",
    "no_duty", "pre_e3_de_minimis",
]
DeclarationType = Literal["H1", "H6", "H7"]
Declarant = Literal[
    "platform", "seller", "carrier", "postal_operator", "agent", "consumer",
]


@dataclass
class Item:
    """Line item in a consignment.

    Per DA C(2026)2760 Art. 1(1)(b)(61), an item is one or more goods sharing
    the same (tariff_classification, description, origin) tuple.
    """
    hs6: str
    description: str = ""
    origin: str = "UNKNOWN"
    qty: int = 1
    unit_value_eur: Decimal = Decimal("0.00")
    fta_proof_held: bool = False
    # Deprecated: used only for no_duty regime detection; Avalara is authoritative for figures.
    standard_duty_rate: Decimal = Decimal("0.00")
    fta_duty_rate: Decimal = Decimal("0.00")
    # Identifiers (mandatory from 1 Nov 2026)
    merchant_id: Optional[str] = None
    manufacturer_id: Optional[str] = None
    gtin: Optional[str] = None

    @property
    def line_value_eur(self) -> Decimal:
        return Decimal(self.qty) * self.unit_value_eur

    @property
    def grouping_key(self) -> tuple[str, str, str]:
        return (self.hs6, self.description.lower().strip(), self.origin.upper())


@dataclass
class Consignment:
    items: list[Item]
    destination_ms: str
    b2b: Optional[bool] = None
    ioss_registered: Optional[bool] = None
    buyer_agent: Optional[bool] = None
    incoterm: Optional[str] = None
    channel: Channel = "express"
    postal_designated_op: Optional[bool] = None
    transaction_date: Optional[date] = None
    intrinsic_value_eur: Optional[Decimal] = None
    ship_from: Optional[str] = None
    non_alteration_confirmed: bool = False
    # Avalara passthrough metadata
    avalara_doc_code: Optional[str] = None
    customer_vat_number: Optional[str] = None

    def __post_init__(self) -> None:
        self.destination_ms = self.destination_ms.upper()


@dataclass
class DefaultApplied:
    field: str
    default: object
    rationale: str


@dataclass
class ItemBreakdown:
    grouping_key: tuple
    qty_total: int
    line_value_eur: Decimal
    regime: Regime
    duty_eur: Decimal
    notes: list[str] = field(default_factory=list)
    avalara_rate: Decimal = Decimal("0.00")
    avalara_is_preferential: bool = False
    avalara_details: list[dict] = field(default_factory=list)


@dataclass
class FeeBreakdown:
    union_handling_fee_eur: Decimal = Decimal("0.00")
    national_fee_eur: Decimal = Decimal("0.00")
    national_fee_source: Optional[str] = None


@dataclass
class VATBreakdown:
    vat_rate: Decimal
    vat_base_eur: Decimal
    vat_eur: Decimal
    collected_via: Literal[
        "ioss_at_checkout", "import_clearance",
        "special_arrangements", "oss_b2b", "none",
    ]


@dataclass
class CalculationResult:
    consignment_value_eur: Decimal
    duty_total_eur: Decimal
    item_breakdown: list[ItemBreakdown]
    fees: FeeBreakdown
    vat: VATBreakdown
    declaration_type: DeclarationType
    declarant: Declarant
    landed_cost_eur: Decimal
    defaults_applied: list[DefaultApplied] = field(default_factory=list)
    compliance_warnings: list[str] = field(default_factory=list)
    legal_references: list[str] = field(default_factory=list)
    avalara_request_id: str = ""
    avalara_total_eur: Decimal = Decimal("0.00")
    avalara_messages: list[str] = field(default_factory=list)
