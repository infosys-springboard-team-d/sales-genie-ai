from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import (
    AnalyticsKpisOut,
    AnalyticsPeriod,
    AnalyticsSummaryOut,
    AutomationActivityItemOut,
    FollowUpRecommendationOut,
    LeadStatus,
    PipelineLeadCardOut,
    PipelineStageOut,
)
from db.models import (
    Activity,
    CompanyInsight,
    ConversationSummary,
    Lead,
    LeadScore,
    OutreachDraft,
    SalesAnalytics,
)


PIPELINE_STAGES: tuple[tuple[LeadStatus, str], ...] = (
    (LeadStatus.NEW, "New Leads"),
    (LeadStatus.CONTACTED, "Contacted"),
    (LeadStatus.QUALIFIED, "Qualified"),
    (LeadStatus.PROPOSAL, "Proposal"),
    (LeadStatus.WON, "Closed Won"),
)

PRIORITY_RANK = {"High Priority": 0, "Medium Priority": 1, "Low Priority": 2}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _period_bounds(
    period: AnalyticsPeriod, now: datetime
) -> tuple[datetime | None, datetime | None, datetime | None]:
    """Return (current_start, prev_start, prev_end) in UTC for the requested period."""
    utc_now = _ensure_utc(now)
    if period == "all_time":
        return None, None, None
    if period == "this_month":
        cur_start = utc_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_end = cur_start
        prev_month_day = cur_start - timedelta(days=1)
        prev_start = prev_month_day.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return cur_start, prev_start, prev_end
    if period == "this_quarter":
        quarter_month = ((utc_now.month - 1) // 3) * 3 + 1
        cur_start = utc_now.replace(
            month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        prev_end = cur_start
        prev_quarter_end = cur_start - timedelta(days=1)
        prev_quarter_month = ((prev_quarter_end.month - 1) // 3) * 3 + 1
        prev_start = prev_quarter_end.replace(
            month=prev_quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return cur_start, prev_start, prev_end
    # this_year
    cur_start = utc_now.replace(
        month=1, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    prev_end = cur_start
    prev_start = cur_start.replace(year=cur_start.year - 1)
    return cur_start, prev_start, prev_end


def _compute_kpis_for_leads(
    leads: list[Lead],
    first_activity_by_lead: dict[int, datetime],
) -> tuple[int, int, int, int, float, float, int, float | None, float | None]:
    total = len(leads)
    won = sum(1 for lead in leads if lead.lead_status == LeadStatus.WON.value)
    lost = sum(1 for lead in leads if lead.lead_status == LeadStatus.LOST.value)
    active = total - won - lost
    conversion_rate = round((won / total) * 100.0, 1) if total > 0 else 0.0

    pipeline_leads = [
        lead for lead in leads if lead.lead_status != LeadStatus.LOST.value
    ]
    valued_leads = [
        lead for lead in pipeline_leads if lead.estimated_value is not None
    ]
    pipeline_value = round(sum(float(lead.estimated_value or 0.0) for lead in valued_leads), 2)

    response_hours: list[float] = []
    for lead in leads:
        first_act = first_activity_by_lead.get(lead.lead_id)
        if first_act is not None:
            delta_sec = (
                _ensure_utc(first_act) - _ensure_utc(lead.created_at)
            ).total_seconds()
            if delta_sec >= 0:
                response_hours.append(delta_sec / 3600.0)
    avg_response_time = (
        round(sum(response_hours) / len(response_hours), 1)
        if response_hours
        else None
    )

    cycle_days: list[float] = []
    for lead in leads:
        if lead.lead_status == LeadStatus.WON.value:
            delta_sec = (
                _ensure_utc(lead.updated_at) - _ensure_utc(lead.created_at)
            ).total_seconds()
            cycle_days.append(max(0.0, delta_sec / 86400.0))
    avg_sales_cycle = (
        round(sum(cycle_days) / len(cycle_days), 1) if cycle_days else None
    )

    return (
        total,
        active,
        won,
        lost,
        conversion_rate,
        pipeline_value,
        len(valued_leads),
        avg_response_time,
        avg_sales_cycle,
    )


def build_follow_up_recommendations(
    leads: list[Lead],
    latest_score_by_lead: dict[int, LeadScore],
    latest_activity_by_lead: dict[int, Activity],
    latest_summary_by_lead: dict[int, ConversationSummary],
    latest_insight_by_lead: dict[int, CompanyInsight],
    now: datetime,
    limit: int = 12,
) -> list[FollowUpRecommendationOut]:
    utc_now = _ensure_utc(now)
    recommendations: list[FollowUpRecommendationOut] = []

    for lead in leads:
        if lead.lead_status in {LeadStatus.WON.value, LeadStatus.LOST.value}:
            continue

        score_row = latest_score_by_lead.get(lead.lead_id)
        activity_row = latest_activity_by_lead.get(lead.lead_id)
        summary_row = latest_summary_by_lead.get(lead.lead_id)
        insight_row = latest_insight_by_lead.get(lead.lead_id)
        score_val = score_row.score if score_row is not None else None

        contact_label = lead.contact_name or "the primary contact"
        days_since_activity = (
            (utc_now - _ensure_utc(activity_row.occurred_at)).total_seconds() / 86400.0
            if activity_row is not None
            else None
        )

        # 1. Open action items from a recent conversation summary
        if summary_row is not None and summary_row.action_items:
            first_action = str(summary_row.action_items[0]).strip()
            priority = (
                "High Priority"
                if lead.lead_status in {LeadStatus.PROPOSAL.value, LeadStatus.QUALIFIED.value}
                or (score_val is not None and score_val >= 70)
                else "Medium Priority"
            )
            channel = "call" if summary_row.interaction_type == "meeting" else "email"
            recommendations.append(
                FollowUpRecommendationOut(
                    lead_id=lead.lead_id,
                    company_name=lead.company_name,
                    contact_name=lead.contact_name,
                    lead_status=LeadStatus(lead.lead_status),
                    priority=priority,
                    title=f"Follow up with {lead.company_name}",
                    reason=f"Open {summary_row.interaction_type} action item for {contact_label}: {first_action}",
                    suggested_action=first_action,
                    recommended_channel=channel,
                    score=score_val,
                    timestamp=_ensure_utc(summary_row.created_at),
                )
            )
            continue

        # 2. Proposal or Qualified stage without recent activity
        if lead.lead_status == LeadStatus.PROPOSAL.value:
            reason = (
                f"{contact_label} is in Proposal stage with no logged follow-up in "
                f"{int(days_since_activity)}d."
                if days_since_activity is not None and days_since_activity >= 1
                else f"{lead.company_name} is in Proposal stage — confirm decision timeline with {contact_label}."
            )
            recommendations.append(
                FollowUpRecommendationOut(
                    lead_id=lead.lead_id,
                    company_name=lead.company_name,
                    contact_name=lead.contact_name,
                    lead_status=LeadStatus(lead.lead_status),
                    priority="High Priority",
                    title=f"Follow up with {lead.company_name}",
                    reason=reason,
                    suggested_action="Schedule a proposal review call to address requirements and next steps.",
                    recommended_channel="call",
                    score=score_val,
                    timestamp=_ensure_utc(
                        activity_row.occurred_at if activity_row else lead.updated_at
                    ),
                )
            )
            continue

        # 3. High-score lead needing outreach
        if score_row is not None and score_row.score >= 70:
            rec_data = score_row.recommendation or {}
            suggested_action = str(
                rec_data.get("action") or "Send personalized outreach referencing analyzed needs."
            )
            rec_channel = str(rec_data.get("channel") or "email")
            if rec_channel not in {"email", "call", "meeting", "review"}:
                rec_channel = "email"
            stale_note = (
                f"Last activity was {int(days_since_activity)} days ago."
                if days_since_activity is not None and days_since_activity >= 2
                else "No recent engagement logged yet."
                if activity_row is None
                else "High readiness score warrants prompt follow-up."
            )
            recommendations.append(
                FollowUpRecommendationOut(
                    lead_id=lead.lead_id,
                    company_name=lead.company_name,
                    contact_name=lead.contact_name,
                    lead_status=LeadStatus(lead.lead_status),
                    priority="High Priority",
                    title=f"Prioritize {lead.company_name}",
                    reason=f"Lead score {score_row.score}/100 ({lead.lead_status}). {stale_note}",
                    suggested_action=suggested_action,
                    recommended_channel=rec_channel,  # type: ignore[arg-type]
                    score=score_val,
                    timestamp=_ensure_utc(score_row.created_at),
                )
            )
            continue

        # 4. Analyzed company insight or moderate score awaiting outreach
        if insight_row is not None or (score_row is not None and score_row.score >= 40):
            opportunity = (
                str(insight_row.opportunities[0])
                if insight_row is not None and insight_row.opportunities
                else "Share tailored value proposition"
            )
            recommendations.append(
                FollowUpRecommendationOut(
                    lead_id=lead.lead_id,
                    company_name=lead.company_name,
                    contact_name=lead.contact_name,
                    lead_status=LeadStatus(lead.lead_status),
                    priority="Medium Priority",
                    title=f"Send tailored outreach to {lead.company_name}",
                    reason=f"Saved intelligence highlights opportunity: {opportunity}",
                    suggested_action="Draft an introductory email highlighting this opportunity.",
                    recommended_channel="email",
                    score=score_val,
                    timestamp=_ensure_utc(
                        insight_row.created_at if insight_row else lead.updated_at
                    ),
                )
            )
            continue

        # 5. New unengaged lead
        if lead.lead_status == LeadStatus.NEW.value and activity_row is None:
            recommendations.append(
                FollowUpRecommendationOut(
                    lead_id=lead.lead_id,
                    company_name=lead.company_name,
                    contact_name=lead.contact_name,
                    lead_status=LeadStatus(lead.lead_status),
                    priority="Low Priority",
                    title=f"Qualify {lead.company_name}",
                    reason=f"New prospect in {lead.industry or 'general'} sector with no analysis or activity yet.",
                    suggested_action="Run company analysis and log initial outreach.",
                    recommended_channel="review",
                    score=score_val,
                    timestamp=_ensure_utc(lead.created_at),
                )
            )

    recommendations.sort(
        key=lambda item: (
            PRIORITY_RANK[item.priority],
            -(item.score or 0),
            -item.timestamp.timestamp(),
        )
    )
    return recommendations[:limit]


def compute_analytics_summary(
    session: Session,
    *,
    period: AnalyticsPeriod = "all_time",
    persist: bool = False,
    now: datetime | None = None,
) -> AnalyticsSummaryOut:
    utc_now = _ensure_utc(now or datetime.now(timezone.utc))
    cur_start, prev_start, prev_end = _period_bounds(period, utc_now)

    all_leads = list(
        session.scalars(
            select(Lead).order_by(Lead.updated_at.desc(), Lead.lead_id.desc())
        ).all()
    )
    all_activities = list(
        session.scalars(
            select(Activity).order_by(Activity.occurred_at.asc(), Activity.activity_id.asc())
        ).all()
    )
    all_scores = list(
        session.scalars(
            select(LeadScore).order_by(LeadScore.created_at.desc(), LeadScore.score_id.desc())
        ).all()
    )
    all_summaries = list(
        session.scalars(
            select(ConversationSummary).order_by(
                ConversationSummary.created_at.desc(), ConversationSummary.summary_id.desc()
            )
        ).all()
    )
    all_insights = list(
        session.scalars(
            select(CompanyInsight).order_by(
                CompanyInsight.created_at.desc(), CompanyInsight.analysis_id.desc()
            )
        ).all()
    )
    recent_drafts = list(
        session.scalars(
            select(OutreachDraft)
            .order_by(OutreachDraft.created_at.desc(), OutreachDraft.draft_id.desc())
            .limit(5)
        ).all()
    )
    lead_by_id = {lead.lead_id: lead for lead in all_leads}

    first_activity_by_lead: dict[int, datetime] = {}
    latest_activity_by_lead: dict[int, Activity] = {}
    for act in all_activities:
        if act.lead_id not in first_activity_by_lead:
            first_activity_by_lead[act.lead_id] = act.occurred_at
        latest_activity_by_lead[act.lead_id] = act

    latest_score_by_lead: dict[int, LeadScore] = {}
    for score in all_scores:
        if score.lead_id not in latest_score_by_lead:
            latest_score_by_lead[score.lead_id] = score

    latest_summary_by_lead: dict[int, ConversationSummary] = {}
    for summary in all_summaries:
        if summary.lead_id is not None and summary.lead_id not in latest_summary_by_lead:
            latest_summary_by_lead[summary.lead_id] = summary

    latest_insight_by_lead: dict[int, CompanyInsight] = {}
    for insight in all_insights:
        if insight.lead_id not in latest_insight_by_lead:
            latest_insight_by_lead[insight.lead_id] = insight

    if cur_start is not None:
        period_leads = [
            lead for lead in all_leads if _ensure_utc(lead.created_at) >= cur_start
        ]
    else:
        period_leads = all_leads

    (
        total_leads,
        active_leads,
        won_leads,
        lost_leads,
        conversion_rate,
        pipeline_value,
        valued_leads_count,
        avg_response_time_hours,
        avg_sales_cycle_days,
    ) = _compute_kpis_for_leads(period_leads, first_activity_by_lead)

    conversion_rate_delta: float | None = None
    pipeline_value_delta_pct: float | None = None
    avg_response_time_delta_minutes: float | None = None
    avg_sales_cycle_delta_days: float | None = None

    if prev_start is not None and prev_end is not None:
        prev_leads = [
            lead
            for lead in all_leads
            if prev_start <= _ensure_utc(lead.created_at) < prev_end
        ]
        if prev_leads:
            (
                _pt,
                _pa,
                _pw,
                _pl,
                prev_conv,
                prev_pipe,
                _pvc,
                prev_resp,
                prev_cycle,
            ) = _compute_kpis_for_leads(prev_leads, first_activity_by_lead)
            conversion_rate_delta = round(conversion_rate - prev_conv, 1)
            if prev_pipe > 0:
                pipeline_value_delta_pct = round(
                    ((pipeline_value - prev_pipe) / prev_pipe) * 100.0, 1
                )
            if avg_response_time_hours is not None and prev_resp is not None:
                avg_response_time_delta_minutes = round(
                    (avg_response_time_hours - prev_resp) * 60.0, 0
                )
            if avg_sales_cycle_days is not None and prev_cycle is not None:
                avg_sales_cycle_delta_days = round(avg_sales_cycle_days - prev_cycle, 1)

    pipeline: list[PipelineStageOut] = []
    stage_breakdown: dict[str, Any] = {}
    for stage_enum, stage_label in PIPELINE_STAGES:
        stage_leads = [
            lead for lead in period_leads if lead.lead_status == stage_enum.value
        ]
        stage_total_val = round(
            sum(float(lead.estimated_value or 0.0) for lead in stage_leads), 2
        )
        cards = [
            PipelineLeadCardOut(
                lead_id=lead.lead_id,
                company_name=lead.company_name,
                contact_name=lead.contact_name,
                industry=lead.industry,
                lead_status=LeadStatus(lead.lead_status),
                estimated_value=lead.estimated_value,
                latest_score=(
                    latest_score_by_lead[lead.lead_id].score
                    if lead.lead_id in latest_score_by_lead
                    else None
                ),
                updated_at=_ensure_utc(lead.updated_at),
            )
            for lead in stage_leads[:50]
        ]
        pipeline.append(
            PipelineStageOut(
                stage=stage_enum,
                label=stage_label,
                count=len(stage_leads),
                total_value=stage_total_val,
                leads=cards,
            )
        )
        stage_breakdown[stage_enum.value] = {
            "label": stage_label,
            "count": len(stage_leads),
            "total_value": stage_total_val,
        }

    recommendations = build_follow_up_recommendations(
        period_leads if period_leads else all_leads,
        latest_score_by_lead=latest_score_by_lead,
        latest_activity_by_lead=latest_activity_by_lead,
        latest_summary_by_lead=latest_summary_by_lead,
        latest_insight_by_lead=latest_insight_by_lead,
        now=utc_now,
    )

    analytics_id: int | None = None
    computed_at = utc_now
    if persist:
        snapshot = SalesAnalytics(
            period=period,
            total_leads=total_leads,
            won_leads=won_leads,
            conversion_rate=conversion_rate,
            pipeline_value=pipeline_value,
            avg_response_time_hours=avg_response_time_hours,
            avg_sales_cycle_days=avg_sales_cycle_days,
            stage_breakdown=stage_breakdown,
            follow_up_recommendations=[
                rec.model_dump(mode="json") for rec in recommendations
            ],
            computed_at=utc_now,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        analytics_id = snapshot.analytics_id
        computed_at = _ensure_utc(snapshot.computed_at)

    kpis = AnalyticsKpisOut(
        total_leads=total_leads,
        active_leads=active_leads,
        won_leads=won_leads,
        lost_leads=lost_leads,
        conversion_rate=conversion_rate,
        conversion_rate_delta=conversion_rate_delta,
        pipeline_value=pipeline_value,
        pipeline_value_delta_pct=pipeline_value_delta_pct,
        valued_leads_count=valued_leads_count,
        avg_response_time_hours=avg_response_time_hours,
        avg_response_time_delta_minutes=avg_response_time_delta_minutes,
        avg_sales_cycle_days=avg_sales_cycle_days,
        avg_sales_cycle_delta_days=avg_sales_cycle_delta_days,
    )

    automation_items: list[AutomationActivityItemOut] = []
    for score in all_scores[:4]:
        lead_obj = lead_by_id.get(score.lead_id)
        if lead_obj is None:
            continue
        action_txt = (score.recommendation or {}).get("action") or score.rationale
        automation_items.append(
            AutomationActivityItemOut(
                kind="score",
                title=f"{lead_obj.company_name} · Lead readiness scored ({score.score}/100)",
                description=str(action_txt)[:140],
                timestamp=_ensure_utc(score.created_at),
                lead_id=lead_obj.lead_id,
            )
        )
    for summary in all_summaries[:4]:
        if summary.lead_id is None:
            continue
        lead_obj = lead_by_id.get(summary.lead_id)
        if lead_obj is None:
            continue
        automation_items.append(
            AutomationActivityItemOut(
                kind="conversation",
                title=f"{lead_obj.company_name} · {summary.interaction_type.title()} summarized",
                description=summary.summary[:140],
                timestamp=_ensure_utc(summary.created_at),
                lead_id=lead_obj.lead_id,
            )
        )
    for draft in recent_drafts:
        lead_obj = lead_by_id.get(draft.lead_id)
        if lead_obj is None:
            continue
        automation_items.append(
            AutomationActivityItemOut(
                kind="outreach",
                title=f"{lead_obj.company_name} · {draft.draft_type.title()} draft generated",
                description=draft.content.splitlines()[0][:140],
                timestamp=_ensure_utc(draft.created_at),
                lead_id=lead_obj.lead_id,
            )
        )
    for insight in all_insights[:4]:
        lead_obj = lead_by_id.get(insight.lead_id)
        if lead_obj is None:
            continue
        automation_items.append(
            AutomationActivityItemOut(
                kind="insight",
                title=f"{lead_obj.company_name} · Company intelligence analyzed",
                description=insight.summary[:140],
                timestamp=_ensure_utc(insight.created_at),
                lead_id=lead_obj.lead_id,
            )
        )
    automation_items.sort(key=lambda item: item.timestamp, reverse=True)

    return AnalyticsSummaryOut(
        period=period,
        analytics_id=analytics_id,
        computed_at=computed_at,
        kpis=kpis,
        pipeline=pipeline,
        follow_up_recommendations=recommendations,
        recent_automation_activity=automation_items[:5],
    )
