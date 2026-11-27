from __future__ import annotations

import html
from datetime import datetime, timezone

import streamlit as st

from ui.client import ApiRequestError, api_request, show_api_error

def render_page_header(eyebrow: str, title: str, description: str) -> None:
    st.markdown(
        f"""
        <section class="sg-page-header">
            <div class="sg-page-eyebrow">{eyebrow}</div>
            <h1>{title}</h1>
            <p>{description}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def crm_status_badge(status: str) -> str:
    badges = {
        "succeeded": ("Synced", "success"),
        "failed": ("Failed", "error"),
        "partial": ("Partially synced", "warning"),
        "not_requested": ("Not requested", "neutral"),
        "configured": ("Ready", "success"),
        "not_configured": ("Not configured", "neutral"),
    }
    label, tone = badges.get(status, ("Unknown", "neutral"))
    return (
        f'<span class="sg-state-badge sg-state-{tone}">'
        f'<span class="sg-state-dot"></span>{label}</span>'
    )


def crm_entity_label(provider: str, entity_type: str) -> str:
    if entity_type == "contact":
        return "Lead" if provider == "salesforce" else "Contact"
    if entity_type == "deal_stage":
        return "Opportunity stage" if provider == "salesforce" else "Deal stage"
    return "Activity"


def render_crm_sync_record(
    *,
    provider: str,
    entity_type: str,
    status: str,
    external_id: str | None,
    error_code: str | None,
    created_at: str | None = None,
) -> None:
    provider_label = "Salesforce" if provider == "salesforce" else "HubSpot"
    entity_label = crm_entity_label(provider, entity_type)
    badge_html = crm_status_badge(status)
    ts_html = (
        html.escape(created_at[:19].replace("T", " ") + " UTC")
        if created_at
        else "Just now"
    )
    if external_id:
        action_desc = f"{entity_label} record synchronized in {provider_label}."
        id_html = (
            f'<span class="sg-tag-pill" style="font-family:monospace;">'
            f'ID: {html.escape(external_id)}</span>'
        )
    else:
        action_desc = f"No {entity_label.lower()} record created in {provider_label}."
        id_html = '<span style="font-size:0.75rem; color:#64748b;">No external ID</span>'

    err_html = ""
    if error_code:
        err_msg = (
            "Access token expired — refresh token in .env"
            if error_code == "CRM_AUTH_FAILED"
            else html.escape(error_code)
        )
        err_html = (
            f'<div style="margin-top:0.45rem; background:#fffbeb; border:1px solid #fde68a; '
            f'color:#92400e; border-radius:7px; padding:0.35rem 0.6rem; font-size:0.78rem;">'
            f'⚠️ <strong>{html.escape(error_code)}</strong> · {err_msg}</div>'
        )

    card_html = (
        f'<div class="sg-outreach-card" style="padding:0.8rem 0.95rem; margin-bottom:0.55rem;">'
        f'<div style="display:flex; justify-content:space-between; align-items:center; gap:0.5rem;">'
        f'<strong style="color:#172b43; font-size:0.9rem;">{provider_label} · {entity_label}</strong>'
        f'{badge_html}'
        f'</div>'
        f'<div style="font-size:0.8rem; color:#475569; margin:0.3rem 0 0.45rem 0;">{action_desc}</div>'
        f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.4rem;">'
        f'{id_html}'
        f'<span style="font-size:0.74rem; color:#64748b;">{ts_html}</span>'
        f'</div>'
        f'{err_html}'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)




def clear_lead_filters() -> None:
    st.session_state["lead_query"] = ""
    st.session_state["lead_status_filter"] = "All statuses"
    st.session_state["lead_industry_filter"] = "All industries"
    st.session_state["lead_directory_page"] = 1


def select_dashboard_lead(lead_id: int) -> None:
    st.session_state["selected_lead_id"] = lead_id




def _split_insight_item(text: str) -> tuple[str | None, str]:
    if ":" in text:
        head, body = text.split(":", 1)
        if 2 <= len(head.strip()) <= 60 and body.strip():
            return head.strip(), body.strip()
    return None, text.strip()


def _render_insight_cards_html(items: list[str], empty_msg: str, variant: str) -> str:
    if not items:
        return (
            f'<div class="sg-intel-card sg-intel-empty">'
            f'<div class="sg-intel-desc">{html.escape(empty_msg)}</div>'
            f'</div>'
        )
    cards = []
    for raw in items:
        title, desc = _split_insight_item(str(raw))
        title_html = (
            f'<div class="sg-intel-title">{html.escape(title)}</div>'
            if title
            else ""
        )
        cards.append(
            f'<div class="sg-intel-card sg-intel-{variant}">'
            f'{title_html}'
            f'<div class="sg-intel-desc">{html.escape(desc)}</div>'
            f'</div>'
        )
    return "".join(cards)


def render_saved_analysis(lead_id: int) -> None:
    saved = st.session_state.get(f"analysis-{lead_id}")
    if saved is None:
        try:
            saved = api_request("GET", f"/api/v1/leads/{lead_id}/analysis")
        except ApiRequestError as error:
            if "No saved analysis exists" in str(error):
                st.info("No saved company analysis yet.")
                return
            show_api_error(error)
            return

    qualification = saved["qualification"]
    score_val = max(0, min(100, int(qualification.get("score", 0))))
    if score_val >= 75:
        ring_color = "#2459a6"
        grade_label = "High Readiness"
    elif score_val >= 45:
        ring_color = "#d97706"
        grade_label = "Moderate Readiness"
    else:
        ring_color = "#64748b"
        grade_label = "Needs Discovery"

    # SVG circular progress ring (r=34, circumference=213.6)
    circumference = 213.6
    dash_offset = circumference * (1 - score_val / 100.0)

    summary_html = html.escape(str(saved.get("summary", "")))
    rationale_raw = str(qualification.get("rationale", ""))

    # Separate header/signals/domain prose cleanly so chips stay short and readable
    signals: list[str] = []
    prose_notes: list[str] = []
    if "|" in rationale_raw:
        raw_parts = [p.strip() for p in rationale_raw.split("|") if p.strip()]
        for idx, part in enumerate(raw_parts):
            if idx == 0 and "Signals:" in part:
                prefix, first_sig = part.split("Signals:", 1)
                if prefix.strip():
                    prose_notes.append(prefix.strip().rstrip("."))
                if first_sig.strip():
                    signals.append(first_sig.strip())
            elif idx == len(raw_parts) - 1 and "Domain Assessment:" in part:
                last_sig, domain_note = part.split("Domain Assessment:", 1)
                if last_sig.strip():
                    signals.append(last_sig.strip().rstrip("."))
                if domain_note.strip():
                    prose_notes.append("Domain Assessment: " + domain_note.strip())
            else:
                signals.append(part)
    else:
        prose_notes.append(rationale_raw)

    chips_html = (
        '<div class="sg-signal-chips">'
        + "".join(f'<span class="sg-signal-chip">{html.escape(s)}</span>' for s in signals)
        + "</div>"
        if signals
        else ""
    )
    prose_html = (
        '<div class="sg-intel-rationale">'
        + "<br>".join(html.escape(n) for n in prose_notes)
        + "</div>"
        if prose_notes
        else ""
    )

    needs_html = _render_insight_cards_html(
        saved.get("potential_needs") or [],
        "No needs were identified.",
        "need",
    )
    opps_html = _render_insight_cards_html(
        saved.get("opportunities") or [],
        "No opportunities were identified.",
        "opp",
    )

    st.markdown(
        f"""
        <div class="sg-intel-header">
            <span class="sg-intel-heading">Lead Intelligence</span>
            <span class="sg-ai-badge">AI-Powered</span>
        </div>
        <div class="sg-intel-summary">{summary_html}</div>
        <div class="sg-score-panel">
            <div class="sg-score-top">
                <div class="sg-score-ring-wrap">
                    <svg class="sg-score-ring" viewBox="0 0 84 84">
                        <circle class="sg-ring-bg" cx="42" cy="42" r="34" />
                        <circle class="sg-ring-fg" cx="42" cy="42" r="34"
                            stroke="{ring_color}"
                            stroke-dasharray="{circumference}"
                            stroke-dashoffset="{dash_offset:.1f}" />
                    </svg>
                    <div class="sg-score-value" style="color:{ring_color}">{score_val}</div>
                </div>
                <div class="sg-score-meta">
                    <div class="sg-score-label">Qualification Score</div>
                    <div class="sg-score-sub" style="color:{ring_color}">{grade_label} · {score_val}/100</div>
                    <div class="sg-score-note">Estimate only; not a predicted conversion probability.</div>
                </div>
            </div>
            <div class="sg-score-details">
                <div class="sg-score-details-title">Qualification Signals</div>
                {chips_html}
                {prose_html}
            </div>
        </div>
        <div class="sg-intel-grid">
            <div>
                <div class="sg-col-heading">Potential needs</div>
                {needs_html}
            </div>
            <div>
                <div class="sg-col-heading">Opportunities</div>
                {opps_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def set_navigation(page: str) -> None:
    st.session_state["navigation"] = page



def _format_currency_compact(amount: float) -> str:
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.1f}K"
    return f"${amount:,.0f}"


def _format_relative_time(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return iso_ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _jump_to_lead(lead_id: int, target_page: str) -> None:
    st.session_state["selected_lead_id"] = lead_id
    st.session_state["navigation"] = target_page
