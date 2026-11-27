from __future__ import annotations

import html

import streamlit as st

from ui.client import ApiRequestError, api_request, show_api_error
from ui.components import (
    _format_currency_compact,
    _format_relative_time,
    _jump_to_lead,
)


def render_dashboard() -> None:
    head_left, head_right = st.columns([2.6, 1.0], gap="medium")
    with head_left:
        st.markdown(
            """
            <div style="margin-bottom:0.6rem;">
                <div style="font-size:1.65rem; font-weight:800; color:#0f172a; line-height:1.15;">Dashboard &amp; Automation</div>
                <div style="font-size:0.88rem; color:#64748b; margin-top:0.2rem;">Sales analytics dashboard with automated follow-up recommendations</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    period_options = {
        "All Time": "all_time",
        "This Month": "this_month",
        "This Quarter": "this_quarter",
        "This Year": "this_year",
    }
    with head_right:
        selected_label = st.selectbox(
            "Period",
            list(period_options.keys()),
            key="dashboard_period",
            label_visibility="collapsed",
        )
        period_key = period_options.get(selected_label, "all_time")
        if st.button("Save Analytics Snapshot", use_container_width=True):
            try:
                snap = api_request(
                    "POST",
                    "/api/v1/analytics/refresh",
                    params={"period": period_key},
                )
                st.success(
                    f"Saved snapshot #{snap.get('analytics_id')} to Sales_Analytics."
                )
            except ApiRequestError as error:
                show_api_error(error)

    try:
        summary = api_request(
            "GET",
            "/api/v1/analytics/summary",
            params={"period": period_key},
        )
    except ApiRequestError as error:
        show_api_error(error)
        return

    kpis = summary["kpis"]
    conv_delta = kpis.get("conversion_rate_delta")
    conv_sub = (
        f"{'↑ +' if conv_delta >= 0 else '↓ '}{conv_delta:.1f}% from prior period"
        if conv_delta is not None
        else f"{kpis['won_leads']} of {kpis['total_leads']} leads won"
    )
    pipe_delta = kpis.get("pipeline_value_delta_pct")
    pipe_sub = (
        f"{'↑ +' if pipe_delta >= 0 else '↓ '}{pipe_delta:.1f}% from prior period"
        if pipe_delta is not None
        else f"{kpis['valued_leads_count']} valued deals"
    )
    resp_val = kpis.get("avg_response_time_hours")
    resp_display = f"{resp_val:.1f}h" if resp_val is not None else "—"
    resp_delta = kpis.get("avg_response_time_delta_minutes")
    resp_sub = (
        f"{resp_delta:+.0f} min vs prior period"
        if resp_delta is not None
        else ("From logged activities" if resp_val is not None else "No activity data yet")
    )
    cycle_val = kpis.get("avg_sales_cycle_days")
    cycle_display = f"{cycle_val:.0f} days" if cycle_val is not None else "—"
    cycle_delta = kpis.get("avg_sales_cycle_delta_days")
    cycle_sub = (
        f"{cycle_delta:+.1f} days vs prior period"
        if cycle_delta is not None
        else ("Created to Won average" if cycle_val is not None else "No closed won deals yet")
    )

    kpi_cards = [
        ("Conversion Rate", f"{kpis['conversion_rate']:.1f}%", conv_sub, "📈", "#ecfdf5", "#15803d"),
        ("Pipeline Value", _format_currency_compact(kpis["pipeline_value"]), pipe_sub, "💼", "#eff6ff", "#1d4ed8"),
        ("Avg Response Time", resp_display, resp_sub, "⏱️", "#f5f3ff", "#6d28d9"),
        ("Avg Sales Cycle", cycle_display, cycle_sub, "🕒", "#fff7ed", "#c2410c"),
    ]
    kpi_cols = st.columns(4, gap="medium")
    for col, (label, value, sub, icon, bg, fg) in zip(kpi_cols, kpi_cards):
        col.markdown(
            f"""
            <div class="sg-kpi-card" style="background:#ffffff;border:1px solid #dbe3ed;border-radius:14px;padding:1rem 1.1rem;display:flex;align-items:center;gap:0.9rem;margin-bottom:1rem;">
                <div style="width:2.5rem;height:2.5rem;border-radius:10px;display:grid;place-items:center;font-size:1.15rem;background:{bg};color:{fg};flex:0 0 auto;">{icon}</div>
                <div style="min-width:0;">
                    <div style="font-size:0.78rem;color:#64748b;font-weight:600;">{html.escape(label)}</div>
                    <div style="font-size:1.35rem;font-weight:800;color:#0f172a;line-height:1.2;">{html.escape(value)}</div>
                    <div style="font-size:0.75rem;color:{fg};margin-top:0.15rem;">{html.escape(sub)}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("Pipeline Overview")
    stages = summary.get("pipeline", [])
    if not stages:
        st.info("No pipeline stages available yet.")
    else:
        stage_cols = st.columns(len(stages), gap="small")
        for col, stage in zip(stage_cols, stages):
            with col:
                st.markdown(
                    f"""
                    <div style="background:#ffffff;border:1px solid #dbe3ed;border-radius:12px;padding:0.85rem;margin-bottom:0.5rem;">
                        <div style="font-size:0.82rem;font-weight:700;color:#0f172a;">{html.escape(stage['label'])}</div>
                        <div style="font-size:0.75rem;color:#64748b;margin-top:0.15rem;">
                            {stage['count']} leads · {html.escape(_format_currency_compact(stage['total_value']))}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                for card in stage.get("leads", [])[:5]:
                    score_txt = f"Score {card['latest_score']}" if card.get("latest_score") is not None else "Unscored"
                    val_txt = _format_currency_compact(card["estimated_value"]) if card.get("estimated_value") is not None else "—"
                    if st.button(
                        f"{card['company_name']} ({val_txt} · {score_txt})",
                        key=f"pipe_{stage['stage']}_{card['lead_id']}",
                        use_container_width=True,
                    ):
                        _jump_to_lead(card["lead_id"], "Leads")
                        st.rerun()

    left_col, right_col = st.columns([1.35, 1.0], gap="large")
    with left_col:
        st.subheader("Follow-up Recommendations")
        recs = summary.get("follow_up_recommendations", [])
        if not recs:
            st.info("No follow-up recommendations right now.")
        else:
            for rec in recs[:8]:
                st.markdown(
                    f"""
                    <div style="background:#ffffff;border:1px solid #dbe3ed;border-radius:12px;padding:0.9rem 1rem;margin-bottom:0.65rem;">
                        <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;">
                            <strong style="color:#0f172a;">{html.escape(rec['company_name'])}</strong>
                            <span style="font-size:0.72rem;font-weight:700;color:#1d4ed8;background:#eff6ff;padding:0.15rem 0.5rem;border-radius:999px;">{html.escape(rec['priority'])}</span>
                        </div>
                        <div style="font-size:0.85rem;font-weight:600;color:#1e293b;margin-top:0.25rem;">{html.escape(rec['title'])}</div>
                        <div style="font-size:0.8rem;color:#475569;margin-top:0.2rem;">{html.escape(rec['suggested_action'])}</div>
                        <div style="font-size:0.74rem;color:#64748b;margin-top:0.25rem;">{html.escape(rec['reason'])} · Channel: {html.escape(rec['recommended_channel'])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(
                    f"Open {rec['company_name']}",
                    key=f"rec_open_{rec['lead_id']}",
                ):
                    _jump_to_lead(rec["lead_id"], "Leads")
                    st.rerun()

    with right_col:
        st.subheader("Recent Automation Activity")
        items = summary.get("recent_automation_activity", [])
        if not items:
            st.info("No automation activity recorded yet.")
        else:
            for item in items[:10]:
                rel = _format_relative_time(item["timestamp"])
                st.markdown(
                    f"""
                    <div style="background:#ffffff;border:1px solid #dbe3ed;border-radius:12px;padding:0.8rem 0.95rem;margin-bottom:0.55rem;">
                        <div style="display:flex;justify-content:space-between;gap:0.5rem;">
                            <strong style="font-size:0.84rem;color:#0f172a;">{html.escape(item['title'])}</strong>
                            <span style="font-size:0.72rem;color:#64748b;">{html.escape(rel)}</span>
                        </div>
                        <div style="font-size:0.78rem;color:#475569;margin-top:0.2rem;">{html.escape(item['description'])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
