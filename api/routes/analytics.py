from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from api.analytics import compute_analytics_summary
from api.deps import SessionDependency, _database_failure
from api.schemas import (
    AnalyticsPeriod,
    AnalyticsSummaryOut,
    FollowUpRecommendationOut,
    SalesAnalyticsSnapshotOut,
)
from db.models import SalesAnalytics

router = APIRouter()


@router.get(
    "/api/v1/analytics/summary",
    response_model=AnalyticsSummaryOut,
)
def get_analytics_summary(
    session: SessionDependency,
    period: AnalyticsPeriod = Query(default="all_time"),
    persist: bool = Query(default=False),
) -> AnalyticsSummaryOut:
    try:
        return compute_analytics_summary(session, period=period, persist=persist)
    except SQLAlchemyError as error:
        raise _database_failure(session, error) from error

@router.post(
    "/api/v1/analytics/refresh",
    response_model=AnalyticsSummaryOut,
    status_code=201,
)
def refresh_analytics_snapshot(
    session: SessionDependency,
    period: AnalyticsPeriod = Query(default="all_time"),
) -> AnalyticsSummaryOut:
    try:
        return compute_analytics_summary(session, period=period, persist=True)
    except SQLAlchemyError as error:
        raise _database_failure(session, error) from error

@router.get(
    "/api/v1/analytics/history",
    response_model=list[SalesAnalyticsSnapshotOut],
)
def list_analytics_history(
    session: SessionDependency,
    period: AnalyticsPeriod | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SalesAnalyticsSnapshotOut]:
    statement = select(SalesAnalytics)
    if period is not None:
        statement = statement.where(SalesAnalytics.period == period)
    rows = session.scalars(
        statement.order_by(
            SalesAnalytics.computed_at.desc(), SalesAnalytics.analytics_id.desc()
        ).limit(limit)
    ).all()
    return [SalesAnalyticsSnapshotOut.model_validate(row) for row in rows]

@router.get(
    "/api/v1/analytics/recommendations",
    response_model=list[FollowUpRecommendationOut],
)
def list_follow_up_recommendations(
    session: SessionDependency,
    period: AnalyticsPeriod = Query(default="all_time"),
    limit: int = Query(default=12, ge=1, le=50),
) -> list[FollowUpRecommendationOut]:
    summary = compute_analytics_summary(session, period=period, persist=False)
    return summary.follow_up_recommendations[:limit]
