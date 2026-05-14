"""Pydantic data models for check-rate."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Occupancy(StrEnum):
    PRIMARY = "primary_residence"
    SECOND = "second_home"
    INVESTMENT = "investment"


class PropertyType(StrEnum):
    SFR = "single_family"
    CONDO = "condo"
    PUD = "pud"
    TWO_TO_FOUR = "2_to_4_unit"


class Purpose(StrEnum):
    PURCHASE = "purchase"
    REFI = "refinance"
    CASHOUT = "cashout"


class LoanType(StrEnum):
    CONVENTIONAL = "conventional"


class AttachmentType(StrEnum):
    """For condos / PUDs: detached vs. attached structure."""
    DETACHED = "detached"
    ATTACHED = "attached"


class CompensationType(StrEnum):
    BORROWER_PAID = "borrower_paid"
    LENDER_PAID = "lender_paid"


class Scenario(BaseModel):
    # ----- Loan basics (all required) -----
    loan_amount: Decimal = Field(gt=0)
    credit_score: int = Field(ge=300, le=850)
    property_value: Decimal = Field(gt=0)
    ltv: Decimal = Field(gt=0, le=Decimal("200"))
    occupancy: Occupancy
    property_type: PropertyType
    purpose: Purpose
    loan_program: str
    loan_type: LoanType
    target_rate: Decimal = Field(gt=0, le=Decimal("30"))

    # ----- Location -----
    state: str = "VA"
    zip: str = "20155"
    county_name: str = "Prince William"

    # ----- Borrower profile -----
    debt_to_income: int = Field(default=40, ge=0, le=100)
    first_time_home_buyer: bool = False
    has_self_employed: bool = False
    total_number_properties: int = Field(default=1, ge=1, le=20)
    financed_properties: int = Field(default=1, ge=1, le=20)

    # ----- Property detail -----
    actual_number_of_units: int = Field(default=1, ge=1, le=4)
    attachment_type: AttachmentType = AttachmentType.DETACHED

    # ----- Loan pricing options -----
    lock_period: int = Field(default=30, ge=15, le=90)  # days
    impounds: bool = True
    has_equity_loan: bool = False
    waive_lender_fee: bool = False

    # ----- Broker compensation -----
    compensation_type: CompensationType = CompensationType.BORROWER_PAID
    borrower_paid_compensation: Decimal = Field(default=Decimal("1.0"), ge=0, le=10)


class Adjustment(BaseModel):
    label: str
    amount: Decimal


class MosoResult(BaseModel):
    base_price: Decimal
    adjustment_total: Decimal
    final_price: Decimal
    adjustments: list[Adjustment]
    source: Literal["moso"] = "moso"


class PortalResult(BaseModel):
    final_price: Decimal
    adjustments: list[Adjustment]
    raw_html_snapshot_path: str
    captured_at: datetime
    source: Literal["portal"] = "portal"


class Mismatch(BaseModel):
    field: str
    moso_value: Decimal | None
    portal_value: Decimal | None
    delta: Decimal | None


class ComparisonReport(BaseModel):
    id: str
    scenario: Scenario
    lender: str
    moso: MosoResult
    portal: PortalResult
    matches: bool
    mismatches: list[Mismatch]
    generated_at: datetime
