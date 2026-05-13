"""Translate a Scenario into a GetRatesOp request body."""
from __future__ import annotations

from typing import Any

from app.models import LoanType, Occupancy, PropertyType, Purpose, Scenario

_PURPOSE_ORDINAL = {Purpose.REFI: 0, Purpose.PURCHASE: 1, Purpose.CASHOUT: 2}
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


def scenario_to_request(s: Scenario, lender_id: int) -> dict[str, Any]:
    """Build a GetRatesOp body for the given scenario and lender id.

    Many fields (state, zip, county, AMI, etc.) are not part of our v1 Scenario.
    v1 ships a fixed example county block — multi-state support is deferred.
    """
    return {
        "get_all_rates": True,
        "loan_amount": int(s.loan_amount),
        "property_value": int(s.property_value),
        "credit_score": s.credit_score,
        "impounds": True,
        "purpose": _PURPOSE_ORDINAL[s.purpose],
        "occupancy": _OCCUPANCY_ORDINAL[s.occupancy],
        "loan_type": _LOAN_TYPE_ORDINAL[s.loan_type],
        "property_type": _PROPERTY_ORDINAL[s.property_type],
        "state": "VA",
        "zip": "20155",
        "county_name": "Prince William",
        "has_equity_loan": False,
        "super_conf_limit": 1249125,
        "alert_lender": lender_id,
        "alert_lenders": [lender_id],
        "attachment_type": 1,
        "waive_lender_fee": False,
        "debt_to_income": 40,
        "total_number_properties": 3,
        "actual_number_of_units": 1,
        "borrower_paid_compensation": 1,
        "compensation_type": 1,
        "has_self_employed": False,
        "first_time_home_buyer": False,
        "income_to_ami": 0,
        "ami": 162000,
        "lock_period": 30,
        "total_loan_amount": int(s.loan_amount),
        "loan_program_group": _LOAN_PROGRAM_GROUP_ORDINAL[s.loan_program],
        "channel": None,
        "kind": "Rate",
        "is_paid_for_va_sponsorship": False,
        "transaction_id": None,
        "manual_closing_cost_adjustment": None,
        "loan_additional_adjustment": None,
        "purchase_plus_geographic_eligibility": None,
        "purchase_plus_checked_address": None,
        # county object is hardcoded in v1; deferred to a future task
        "countyLimit": None,
    }
