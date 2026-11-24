"""Shared reference-data models (Phase 1 output, consumed by later phases).

Wherever a value could not be determined from the SAF-T file it is the literal ``UNKNOWN``
("unknown") — never None or 0 — so a reviewer can't mistake a gap for a real value.
Field names and ``to_dict()`` keys follow specs/001-phase1-saft-reader/contracts/saft_data.schema.json.
"""

from dataclasses import dataclass, field
from decimal import Decimal

UNKNOWN = "unknown"


def _num(value):
    """Decimal/number -> int when whole, else float; UNKNOWN and None pass through."""
    if value is None or value == UNKNOWN:
        return value
    d = Decimal(str(value))
    return int(d) if d == d.to_integral_value() else float(d)


@dataclass(frozen=True)
class Account:
    id: str
    description: str          # or UNKNOWN
    standard_account_id: str  # or UNKNOWN

    def to_dict(self):
        return {"id": self.id, "description": self.description,
                "standard_account_id": self.standard_account_id}


@dataclass(frozen=True)
class VatCode:
    code: str                          # "" only for the implicit blank entry
    percentage: Decimal | str          # or UNKNOWN
    description: str                   # or UNKNOWN
    standard_tax_code: str             # or UNKNOWN
    effective_date: str | None
    expiration_date: str | None
    source: str                        # "tax_table" | "implicit"

    def to_dict(self):
        return {"code": self.code, "percentage": _num(self.percentage),
                "description": self.description, "standard_tax_code": self.standard_tax_code,
                "effective_date": self.effective_date, "expiration_date": self.expiration_date,
                "source": self.source}


@dataclass(frozen=True)
class Supplier:
    id: str
    name: str                 # or UNKNOWN
    registration_number: str  # or UNKNOWN
    in_master_data: bool

    def to_dict(self):
        return {"id": self.id, "name": self.name,
                "registration_number": self.registration_number,
                "in_master_data": self.in_master_data}


@dataclass(frozen=True)
class Candidate:
    account_id: str
    account_description: str  # or UNKNOWN
    invoice_count: int
    share: Decimal

    def to_dict(self):
        return {"account_id": self.account_id, "account_description": self.account_description,
                "invoice_count": self.invoice_count, "share": _num(self.share)}


@dataclass(frozen=True)
class SupplierVatAccountMapping:
    supplier_id: str
    supplier_name: str             # or UNKNOWN
    vat_code: str
    account_id: str                # or UNKNOWN
    account_description: str       # or UNKNOWN
    share: Decimal | None          # None when account_id is UNKNOWN
    invoice_count: int
    candidates: tuple = field(default_factory=tuple)
    reason: str | None = None      # None when mapped

    def to_dict(self):
        return {"supplier_id": self.supplier_id, "supplier_name": self.supplier_name,
                "vat_code": self.vat_code,
                "account_id": self.account_id, "account_description": self.account_description,
                "share": _num(self.share), "invoice_count": self.invoice_count,
                "candidates": [c.to_dict() for c in self.candidates],
                "reason": self.reason}


@dataclass(frozen=True)
class SupplierAccountMapping:
    supplier_id: str
    supplier_name: str             # or UNKNOWN
    account_id: str                # or UNKNOWN
    account_description: str       # or UNKNOWN
    share: Decimal | None          # None when account_id is UNKNOWN
    invoice_count: int
    candidates: tuple = field(default_factory=tuple)
    reason: str | None = None      # None when mapped
    vat_codes_seen: tuple = field(default_factory=tuple)

    def to_dict(self):
        return {"supplier_id": self.supplier_id, "supplier_name": self.supplier_name,
                "account_id": self.account_id, "account_description": self.account_description,
                "share": _num(self.share), "invoice_count": self.invoice_count,
                "candidates": [c.to_dict() for c in self.candidates],
                "reason": self.reason, "vat_codes_seen": list(self.vat_codes_seen)}
