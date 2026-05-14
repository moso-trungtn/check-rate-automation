"""Translate a Scenario into a GetRatesOp request body."""
from __future__ import annotations

from typing import Any

from app.models import (
    AttachmentType,
    CompensationType,
    LoanType,
    Occupancy,
    PropertyType,
    Purpose,
    Scenario,
)

# Verified empirically against /exec/GetRatesOp for AD Mortgage:
#   0 → Refinance     (response has "Refinance Rate/Term Fico Ltv Adjustments")
#   1 → Cash Out      (response has "Cash Out Fico Ltv Adjustments")
#   2 → Purchase      (response has "Purchase Fico Ltv Adjustments")
_PURPOSE_ORDINAL = {Purpose.REFI: 0, Purpose.CASHOUT: 1, Purpose.PURCHASE: 2}
_OCCUPANCY_ORDINAL = {Occupancy.PRIMARY: 0, Occupancy.SECOND: 1, Occupancy.INVESTMENT: 2}
_PROPERTY_ORDINAL = {
    PropertyType.SFR: 0,
    PropertyType.CONDO: 1,
    PropertyType.PUD: 2,
    PropertyType.TWO_TO_FOUR: 3,
}
_LOAN_TYPE_ORDINAL = {LoanType.CONVENTIONAL: 0}

# v1 only handles 30yr Fixed Conv. Group ordinal 2 was observed in the live request.
_LOAN_PROGRAM_GROUP_ORDINAL: dict[str, int] = {"30yr Fixed Conv": 2}

# MOSO uses 0 for detached / 1 for attached on condo & PUD.
_ATTACHMENT_ORDINAL = {AttachmentType.DETACHED: 1, AttachmentType.ATTACHED: 0}

# MOSO uses 1 for borrower-paid / 0 for lender-paid.
_COMP_TYPE_ORDINAL = {
    CompensationType.BORROWER_PAID: 1,
    CompensationType.LENDER_PAID: 0,
}


def scenario_to_request(s: Scenario, lender_id: int) -> dict[str, Any]:
    """Build a GetRatesOp body for the given scenario and lender id.

    Many fields (state, zip, county, AMI, etc.) are not part of our v1 Scenario.
    v1 ships a fixed example county block — multi-state support is deferred.
    """
    return {
        "get_all_rates": True,
        # ----- Loan basics -----
        "loan_amount": int(s.loan_amount),
        "property_value": int(s.property_value),
        "credit_score": s.credit_score,
        "purpose": _PURPOSE_ORDINAL[s.purpose],
        "occupancy": _OCCUPANCY_ORDINAL[s.occupancy],
        "loan_type": _LOAN_TYPE_ORDINAL[s.loan_type],
        "property_type": _PROPERTY_ORDINAL[s.property_type],
        # ----- Location -----
        "state": s.state,
        "zip": s.zip,
        "county_name": s.county_name,
        # ----- Borrower profile -----
        "debt_to_income": s.debt_to_income,
        "first_time_home_buyer": s.first_time_home_buyer,
        "has_self_employed": s.has_self_employed,
        "total_number_properties": s.total_number_properties,
        "financed_properties": s.financed_properties,
        # ----- Property detail -----
        "actual_number_of_units": s.actual_number_of_units,
        "attachment_type": _ATTACHMENT_ORDINAL[s.attachment_type],
        # ----- Loan options -----
        "lock_period": s.lock_period,
        "impounds": s.impounds,
        "has_equity_loan": s.has_equity_loan,
        "waive_lender_fee": s.waive_lender_fee,
        # ----- Compensation -----
        "compensation_type": _COMP_TYPE_ORDINAL[s.compensation_type],
        "borrower_paid_compensation": float(s.borrower_paid_compensation),
        # ----- Lender selection -----
        "alert_lender": lender_id,
        "alert_lenders": [lender_id],
        # ----- Loan program / target -----
        "total_loan_amount": int(s.loan_amount),
        "loan_program_group": _LOAN_PROGRAM_GROUP_ORDINAL[s.loan_program],
        # ----- Defaults (not on v1 form) -----
        "super_conf_limit": 1249125,
        "income_to_ami": 0,
        "ami": 162000,
        "channel": None,
        "kind": "Rate",
        "is_paid_for_va_sponsorship": False,
        "transaction_id": None,
        "manual_closing_cost_adjustment": None,
        "loan_additional_adjustment": None,
        "purchase_plus_geographic_eligibility": None,
        "purchase_plus_checked_address": None,
        "countyLimit": None,
    }
