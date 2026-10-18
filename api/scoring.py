from __future__ import annotations

from db.models import Lead


def score_lead(
    lead: Lead, summary: str, potential_needs: list[str], opportunities: list[str]
) -> tuple[int, str, dict[str, int]]:
    factors = {
        "industry_provided": 15 if lead.industry else 0,
        "contact_identified": 15 if lead.contact_name else 0,
        "email_available": 15 if lead.email else 0,
        "phone_available": 10 if lead.phone else 0,
        "analysis_summary_available": 10 if summary.strip() else 0,
        "potential_needs_identified": 15 if potential_needs else 0,
        "opportunities_identified": 20 if opportunities else 0,
    }
    score = sum(factors.values())
    evidence = ", ".join(
        f"{name.replace('_', ' ')} (+{points})"
        for name, points in factors.items()
        if points
    )
    rationale = (
        f"Estimated qualification score {score}/100 based on available lead details "
        f"and analysis signals: {evidence or 'no qualifying information provided'}. "
        "This transparent completeness/fit heuristic is not a predicted conversion "
        "probability or an accuracy claim."
    )
    return score, rationale, factors
