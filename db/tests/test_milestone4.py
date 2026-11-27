from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.schemas import LeadCreate, LeadPatch
from db.database import create_database_engine
from db.models import (
    Activity,
    Base,
    CompanyInsight,
    ConversationSummary,
    Lead,
    LeadScore,
    SalesAnalytics,
)
from main import create_app


def _make_test_app():
    engine = create_database_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = create_app(engine=engine)
    return app, engine


def _route_endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route {method} {path} not found")


def test_analytics_summary_empty_db_does_not_fabricate_metrics() -> None:
    app, engine = _make_test_app()
    get_summary = _route_endpoint(app, "/api/v1/analytics/summary", "GET")
    try:
        with Session(engine) as session:
            data = get_summary(session=session, period="all_time", persist=False).model_dump(
                mode="json"
            )
        assert data["period"] == "all_time"
        kpis = data["kpis"]
        assert kpis["total_leads"] == 0
        assert kpis["won_leads"] == 0
        assert kpis["conversion_rate"] == 0.0
        assert kpis["pipeline_value"] == 0.0
        assert kpis["avg_response_time_hours"] is None
        assert kpis["avg_sales_cycle_days"] is None
        assert len(data["pipeline"]) == 5
        assert data["follow_up_recommendations"] == []
    finally:
        engine.dispose()


def test_analytics_kpis_pipeline_recommendations_and_persistence() -> None:
    app, engine = _make_test_app()
    create_lead = _route_endpoint(app, "/api/v1/leads", "POST")
    update_lead = _route_endpoint(app, "/api/v1/leads/{lead_id}", "PATCH")
    get_summary = _route_endpoint(app, "/api/v1/analytics/summary", "GET")
    refresh_snapshot = _route_endpoint(app, "/api/v1/analytics/refresh", "POST")
    list_history = _route_endpoint(app, "/api/v1/analytics/history", "GET")
    list_recs = _route_endpoint(app, "/api/v1/analytics/recommendations", "GET")

    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as session:
            # Verify optional estimated_value via create_lead and update_lead
            created = create_lead(
                payload=LeadCreate(
                    company_name="Acme Corp",
                    industry="Software",
                    contact_name="Alex Rivera",
                    email="alex@acme.test",
                    estimated_value=100_000.0,
                ),
                session=session,
            )
            updated = update_lead(
                lead_id=created.lead_id,
                payload=LeadPatch(estimated_value=120_000.0),
                session=session,
            )
            assert updated.estimated_value == 120_000.0

            lead_new = session.get(Lead, created.lead_id)
            assert lead_new is not None
            lead_new.created_at = now - timedelta(days=5)
            lead_new.updated_at = now - timedelta(days=5)

            lead_prop = Lead(
                company_name="TechCorp",
                industry="FinTech",
                contact_name="Sarah Johnson",
                email="sarah@techcorp.test",
                lead_status="Proposal",
                estimated_value=250_000.0,
                created_at=now - timedelta(days=10),
                updated_at=now - timedelta(hours=2),
            )
            lead_won = Lead(
                company_name="NexGen",
                industry="AI",
                contact_name="Jordan Lee",
                email="jordan@nexgen.test",
                lead_status="Won",
                estimated_value=350_000.0,
                created_at=now - timedelta(days=28),
                updated_at=now,
            )
            lead_lost = Lead(
                company_name="LostCo",
                industry="Retail",
                lead_status="Lost",
                estimated_value=999_000.0,
                created_at=now - timedelta(days=15),
                updated_at=now - timedelta(days=1),
            )
            session.add_all([lead_prop, lead_won, lead_lost])
            session.flush()

            # 2-hour response time on lead_prop, 4-hour response time on lead_won -> avg 3.0h
            session.add_all(
                [
                    Activity(
                        lead_id=lead_prop.lead_id,
                        activity_type="email",
                        details={"note": "Initial outreach"},
                        occurred_at=lead_prop.created_at + timedelta(hours=2),
                    ),
                    Activity(
                        lead_id=lead_won.lead_id,
                        activity_type="call",
                        details={"note": "Discovery call"},
                        occurred_at=lead_won.created_at + timedelta(hours=4),
                    ),
                    ConversationSummary(
                        lead_id=lead_prop.lead_id,
                        interaction_type="meeting",
                        summary="Discussed technical requirements.",
                        key_points=["SOC2 compliance needed"],
                        action_items=["Send security whitepaper and schedule technical call"],
                    ),
                    LeadScore(
                        lead_id=lead_prop.lead_id,
                        score=84,
                        rationale="Strong fit and active proposal.",
                        factors={"fit": 22, "engagement": 20, "intent": 22, "decision_readiness": 20},
                        recommendation={
                            "action": "Schedule technical review",
                            "timing": "Within 24 hours",
                            "channel": "call",
                            "rationale": "Proposal stage with high score",
                        },
                    ),
                    CompanyInsight(
                        lead_id=lead_new.lead_id,
                        summary="Acme Corp builds workflow tools.",
                        potential_needs=["Pipeline automation"],
                        opportunities=["Consolidate CRM reporting"],
                        qualification_score=70,
                        qualification_rationale="Good fit",
                    ),
                ]
            )
            session.commit()

            # 1. Summary endpoint
            body = get_summary(session=session, period="all_time", persist=False).model_dump(
                mode="json"
            )
            kpis = body["kpis"]
            assert kpis["total_leads"] == 4
            assert kpis["won_leads"] == 1
            assert kpis["lost_leads"] == 1
            assert kpis["active_leads"] == 2
            assert kpis["conversion_rate"] == 25.0
            # Pipeline excludes LostCo (999k) -> 120k + 250k + 350k = 720k
            assert kpis["pipeline_value"] == 720_000.0
            assert kpis["valued_leads_count"] == 3
            assert kpis["avg_response_time_hours"] == 3.0
            assert kpis["avg_sales_cycle_days"] == 28.0

            stages = {stage["stage"]: stage for stage in body["pipeline"]}
            assert stages["New"]["count"] == 1
            assert stages["Proposal"]["count"] == 1
            assert stages["Won"]["count"] == 1
            assert stages["Proposal"]["leads"][0]["company_name"] == "TechCorp"
            assert stages["Proposal"]["leads"][0]["latest_score"] == 84

            recs = body["follow_up_recommendations"]
            assert len(recs) >= 2
            assert recs[0]["company_name"] == "TechCorp"
            assert recs[0]["priority"] == "High Priority"
            assert "security whitepaper" in recs[0]["suggested_action"].lower()

            # 2. Persist snapshot via POST /api/v1/analytics/refresh
            refresh_body = refresh_snapshot(session=session, period="this_month").model_dump(
                mode="json"
            )
            assert refresh_body["analytics_id"] is not None

            # 3. Retrieve history from Sales_Analytics table
            history = list_history(session=session, period=None, limit=20)
            assert len(history) == 1
            assert history[0].analytics_id == refresh_body["analytics_id"]
            assert history[0].period == "this_month"

            # 4. Recommendations endpoint
            recs_out = list_recs(session=session, period="all_time", limit=12)
            assert len(recs_out) >= 2

            assert session.query(SalesAnalytics).count() == 1
    finally:
        engine.dispose()
