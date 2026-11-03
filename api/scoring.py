from __future__ import annotations

from db.models import CompanyInsight, Lead


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


def score_sales_readiness(
    lead: Lead,
    insight: CompanyInsight | None,
    *,
    recent_activity_count: int,
    conversation_count: int,
) -> tuple[int, str, dict[str, int], dict[str, str]]:
    has_needs = bool(insight and insight.potential_needs)
    has_opportunities = bool(insight and insight.opportunities)
    status_readiness = {
        "New": 0,
        "Contacted": 3,
        "Qualified": 6,
        "Proposal": 8,
        "Won": 10,
        "Lost": 0,
    }.get(lead.lead_status, 0)
    factors = {
        "fit": (10 if lead.industry else 0) + (15 if has_opportunities else 0),
        "engagement": min(max(recent_activity_count, 0), 4) * 5
        + (5 if lead.lead_status != "New" and lead.lead_status != "Lost" else 0),
        "intent": (15 if has_needs else 0)
        + (5 if has_opportunities else 0)
        + (5 if conversation_count else 0),
        "decision_readiness": (5 if lead.contact_name else 0)
        + (5 if lead.email else 0)
        + (5 if lead.phone else 0)
        + status_readiness,
    }
    score = sum(factors.values())
    score_label = "high" if score >= 70 else "moderate" if score >= 40 else "low"
    rationale = (
        f"Estimated sales-readiness score {score}/100 "
        f"({score_label}) based on fit, recorded engagement, intent signals, "
        "and decision readiness. This rule-based estimate is not a calibrated "
        "conversion probability; validate it against labeled outcomes before "
        "using it as a predictive measure."
    )
    recommendation = recommend_next_action(
        lead,
        recent_activity_count=recent_activity_count,
        has_needs=has_needs,
        score_label=score_label,
    )
    return score, rationale, factors, recommendation


def recommend_next_action(
    lead: Lead,
    *,
    recent_activity_count: int,
    has_needs: bool,
    score_label: str,
) -> dict[str, str]:
    if lead.lead_status == "Won":
        return {
            "action": "Coordinate the customer handoff and onboarding.",
            "timing": "Next business day",
            "channel": "Internal handoff",
            "rationale": "The lead is marked Won, so prospecting follow-up is complete.",
        }
    if lead.lead_status == "Lost":
        return {
            "action": "Review the loss reason before considering future re-engagement.",
            "timing": "Before any future outreach",
            "channel": "Internal review",
            "rationale": "The lead is marked Lost; do not send an automatic follow-up.",
        }
    if not lead.email and not lead.phone:
        return {
            "action": "Add a verified contact method before outreach.",
            "timing": "Before outreach",
            "channel": "Contact research",
            "rationale": "No email address or phone number is available.",
        }
    if lead.lead_status == "Proposal":
        return {
            "action": "Confirm the decision timeline and address proposal questions.",
            "timing": "Within 2 business days",
            "channel": "Email" if lead.email else "Phone",
            "rationale": "The lead is in the Proposal stage and needs a clear next step.",
        }
    if lead.lead_status == "Qualified":
        return {
            "action": "Schedule a discovery follow-up around the identified needs.",
            "timing": "Within 1 business day",
            "channel": "Email" if lead.email else "Phone",
            "rationale": "The lead is qualified; use verified insight signals to guide follow-up."
            if has_needs
            else "The lead is qualified; confirm needs during a discovery follow-up.",
        }
    if recent_activity_count == 0:
        return {
            "action": "Prepare a personalized introduction and ask for a short discovery meeting.",
            "timing": "Today",
            "channel": "Email" if lead.email else "Phone",
            "rationale": "No engagement activity is recorded in the last 30 days.",
        }
    if score_label == "high" and has_needs:
        return {
            "action": "Follow up with a specific question about the identified need.",
            "timing": "Within 1 business day",
            "channel": "Email" if lead.email else "Phone",
            "rationale": "Recent engagement and an identified need support a focused follow-up.",
        }
    return {
        "action": "Record the outcome and agree on a clear next step with the prospect.",
        "timing": "Within 2 business days",
        "channel": "Email" if lead.email else "Phone",
        "rationale": "Recent engagement is present; continue the conversation with a specific next step.",
    }
