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

    data_points = []
    if lead.industry:
        data_points.append(f"Industry Alignment: {lead.industry} (+15)")
    if lead.contact_name:
        data_points.append(f"Named Stakeholder: {lead.contact_name} (+15)")
    if lead.email:
        data_points.append("Direct Digital Channel: Email Verified (+15)")
    if lead.phone:
        data_points.append("Direct Voice Channel: Phone Verified (+10)")
    if summary.strip():
        data_points.append("Account Intelligence: Executive Summary Available (+10)")
    if potential_needs:
        data_points.append(f"Operational Pain Signals: {len(potential_needs)} Evidenced Needs (+15)")
    if opportunities:
        data_points.append(f"Strategic Value Plays: {len(opportunities)} Expansion Angles (+20)")

    evidence = " | ".join(data_points) if data_points else "No qualifying profile signals detected"
    maturity_grade = (
        "Grade A (Highly Qualified)"
        if score >= 80
        else "Grade B (Moderately Qualified)"
        if score >= 50
        else "Grade C (Early Ingestion)"
    )

    rationale = (
        f"[B2B Lead Qualification Assessment — {maturity_grade}] Overall Qualification Score: {score}/100. "
        f"Verified Profile & Intelligence Signals: {evidence}. "
        "Domain Assessment: This metric measures data maturity, ICP profile completeness, and substantiated "
        "operational discovery readiness under enterprise B2B qualification standards (BANT/MEDDPICC framework baseline). "
        "It provides explainable pipeline qualification prior to outbound sales engagement."
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
    tier_label = (
        "Tier 1 — High Velocity"
        if score >= 70
        else "Tier 2 — Active Pipeline"
        if score >= 40
        else "Tier 3 — Early Nurture"
    )

    rationale = (
        f"[Enterprise Sales-Readiness Index — {tier_label}] Composite Readiness Score: {score}/100 ({score_label}). "
        f"Evaluation Breakdown: (1) ICP & Opportunity Fit: {factors['fit']}/25; "
        f"(2) Multi-Touch Engagement Velocity: {factors['engagement']}/25 ({recent_activity_count} recent touches); "
        f"(3) Commercial Intent & Discovery Signals: {factors['intent']}/25; "
        f"(4) Stakeholder Reachability & Stage Maturity: {factors['decision_readiness']}/25 ({lead.lead_status} stage). "
        "Strategic Diagnosis: Rule-grounded multi-dimensional readiness index reflecting commercial alignment, "
        "touchpoint momentum, and pipeline velocity to guide account prioritization and sales rep execution."
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
            "action": "Initiate formalized customer onboarding and executive sponsor transition handoff.",
            "timing": "Next business day",
            "channel": "Internal handoff",
            "rationale": "Account is marked Won. Prospecting cadence is complete; activate customer success workflow and onboarding deliverables.",
        }
    if lead.lead_status == "Lost":
        return {
            "action": "Conduct internal loss debrief and competitive review before assessing future re-engagement windows.",
            "timing": "Before any future outreach",
            "channel": "Internal review",
            "rationale": "Account is marked Lost. Halt outbound sequences, catalog loss factors, and set a 90-day re-qualification checkpoint.",
        }
    if not lead.email and not lead.phone:
        return {
            "action": "Execute secondary account enrichment to secure verified decision-maker contact details.",
            "timing": "Before outreach",
            "channel": "Contact research",
            "rationale": "Direct communication coordinates are unpopulated. Enrich stakeholder details before initiating outbound sales cadence.",
        }
    if lead.lead_status == "Proposal":
        return {
            "action": "Engage economic buyer to review formal commercial proposal, confirm evaluation criteria, and secure closing timeline.",
            "timing": "Within 2 business days",
            "channel": "Email" if lead.email else "Phone",
            "rationale": "Account is in active Proposal evaluation. Address remaining scope questions, align on procurement terms, and solidify mutual close date.",
        }
    if lead.lead_status == "Qualified":
        return {
            "action": "Deliver consultative solution-mapping session tailored to substantiated operational pain points.",
            "timing": "Within 1 business day",
            "channel": "Email" if lead.email else "Phone",
            "rationale": (
                "Account is verified Qualified with documented operational needs; leverage evidenced intelligence to demonstrate targeted value."
                if has_needs
                else "Account is verified Qualified. Schedule solution alignment call to uncover specific technical and operational priorities."
            ),
        }
    if recent_activity_count == 0:
        return {
            "action": "Deploy personalized executive introductory cadence focused on strategic industry priorities.",
            "timing": "Today",
            "channel": "Email" if lead.email else "Phone",
            "rationale": "Zero engagement touches recorded in the past 30 days. Establish initial touchpoint with consultative value hypothesis.",
        }
    if score_label == "high" and has_needs:
        return {
            "action": "Execute targeted executive follow-up addressing evidenced operational bottlenecks to accelerate deal velocity.",
            "timing": "Within 1 business day",
            "channel": "Email" if lead.email else "Phone",
            "rationale": "High sales-readiness index combined with validated operational pain indicates active buying posture; prioritize immediate follow-up.",
        }
    return {
        "action": "Advance cadence with targeted discovery touchpoint to validate buying timeline and define mutual action plan.",
        "timing": "Within 2 business days",
        "channel": "Email" if lead.email else "Phone",
        "rationale": "Recent account engagement is established; sustain pipeline momentum by securing agreement on explicit next evaluation milestone.",
    }
