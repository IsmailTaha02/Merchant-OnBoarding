"""Replaceable analysis-provider contract and deterministic no-network adapter."""
from __future__ import annotations
from typing import Protocol

class AnalysisProvider(Protocol):
    def summarize(self, business: dict) -> dict: ...

class MockAnalysisProvider:
    """Safe fixture adapter; never claims to verify facts or make a risk decision."""
    def summarize(self, business: dict) -> dict:
        description=(business.get("description") or "Not provided")[:500]
        return {
            "summary": f"Applicant describes the business as: {description}",
            "salesChannel": "not specified" if not business.get("ecommercePercent") and not business.get("cardPresentPercent") else "Applicant-entered card-present/e-commerce split",
            "geography": business.get("operatingCountries") or business.get("formationCountry") or "not specified",
            "fulfillmentModel": business.get("fulfillmentModel") or "not specified",
            "recurringPayments": business.get("recurringPayments") or "not specified",
            "customerType": business.get("customerType") or "not specified",
            "sourceFields": [key for key in ("description", "cardPresentPercent", "cardNotPresentPercent", "ecommercePercent", "operatingCountries", "formationCountry", "fulfillmentModel", "recurringPayments", "customerType") if business.get(key)],
            "source": "deterministic-mock",
            "verified": False,
        }

def default_analysis_provider() -> AnalysisProvider:
    return MockAnalysisProvider()
