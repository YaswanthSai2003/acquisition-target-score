from __future__ import annotations

import sqlite3
from typing import Any

from app.scoring import (
    LeadFinancials, OwnerAgeBracket, OwnershipType, ScoreResult,
    assess_diligence_evidence, compute_ats_score,
)


def row_to_financials(row: sqlite3.Row) -> LeadFinancials:
    return LeadFinancials(
        industry=row["industry"],
        years_in_business=row["years_in_business"],
        ownership_type=OwnershipType(row["ownership_type"]),
        owner_age_bracket=OwnerAgeBracket(row["owner_age_bracket"]),
        has_successor_involved=(
            None if row["has_successor_involved"] is None else bool(row["has_successor_involved"])
        ),
        estimated_annual_revenue=row["estimated_annual_revenue"],
        estimated_ebitda_margin=row["estimated_ebitda_margin"],
    )


def score_result_to_dict(result: ScoreResult) -> dict[str, Any]:
    return {
        "total_score": result.total_score,
        "tier": result.tier,
        "factors": [
            {
                "name": f.name,
                "weight": f.weight,
                "raw_score": round(f.raw_score, 1),
                "points": round(f.points, 1),
                "rationale": f.rationale,
            }
            for f in result.factors
        ],
    }


def lead_row_to_summary_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Lightweight shape for table/list views - score but no factor breakdown."""
    result = compute_ats_score(row_to_financials(row))
    return {
        "id": row["id"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "city": row["city"],
        "state": row["state"],
        "employee_count": row["employee_count"],
        "estimated_annual_revenue": row["estimated_annual_revenue"],
        "years_in_business": row["years_in_business"],
        "ownership_type": row["ownership_type"],
        "ats_score": result.total_score,
        "ats_tier": result.tier,
    }


def lead_row_to_detail_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Full shape for the detail drawer - score plus evidence coverage."""
    financials = row_to_financials(row)
    result = compute_ats_score(financials)
    evidence = assess_diligence_evidence(financials, row["source_note"])
    return {
        "id": row["id"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "city": row["city"],
        "state": row["state"],
        "employee_count": row["employee_count"],
        "estimated_annual_revenue": row["estimated_annual_revenue"],
        "estimated_ebitda_margin": row["estimated_ebitda_margin"],
        "years_in_business": row["years_in_business"],
        "ownership_type": row["ownership_type"],
        "owner_age_bracket": row["owner_age_bracket"],
        "has_successor_involved": (
            None if row["has_successor_involved"] is None else bool(row["has_successor_involved"])
        ),
        "website": row["website"],
        "source_note": row["source_note"],
        "score": score_result_to_dict(result),
        "evidence": {
            "confidence_score": evidence.confidence_score,
            "label": evidence.label,
            "known_signals": evidence.known_signals,
            "gaps": evidence.gaps,
            "next_action": evidence.next_action,
            "caveat": evidence.caveat,
        },
    }
