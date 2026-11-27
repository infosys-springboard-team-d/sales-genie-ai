from __future__ import annotations

import html
import io
import os
import re
import zlib
from collections import Counter
from math import ceil
from urllib.parse import quote

import requests
import streamlit as st
from dotenv import load_dotenv
from PIL import Image

from api.enrichment import get_lead_firmographics


load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = 10
ANALYSIS_TIMEOUT = 180
STATUSES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]


class ApiRequestError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def api_request(
    method: str,
    path: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
    **kwargs: object,
) -> dict | list:
    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            timeout=timeout,
            **kwargs,
        )
    except requests.Timeout as error:
        raise ApiRequestError("The API request timed out. Please retry.") from error
    except requests.ConnectionError as error:
        raise ApiRequestError(
            f"Cannot reach the SalesGenie API at {API_BASE_URL}."
        ) from error
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        error_body = body.get("error", {}) if isinstance(body, dict) else {}
        if not isinstance(error_body, dict):
            error_body = {}
        message = error_body.get("message", f"API request failed ({response.status_code}).")
        raise ApiRequestError(message, code=error_body.get("code"))
    if not isinstance(body, (dict, list)):
        raise ApiRequestError("The API returned an unexpected response.")
    return body


def show_api_error(error: ApiRequestError) -> None:
    st.error(str(error))


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


def fetch_all_leads() -> list[dict]:
    first_page = api_request(
        "GET", "/api/v1/leads", params={"page": 1, "page_size": 100}
    )
    leads = first_page["items"]
    page_count = ceil(first_page["total"] / 100)
    for page_number in range(2, page_count + 1):
        page_result = api_request(
            "GET",
            "/api/v1/leads",
            params={"page": page_number, "page_size": 100},
        )
        leads.extend(page_result["items"])
    return leads


def render_add_lead() -> None:
    render_page_header(
        "PIPELINE",
        "Add a lead",
        "Create a prospect profile to start tracking its sales journey.",
    )
    form_col, guide_col = st.columns([1.65, 1], gap="large")
    with form_col:
        with st.container(border=True):
            st.markdown("#### Prospect profile")
            st.caption("Fill in the company and stakeholder details below.")
            with st.form("add_lead_form", clear_on_submit=True):
                st.markdown("**Company & segment**")
                r1_left, r1_right = st.columns(2)
                company_name = r1_left.text_input(
                    "Company name *", placeholder="e.g. Apex Cloud Systems"
                )
                industry = r1_right.text_input(
                    "Industry", placeholder="e.g. Enterprise Software"
                )

                st.markdown("**Primary contact & stage**")
                r2_left, r2_right = st.columns(2)
                contact_name = r2_left.text_input(
                    "Contact name", placeholder="e.g. Sarah Johnson"
                )
                email = r2_right.text_input(
                    "Email", placeholder="e.g. sarah@apexcloud.com"
                )

                r3_left, r3_right = st.columns(2)
                phone = r3_left.text_input("Phone", placeholder="e.g. +1-555-0148")
                lead_status = r3_right.selectbox(
                    "Initial stage", STATUSES, index=0
                )

                submitted = st.form_submit_button("Add lead", type="primary")
            if submitted:
                try:
                    lead = api_request(
                        "POST",
                        "/api/v1/leads",
                        json={
                            "company_name": company_name,
                            "industry": industry or None,
                            "contact_name": contact_name or None,
                            "email": email or None,
                            "phone": phone or None,
                            "lead_status": lead_status,
                        },
                    )
                    st.success(
                        f"Added {lead['company_name']} (lead ID {lead['lead_id']})."
                    )
                except ApiRequestError as error:
                    show_api_error(error)

    with guide_col:
        st.markdown(
            """
            <div class="sg-detail-box" style="margin-bottom:0.75rem; background:#ffffff; border-color:#d7e0e9; padding:1rem;">
                <div class="sg-detail-label">AUTO-ENRICHMENT ON SAVE</div>
                <div class="sg-detail-value" style="font-size:0.95rem; margin-bottom:0.4rem;">Instant Firmographic Profile</div>
                <div class="sg-detail-sub" style="line-height:1.5;">
                    Once saved, SalesGenie automatically attaches industry-aligned
                    <strong>Company Size</strong>, <strong>Annual Revenue</strong>,
                    <strong>Location</strong>, <strong>Funding Stage</strong>, and
                    <strong>Tech Stack</strong> ready for AI analysis.
                </div>
            </div>
            <div class="sg-detail-box" style="background:#f8fafc; border-color:#d7e0e9; padding:1rem;">
                <div class="sg-detail-label">DATA QUALITY TIPS</div>
                <div class="sg-detail-sub" style="line-height:1.55;">
                    • <strong>Company name</strong> is required and must be unique per contact.<br>
                    • Add <strong>Industry</strong> so Ollama generates tailored B2B needs.<br>
                    • Include <strong>Email &amp; Phone</strong> for full readiness scoring and CRM sync.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_import() -> None:
    render_page_header(
        "PIPELINE",
        "Import leads",
        "Bring prospects into SalesGenie with a validated, all-or-nothing CSV import.",
    )
    st.caption(
        "UTF-8 CSV. Required column: company_name. Import is all-or-nothing: "
        "any invalid or duplicate row rejects the whole file."
    )
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
    if uploaded and st.button("Import CSV", type="primary"):
        try:
            result = api_request(
                "POST",
                "/api/v1/leads/import",
                files={"file": (uploaded.name, uploaded.getvalue(), "text/csv")},
            )
        except ApiRequestError as error:
            show_api_error(error)
            return
        if result["committed"]:
            st.success(f"Import complete: created {result['created']}.")
        else:
            st.error(
                f"Nothing imported. Duplicates: {result['duplicates']} · "
                f"invalid rows: {result['rejected']} · "
                f"valid rows rolled back: {len(result['rolled_back_rows'])}"
            )
        if result["row_errors"]:
            st.dataframe(result["row_errors"], use_container_width=True, hide_index=True)


def clear_lead_filters() -> None:
    st.session_state["lead_query"] = ""
    st.session_state["lead_status_filter"] = "All statuses"
    st.session_state["lead_industry_filter"] = "All industries"
    st.session_state["lead_directory_page"] = 1


def select_dashboard_lead(lead_id: int) -> None:
    st.session_state["selected_lead_id"] = lead_id


def render_leads() -> None:
    try:
        api_request("GET", "/health")
        leads = fetch_all_leads()
    except ApiRequestError as error:
        show_api_error(error)
        return

    counts = Counter(lead["lead_status"] for lead in leads)
    active_count = sum(
        counts[status] for status in ("New", "Contacted", "Qualified", "Proposal")
    )
    st.markdown(
        f"""
        <section class="sg-pipeline-hero">
            <div class="sg-hero-copy">
                <div class="sg-hero-eyebrow">SALES PIPELINE · LIVE WORKSPACE</div>
                <h1>Keep every opportunity moving.</h1>
                <p>Review your prospects, spot follow-ups, and turn company insights into your next action.</p>
                <div class="sg-hero-api">API connected · <a href="{API_BASE_URL}/docs" target="_blank">View API docs</a></div>
            </div>
            <div class="sg-hero-stats">
                <div><span>Active pipeline</span><strong>{active_count}</strong><small>leads to follow up</small></div>
                <div><span>Total prospects</span><strong>{len(leads)}</strong><small>in your workspace</small></div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    metrics = [("Total leads", len(leads), "total")] + [
        (status, counts[status], status.lower()) for status in STATUSES
    ]
    metric_cards = "".join(
        f'<div class="sg-metric-card sg-metric-{tone}">'
        f'<span class="sg-metric-label">{label}</span>'
        f'<span class="sg-metric-value">{value}</span>'
        "</div>"
        for label, value, tone in metrics
    )
    st.markdown(
        f'<div class="sg-metrics-grid">{metric_cards}</div>',
        unsafe_allow_html=True,
    )

    filters = st.columns([2.5, 1.15, 1.35, 0.75])
    query = filters[0].text_input(
        "Search", placeholder="Company, contact, email, or industry", key="lead_query"
    )
    selected_status = filters[1].selectbox(
        "Status", ["All statuses"] + STATUSES, key="lead_status_filter"
    )
    industries = sorted({lead["industry"] for lead in leads if lead["industry"]})
    industry_options = ["All industries"] + industries
    if st.session_state.get("lead_industry_filter") not in industry_options:
        st.session_state["lead_industry_filter"] = "All industries"
    selected_industry = filters[2].selectbox(
        "Industry", industry_options, key="lead_industry_filter"
    )
    filters[3].button(
        "Clear filters",
        use_container_width=True,
        on_click=clear_lead_filters,
    )

    normalized_query = query.strip().casefold()
    filtered_leads = [
        lead
        for lead in leads
        if (selected_status == "All statuses" or lead["lead_status"] == selected_status)
        and (selected_industry == "All industries" or lead["industry"] == selected_industry)
        and (
            not normalized_query
            or any(
                normalized_query in (lead[field] or "").casefold()
                for field in ("company_name", "contact_name", "email", "industry")
            )
        )
    ]
    st.markdown("### Lead directory")
    st.caption(f"Showing {len(filtered_leads)} of {len(leads)} leads")
    if not filtered_leads:
        st.info("No leads match these filters.")
        return

    page_size = 10
    directory_page_count = max(1, ceil(len(filtered_leads) / page_size))
    page = min(st.session_state.get("lead_directory_page", 1), directory_page_count)
    st.session_state["lead_directory_page"] = page
    start = (page - 1) * page_size
    visible_leads = filtered_leads[start : start + page_size]

    selected_ids = {lead["lead_id"] for lead in filtered_leads}
    if st.session_state.get("selected_lead_id") not in selected_ids:
        st.session_state["selected_lead_id"] = visible_leads[0]["lead_id"]

    directory, detail = st.columns([1.25, 1], gap="large")
    with directory:
        with st.container(border=True):
            st.markdown("#### All leads")
            st.caption("Select a company to inspect its details and insights.")
            st.markdown("<div class='sg-directory-spacer'></div>", unsafe_allow_html=True)
            header = st.columns([0.45, 2.1, 1.15, 1.05, 0.9, 0.85])
            for column, label in zip(
                header, ("ID", "Company", "Contact", "Industry", "Status", "Updated")
            ):
                column.caption(f"**{label}**")

            for lead in visible_leads:
                row = st.columns([0.45, 2.1, 1.15, 1.05, 0.9, 0.85])
                row[0].caption(f"#{lead['lead_id']}")
                row[1].button(
                    lead["company_name"],
                    key=f"select-lead-{lead['lead_id']}",
                    use_container_width=True,
                    type=(
                        "primary"
                        if lead["lead_id"] == st.session_state["selected_lead_id"]
                        else "secondary"
                    ),
                    on_click=select_dashboard_lead,
                    args=(lead["lead_id"],),
                )
                row[2].caption(lead["contact_name"] or "—")
                row[3].caption(lead["industry"] or "—")
                status_class = lead["lead_status"].lower()
                row[4].markdown(
                    f"<span class='status-pill status-{status_class}'>"
                    f"{lead['lead_status']}</span>",
                    unsafe_allow_html=True,
                )
                row[5].caption(lead["updated_at"][:10])
                st.divider()

            previous, page_label, next_page = st.columns([1, 2, 1])
            if previous.button(
                "Previous", disabled=page <= 1, use_container_width=True
            ):
                st.session_state["lead_directory_page"] = page - 1
                st.rerun()
            page_label.caption(f"Page {page} of {directory_page_count}")
            if next_page.button(
                "Next",
                disabled=page >= directory_page_count,
                use_container_width=True,
            ):
                st.session_state["lead_directory_page"] = page + 1
                st.rerun()

        with st.container(border=True):
            st.markdown("#### Recently updated")
            for lead in sorted(
                leads, key=lambda item: item["updated_at"], reverse=True
            )[:5]:
                st.caption(
                    f"**{lead['company_name']}** · {lead['lead_status']} · "
                    f"{lead['updated_at'][:10]}"
                )

    lead_id = st.session_state["selected_lead_id"]
    try:
        lead = api_request("GET", f"/api/v1/leads/{lead_id}")
    except ApiRequestError as error:
        show_api_error(error)
        return

    with detail:
        with st.container(border=True):
            firmographics = get_lead_firmographics(
                lead_id, lead.get("industry"), lead.get("email")
            )
            title, status_column = st.columns([3, 1])
            title.markdown(f"#### {lead['company_name']}")
            status_column.markdown(
                f"<span class='status-pill status-{lead['lead_status'].lower()}'>"
                f"{lead['lead_status']}</span>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"{lead['industry'] or 'General Enterprise'} · {firmographics['funding_stage']} · "
                f"Lead #{lead_id} · {firmographics['lead_source']}"
            )
            st.caption(
                f"Contact: **{lead.get('contact_name') or 'Not assigned'}** · "
                f"{lead.get('email') or 'No email'} · {lead.get('phone') or 'No phone'}"
            )

            size_html = html.escape(firmographics["company_size"])
            rev_html = html.escape(firmographics["annual_revenue"])
            loc_html = html.escape(firmographics["location"])
            stage_html = html.escape(firmographics["funding_stage"])
            stack_html = "".join(
                f'<span class="sg-tag-pill">{html.escape(tech)}</span>'
                for tech in firmographics["tech_stack"]
            )

            st.markdown(
                f"""
                <div class="sg-detail-grid">
                    <div class="sg-detail-box">
                        <div class="sg-detail-label">COMPANY SIZE</div>
                        <div class="sg-detail-value">{size_html}</div>
                    </div>
                    <div class="sg-detail-box">
                        <div class="sg-detail-label">ANNUAL REVENUE</div>
                        <div class="sg-detail-value">{rev_html}</div>
                    </div>
                    <div class="sg-detail-box">
                        <div class="sg-detail-label">LOCATION</div>
                        <div class="sg-detail-value">{loc_html}</div>
                    </div>
                    <div class="sg-detail-box">
                        <div class="sg-detail-label">FUNDING STAGE</div>
                        <div class="sg-detail-value">{stage_html}</div>
                    </div>
                </div>
                <div class="sg-tags-box">
                    <div class="sg-detail-label">TECHNOLOGY STACK</div>
                    <div class="sg-tags-row">{stack_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.expander("Edit lead", expanded=False):
                with st.form(f"update-lead-{lead_id}"):
                    c1, c2 = st.columns(2)
                    company_name = c1.text_input("Company", value=lead["company_name"])
                    industry = c2.text_input("Industry", value=lead["industry"] or "")
                    contact_name = c1.text_input("Contact", value=lead["contact_name"] or "")
                    email = c2.text_input("Email", value=lead["email"] or "")
                    phone = c1.text_input("Phone", value=lead["phone"] or "")
                    new_status = c2.selectbox(
                        "Lifecycle status",
                        STATUSES,
                        index=STATUSES.index(lead["lead_status"]),
                    )
                    save = st.form_submit_button("Save changes", type="primary")
                if save:
                    try:
                        api_request(
                            "PATCH",
                            f"/api/v1/leads/{lead_id}",
                            json={
                                "company_name": company_name,
                                "industry": industry or None,
                                "contact_name": contact_name or None,
                                "email": email or None,
                                "phone": phone or None,
                            },
                        )
                        if new_status != lead["lead_status"]:
                            api_request(
                                "PATCH",
                                f"/api/v1/leads/{lead_id}/status",
                                json={"lead_status": new_status},
                            )
                        st.success("Lead changes saved.")
                        st.rerun()
                    except ApiRequestError as error:
                        show_api_error(error)

            st.markdown("##### Company insights")
            context = st.text_area(
                "Analysis notes",
                placeholder="Optional company or industry context",
                key=f"analysis-context-{lead_id}",
                label_visibility="collapsed",
            )
            analysis_file = st.file_uploader(
                "Import company / industry notes (PDF, image, or text)",
                type=["pdf", "png", "jpg", "jpeg", "webp", "txt", "md"],
                key=f"analysis-file-{lead_id}",
            )
            if st.button("Analyze company", type="primary", key=f"analyze-{lead_id}"):
                combined_context = (context or "").strip()
                if analysis_file is not None:
                    file_ctx = _extract_activity_file_note(analysis_file)
                    combined_context = (
                        f"{combined_context}\n{file_ctx}".strip()
                        if combined_context
                        else file_ctx
                    )
                if len(combined_context) > 5000:
                    combined_context = combined_context[:4997] + "..."
                with st.spinner("Generating and saving company insights..."):
                    try:
                        result = api_request(
                            "POST",
                            f"/api/v1/leads/{lead_id}/analysis",
                            json={"context": combined_context or None},
                            timeout=ANALYSIS_TIMEOUT,
                        )
                        st.session_state[f"analysis-{lead_id}"] = result
                    except ApiRequestError as error:
                        show_api_error(error)
            render_saved_analysis(lead_id)


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


def _extract_pdf_text_fallback(raw_bytes: bytes) -> str:
    """Extract readable text from uncompressed or FlateDecode PDF streams."""
    chunks: list[str] = []
    for match in re.finditer(rb"stream[\r\n]+(.*?)[\r\n]+endstream", raw_bytes, re.DOTALL):
        stream_data = match.group(1)
        try:
            stream_data = zlib.decompress(stream_data)
        except zlib.error:
            pass
        for txt in re.findall(rb"\(([^()]{2,200})\)", stream_data):
            decoded = txt.decode("latin-1", errors="ignore").strip()
            if decoded and any(ch.isalpha() for ch in decoded):
                chunks.append(decoded)
    return " ".join(chunks)


def _extract_activity_file_note(uploaded_file) -> str:
    """Build a concise, 1500-char-safe activity note from an uploaded PDF, image, or text file."""
    name = uploaded_file.name
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    raw = uploaded_file.getvalue()

    if ext in {"txt", "md", "csv"}:
        text = raw.decode("utf-8", errors="ignore").strip()
        preview = text[:1400] + ("..." if len(text) > 1400 else "")
        return f"[Attached {ext.upper()}: {name}] {preview}" if preview else f"[Attached file: {name}]"

    if ext == "pdf":
        extracted = ""
        try:
            import pypdf  # type: ignore[import-not-found]
            reader = pypdf.PdfReader(io.BytesIO(raw))
            extracted = " ".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        except Exception:
            extracted = _extract_pdf_text_fallback(raw)
        extracted = re.sub(r"\s+", " ", extracted).strip()
        if extracted:
            preview = extracted[:1400] + ("..." if len(extracted) > 1400 else "")
            return f"[Attached PDF: {name}] {preview}"
        return f"[Attached PDF: {name} ({len(raw) // 1024 or 1} KB)]"

    if ext in {"png", "jpg", "jpeg", "webp"}:
        try:
            img = Image.open(io.BytesIO(raw))
            w, h = img.size
            fmt = img.format or ext.upper()
            return f"[Attached Image: {name} ({w}x{h} {fmt})]"
        except Exception:
            return f"[Attached Image: {name}]"

    return f"[Attached File: {name}]"


def render_outreach() -> None:
    render_page_header(
        "ENGAGEMENT",
        "Outreach strategy",
        "Review an explainable readiness estimate and create personalized drafts. "
        "Drafts are saved for human review; SalesGenie does not send email.",
    )
    try:
        leads = fetch_all_leads()
    except ApiRequestError as error:
        show_api_error(error)
        return
    if not leads:
        st.info("Add a lead before preparing outreach.")
        return

    lead_by_label = {
        f"{lead['company_name']} (#{lead['lead_id']})": lead for lead in leads
    }
    labels = list(lead_by_label)
    sel_col, btn_col = st.columns([3, 1], gap="medium")
    with sel_col:
        selected_label = st.selectbox("Select a lead", labels, key="outreach-lead")
    lead = lead_by_label[selected_label]
    lead_id = lead["lead_id"]
    firmographics = get_lead_firmographics(
        lead_id, lead.get("industry"), lead.get("email")
    )
    with btn_col:
        st.markdown("<div style='height:1.7rem;'></div>", unsafe_allow_html=True)
        refresh_clicked = st.button(
            "Calculate / refresh score", type="primary", key=f"score-{lead_id}", use_container_width=True
        )

    st.markdown(
        f'<div class="sg-outreach-card" style="padding:0.8rem 1.05rem; margin-bottom:0.9rem;">'
        f'<div style="display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:0.5rem;">'
        f'<div>'
        f'<span style="font-size:1.05rem; font-weight:700; color:#172b43;">{html.escape(lead["company_name"])}</span> '
        f'<span style="color:#64748b; font-size:0.84rem;">· {html.escape(lead.get("industry") or "General Enterprise")} · {html.escape(firmographics["funding_stage"])}</span>'
        f'</div>'
        f'<span class="status-pill status-{lead["lead_status"].lower()}">{html.escape(lead["lead_status"])}</span>'
        f'</div>'
        f'<div style="margin-top:0.35rem; font-size:0.8rem; color:#475569;">'
        f'👤 <strong>{html.escape(lead.get("contact_name") or "Contact not set")}</strong> · '
        f'✉️ {html.escape(lead.get("email") or "No email")} · '
        f'📍 {html.escape(firmographics["location"])} · '
        f'👥 {html.escape(firmographics["company_size"])}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if refresh_clicked:
        try:
            api_request("POST", f"/api/v1/leads/{lead_id}/scores")
            st.success("Score and recommendation saved.")
        except ApiRequestError as error:
            show_api_error(error)

    try:
        score = api_request("GET", f"/api/v1/leads/{lead_id}/scores/latest")
    except ApiRequestError as error:
        score = None
        if error.code == "SCORE_NOT_FOUND":
            st.info("No Milestone 2 score yet. Calculate a score to see the recommendation.")
        else:
            show_api_error(error)
    if score:
        score_val = max(0, min(100, int(score["score"])))
        if score_val >= 75:
            ring_color = "#2459a6"
            qual_title = "Highly Qualified Lead"
        elif score_val >= 45:
            ring_color = "#d97706"
            qual_title = "Moderate Readiness Lead"
        else:
            ring_color = "#64748b"
            qual_title = "Early Discovery Lead"

        circumference = 251.2  # 2 * pi * 40
        dash_offset = circumference * (1 - score_val / 100.0)
        factors = score.get("factors", {})
        factor_labels = {
            "fit": ("Industry & Profile Fit", "🏢"),
            "engagement": ("Engagement Signals", "📈"),
            "intent": ("Buying Intent", "🎯"),
            "decision_readiness": ("Decision Readiness", "👤"),
        }
        factor_rows = "".join(
            f'<div class="sg-factor-row">'
            f'<div class="sg-factor-left">'
            f'<span class="sg-factor-icon">{icon}</span>'
            f'<span class="sg-factor-name">{label}</span>'
            f'</div>'
            f'<span class="sg-factor-pts">+{int(factors.get(key, 0))} points</span>'
            f'</div>'
            for key, (label, icon) in factor_labels.items()
        )
        recommendation = score["recommendation"]
        rationale_clean = html.escape(str(score.get("rationale", ""))).replace("\n", " ")

        score_col, strat_col = st.columns([1, 1.35], gap="large")
        with score_col:
            score_card_html = (
                f'<div class="sg-outreach-card">'
                f'<div class="sg-intel-header" style="margin-top:0;">'
                f'<span class="sg-intel-heading">Lead Score</span>'
                f'<span class="sg-ai-badge">AI Powered</span>'
                f'</div>'
                f'<div class="sg-big-ring-wrap">'
                f'<svg class="sg-big-ring" viewBox="0 0 100 100">'
                f'<circle class="sg-ring-bg" cx="50" cy="50" r="40" />'
                f'<circle class="sg-ring-fg" cx="50" cy="50" r="40" '
                f'stroke="{ring_color}" stroke-dasharray="{circumference}" '
                f'stroke-dashoffset="{dash_offset:.1f}" />'
                f'</svg>'
                f'<div class="sg-big-score-val">{score_val}</div>'
                f'</div>'
                f'<div class="sg-big-score-sub">{qual_title}</div>'
                f'<div class="sg-prob-row"><span>Readiness Index</span><strong>{score_val}%</strong></div>'
                f'<div class="sg-prob-track"><div class="sg-prob-fill" style="width:{score_val}%;"></div></div>'
                f'<div class="sg-score-details-title" style="margin-top:0.85rem;">Scoring Factors</div>'
                f'{factor_rows}'
                f'<div class="sg-score-note" style="margin-top:0.6rem;">{rationale_clean}</div>'
                f'</div>'
            )
            st.markdown(score_card_html, unsafe_allow_html=True)

        with strat_col:
            firmographics = get_lead_firmographics(
                lead_id, lead.get("industry"), lead.get("email")
            )
            company_lbl = html.escape(lead["company_name"])
            industry_lbl = html.escape(lead.get("industry") or "B2B enterprise")
            contact_lbl = html.escape(lead.get("contact_name") or "the primary stakeholder")
            stage_lbl = html.escape(firmographics["funding_stage"])
            size_lbl = html.escape(firmographics["company_size"])

            timing_raw = str(recommendation.get("timing", "Today")).strip()
            channel_raw = str(recommendation.get("channel", "email")).strip()
            action_text = html.escape(str(recommendation.get("action", "")).strip())
            rationale_text = html.escape(str(recommendation.get("rationale", "")).strip())

            timing_prio_cls = "sg-prio-high" if (score_val >= 65 or timing_raw.lower() == "today") else "sg-prio-med"
            timing_prio_lbl = "High" if timing_prio_cls == "sg-prio-high" else "Medium"

            timing_body = (
                f"Send initial follow-up <strong>{html.escape(timing_raw.lower())}</strong> "
                f"(within 24–48 hours while profile signals are fresh). "
                f"Mid-morning windows (10:00–11:00 AM) typically achieve the highest response rates "
                f"for {industry_lbl} decision-makers."
            )
            channel_body = (
                f"Lead with a targeted <strong>{html.escape(channel_raw.lower())}</strong> touchpoint to "
                f"{contact_lbl}, followed by a LinkedIn connection within 24 hours. "
                f"Reference {company_lbl}'s {stage_lbl} positioning and {industry_lbl} growth priorities."
            )
            content_body = (
                f"<strong>{action_text}</strong><br>"
                f"Share peer benchmarks tailored for {size_lbl} {industry_lbl} teams. "
                f"{rationale_text}"
            )

            strat_html = (
                f'<div class="sg-outreach-card">'
                f'<div class="sg-intel-header" style="margin-top:0;">'
                f'<span class="sg-intel-heading">Outreach Strategy</span>'
                f'</div>'
                f'<div class="sg-strat-item">'
                f'<div class="sg-strat-top">'
                f'<span class="sg-strat-title">Follow-up Timing</span>'
                f'<span class="sg-prio-badge {timing_prio_cls}">{timing_prio_lbl}</span>'
                f'</div>'
                f'<div class="sg-strat-body">{timing_body}</div>'
                f'<div class="sg-strat-meta">🕒 Optimal: {html.escape(timing_raw)} · 10:00–11:00 AM</div>'
                f'</div>'
                f'<div class="sg-strat-item">'
                f'<div class="sg-strat-top">'
                f'<span class="sg-strat-title">Channel Mix</span>'
                f'<span class="sg-prio-badge sg-prio-med">Medium</span>'
                f'</div>'
                f'<div class="sg-strat-body">{channel_body}</div>'
                f'<div class="sg-strat-meta">⇄ Primary: {html.escape(channel_raw.title())} · Multi-channel approach</div>'
                f'</div>'
                f'<div class="sg-strat-item" style="margin-bottom:0;">'
                f'<div class="sg-strat-top">'
                f'<span class="sg-strat-title">Content Strategy</span>'
                f'<span class="sg-prio-badge sg-prio-med">Medium</span>'
                f'</div>'
                f'<div class="sg-strat-body">{content_body}</div>'
                f'<div class="sg-strat-meta">📄 Value-first consultative approach</div>'
                f'</div>'
                f'</div>'
            )
            st.markdown(strat_html, unsafe_allow_html=True)

    with st.expander("Log a sales activity", expanded=False):
        with st.form(f"activity-form-{lead_id}"):
            activity_type = st.selectbox(
                "Activity", ["call", "email", "meeting", "reply", "note"]
            )
            activity_note = st.text_area("Outcome or notes", max_chars=2000)
            uploaded_attachment = st.file_uploader(
                "Import outcome or notes file (PDF, image, or text)",
                type=["pdf", "png", "jpg", "jpeg", "webp", "txt", "md"],
                key=f"activity-file-{lead_id}",
            )
            activity_submitted = st.form_submit_button("Save activity")
        if activity_submitted:
            combined_note = (activity_note or "").strip()
            if uploaded_attachment is not None:
                file_note = _extract_activity_file_note(uploaded_attachment)
                combined_note = f"{combined_note}\n{file_note}".strip() if combined_note else file_note
            if len(combined_note) > 2000:
                combined_note = combined_note[:1997] + "..."
            try:
                api_request(
                    "POST",
                    f"/api/v1/leads/{lead_id}/activities",
                    json={
                        "activity_type": activity_type,
                        "details": combined_note or None,
                    },
                )
                st.success("Activity recorded.")
                st.rerun()
            except ApiRequestError as error:
                show_api_error(error)
    try:
        activities = api_request("GET", f"/api/v1/leads/{lead_id}/activities")
    except ApiRequestError as error:
        show_api_error(error)
        activities = []
    if activities:
        st.caption("Recent activity")
        for activity in activities[:5]:
            note = activity["details"].get("note")
            st.write(
                f"**{activity['activity_type'].title()}** · "
                f"{activity['occurred_at'][:10]}"
                + (f" — {note}" if note else "")
            )

    st.markdown("### Outreach Composer & AI Email Generator")
    gen_col, preview_col = st.columns([1, 1.2], gap="large")
    with gen_col:
        with st.form(f"outreach-form-{lead_id}"):
            opt1, opt2, opt3 = st.columns(3)
            draft_type = opt1.selectbox("Draft type", ["email", "message"])
            tone = opt2.selectbox(
                "Tone", ["professional", "friendly", "concise", "persuasive"]
            )
            length = opt3.selectbox("Length", ["short", "medium", "long"])
            goal = st.text_input("Goal", value="Start a relevant sales conversation")
            pain_point_text = st.text_area(
                "Known prospect needs or pain points",
                help="Use verified notes only. Enter one item per line.",
                height=110,
            )
            pain_point_file = st.file_uploader(
                "Import pain points / notes file (PDF, image, or text)",
                type=["pdf", "png", "jpg", "jpeg", "webp", "txt", "md"],
                key=f"outreach-pain-file-{lead_id}",
            )
            generate = st.form_submit_button("Generate / regenerate draft", type="primary")
        if generate:
            pain_points = [
                item.strip() for item in pain_point_text.splitlines() if item.strip()
            ]
            if pain_point_file is not None:
                extracted_note = _extract_activity_file_note(pain_point_file)
                for line in extracted_note.splitlines():
                    cleaned = line.strip()
                    if cleaned:
                        pain_points.append(cleaned[:500])
            pain_points = pain_points[:10]
            with st.spinner("Generating a draft for review..."):
                try:
                    api_request(
                        "POST",
                        f"/api/v1/leads/{lead_id}/outreach-drafts",
                        json={
                            "draft_type": draft_type,
                            "tone": tone,
                            "length": length,
                            "goal": goal,
                            "pain_points": pain_points,
                        },
                        timeout=ANALYSIS_TIMEOUT,
                    )
                    st.success("Draft generated and saved.")
                    st.rerun()
                except ApiRequestError as error:
                    show_api_error(error)

    with preview_col:
        try:
            drafts = api_request("GET", f"/api/v1/leads/{lead_id}/outreach-drafts")
        except ApiRequestError as error:
            show_api_error(error)
            return
        if not drafts:
            st.info("No outreach drafts saved for this lead yet. Generate one on the left to preview it here.")
            return
        draft = drafts[0]
        raw_content = draft["content"]
        if draft["draft_type"] == "email" and raw_content.startswith("Subject: "):
            subj_line, _, email_body = raw_content.partition("\n\n")
            email_subject = subj_line.removeprefix("Subject: ").strip()
            if not email_body:
                subj_line, _, email_body = raw_content.partition("\n")
                email_subject = subj_line.removeprefix("Subject: ").strip()
        else:
            email_subject = "Follow-up from SalesGenie" if draft["draft_type"] == "email" else "Direct Message Draft"
            email_body = raw_content

        to_addr = html.escape(lead.get("email") or "No email on file")
        subj_html = html.escape(email_subject)
        body_html = html.escape(email_body).replace("\n", "<br>")

        email_card_html = (
            f'<div class="sg-outreach-card">'
            f'<div class="sg-intel-header" style="margin-top:0;">'
            f'<span class="sg-intel-heading">AI Email Generator</span>'
            f'<span class="sg-ai-badge">AI Powered</span>'
            f'</div>'
            f'<div class="sg-email-meta-row">'
            f'<span class="sg-email-meta-label">To:</span>'
            f'<span class="sg-email-meta-val">{to_addr}</span>'
            f'</div>'
            f'<div class="sg-email-meta-row">'
            f'<span class="sg-email-meta-label">Subject:</span>'
            f'<span class="sg-email-meta-val"><strong>{subj_html}</strong></span>'
            f'</div>'
            f'<div class="sg-email-body-card">{body_html}</div>'
            f'</div>'
        )
        st.markdown(email_card_html, unsafe_allow_html=True)

        btn_c1, btn_c2 = st.columns(2)
        with btn_c1:
            st.download_button(
                "Download draft",
                data=raw_content,
                file_name=f"salesgenie-{draft['draft_type']}-draft-{draft['draft_id']}.txt",
                mime="text/plain",
                key=f"download-draft-{draft['draft_id']}",
                use_container_width=True,
            )
        if draft["draft_type"] == "email" and lead.get("email"):
            gmail_url = (
                f"https://mail.google.com/mail/?view=cm&fs=1"
                f"&to={quote(lead['email'])}"
                f"&su={quote(email_subject)}"
                f"&body={quote(email_body)}"
            )
            with btn_c2:
                st.link_button("Open in Gmail", gmail_url, use_container_width=True)

        with st.expander("Edit or copy raw draft", expanded=False):
            st.code(raw_content)
            with st.form(f"edit-draft-{draft['draft_id']}"):
                edited_content = st.text_area(
                    "Edit draft",
                    value=raw_content,
                    height=220,
                    key=f"draft-content-{draft['draft_id']}",
                )
                save_draft = st.form_submit_button("Save edits")
            if save_draft:
                try:
                    api_request(
                        "PATCH",
                        f"/api/v1/outreach-drafts/{draft['draft_id']}",
                        json={"content": edited_content},
                    )
                    st.success("Draft edits saved.")
                    st.rerun()
                except ApiRequestError as error:
                    show_api_error(error)

        if draft["draft_type"] == "email":
            if lead["email"]:
                mailto_url = (
                    f"mailto:{quote(lead['email'], safe='@')}"
                    f"?subject={quote(email_subject)}&body={quote(email_body)}"
                )
                st.link_button("Open in default email app", mailto_url, use_container_width=True)
                st.caption("Review the recipient and content in your email client before sending.")
            else:
                st.info("Add an email address to open this draft in your email client.")


def render_conversations() -> None:
    render_page_header(
        "CONVERSATIONS",
        "Conversation intelligence",
        "Summarize calls and meetings, review extracted actions, and synchronize "
        "lead activity with Salesforce or HubSpot.",
    )
    try:
        leads = fetch_all_leads()
    except ApiRequestError as error:
        show_api_error(error)
        return
    if not leads:
        st.info("Add a lead before recording or synchronizing a conversation.")
        return

    lead_by_label = {
        f"{lead['company_name']} (#{lead['lead_id']})": lead for lead in leads
    }
    selected_label = st.selectbox("Lead", list(lead_by_label))
    lead = lead_by_label[selected_label]
    lead_id = lead["lead_id"]
    company_lbl = html.escape(lead["company_name"])
    contact_lbl = html.escape(lead.get("contact_name") or "Primary Contact")
    industry_lbl = html.escape(lead.get("industry") or "General Enterprise")

    st.markdown(
        f'<div class="sg-outreach-card" style="padding:0.75rem 1rem; margin-bottom:0.85rem;">'
        f'<div style="display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:0.5rem;">'
        f'<div><strong style="color:#172b43; font-size:1rem;">{company_lbl}</strong> '
        f'<span style="color:#64748b; font-size:0.83rem;">· 👤 {contact_lbl} · {industry_lbl}</span></div>'
        f'<span class="status-pill status-{lead["lead_status"].lower()}">{html.escape(lead["lead_status"])}</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    summarize_tab, crm_tab, activity_tab = st.tabs(
        ["Meeting summary", "CRM sync", "Recent activity"]
    )

    with summarize_tab:
        sum_form_col, sum_list_col = st.columns([1, 1.25], gap="large")
        with sum_form_col:
            st.markdown("#### Summarize a call or meeting")
            st.caption(
                "Sent to local Ollama (`llama3.2`); raw transcripts are not retained—only "
                "the summary, key points, and action items are saved."
            )
            with st.form(f"conversation-summary-{lead_id}"):
                interaction_type = st.selectbox(
                    "Interaction type", ["call", "meeting"], key=f"interaction-type-{lead_id}"
                )
                transcript = st.text_area(
                    "Transcript",
                    height=180,
                    max_chars=40000,
                    placeholder="Paste call or meeting transcript here...",
                    help="Enter a transcript up to 40,000 characters.",
                    key=f"transcript-{lead_id}",
                )
                transcript_file = st.file_uploader(
                    "Or import transcript file (TXT, MD, PDF)",
                    type=["txt", "md", "pdf"],
                    key=f"transcript-file-{lead_id}",
                )
                summarize = st.form_submit_button("Summarize and save", type="primary")
            if summarize:
                final_transcript = (transcript or "").strip()
                if transcript_file is not None:
                    file_text = _extract_activity_file_note(transcript_file)
                    final_transcript = f"{final_transcript}\n{file_text}".strip() if final_transcript else file_text
                if not final_transcript:
                    st.warning("Please enter a transcript or upload a transcript file.")
                else:
                    with st.spinner("Summarizing the conversation..."):
                        try:
                            api_request(
                                "POST",
                                f"/api/v1/leads/{lead_id}/conversation-summaries",
                                json={
                                    "interaction_type": interaction_type,
                                    "transcript": final_transcript[:40000],
                                },
                                timeout=ANALYSIS_TIMEOUT,
                            )
                            st.success("Conversation summary saved.")
                            st.rerun()
                        except ApiRequestError as error:
                            show_api_error(error)

        with sum_list_col:
            try:
                summaries = api_request(
                    "GET", f"/api/v1/leads/{lead_id}/conversation-summaries"
                )
            except ApiRequestError as error:
                show_api_error(error)
                summaries = []
            if summaries:
                for summary in summaries:
                    ts_lbl = html.escape(summary["created_at"][:19].replace("T", " ") + " UTC")
                    itype_lbl = html.escape(summary["interaction_type"].title())
                    sum_text = html.escape(summary["summary"])
                    points_html = "".join(
                        f'<div class="sg-point-item"><span class="sg-point-dot"></span><span>{html.escape(pt)}</span></div>'
                        for pt in (summary.get("key_points") or [])
                    )
                    if summary.get("action_items"):
                        actions_html = "".join(
                            f'<div class="sg-action-card">'
                            f'<div class="sg-action-meta"><span>{contact_lbl}</span><span>Action Required</span></div>'
                            f'<div class="sg-action-text">{html.escape(ai)}</div>'
                            f'</div>'
                            for ai in summary["action_items"]
                        )
                    else:
                        actions_html = '<div class="sg-score-note">No explicit action items were identified.</div>'

                    card_html = (
                        f'<div class="sg-outreach-card">'
                        f'<div class="sg-intel-header" style="margin-top:0;">'
                        f'<span class="sg-intel-heading">{itype_lbl} Summary</span>'
                        f'<span class="sg-ai-badge">AI Powered</span>'
                        f'</div>'
                        f'<div style="font-size:0.78rem; color:#64748b; margin-bottom:0.65rem;">'
                        f'👤 {contact_lbl} &nbsp;·&nbsp; 🕒 {ts_lbl} &nbsp;·&nbsp; 🏢 {company_lbl}'
                        f'</div>'
                        f'<div class="sg-intel-summary" style="margin-bottom:0.75rem;">{sum_text}</div>'
                        f'<div class="sg-score-details-title">Key Discussion Points</div>'
                        f'{points_html or "<div class=sg-score-note>None noted.</div>"}'
                        f'<div class="sg-score-details-title" style="margin-top:0.75rem;">Action Items</div>'
                        f'{actions_html}'
                        f'</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)
            else:
                st.info("No saved conversation summaries for this lead.")

    with crm_tab:
        try:
            mappings = api_request("GET", "/api/v1/crm/mappings")
        except ApiRequestError as error:
            show_api_error(error)
            mappings = {}
        if isinstance(mappings, dict):
            configuration = st.columns(2, gap="medium")
            for column, provider_name in zip(
                configuration, ("salesforce", "hubspot")
            ):
                mapping = mappings.get(provider_name, {})
                label = "Salesforce" if provider_name == "salesforce" else "HubSpot"
                badge = crm_status_badge("configured" if mapping.get("configured") else "not_configured")
                c_obj = html.escape(str(mapping.get("contact_object", "—")))
                a_obj = html.escape(str(mapping.get("activity_object", "—")))
                stage_lbl = "Configured" if mapping.get("deal_stage_mapping") else "Not configured"
                column.markdown(
                    f'<div class="sg-outreach-card" style="padding:0.85rem 1rem;">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.35rem;">'
                    f'<strong style="color:#172b43; font-size:0.95rem;">{label}</strong>{badge}'
                    f'</div>'
                    f'<div style="font-size:0.78rem; color:#475569;">Contact: <strong>{c_obj}</strong> · Activity: <strong>{a_obj}</strong></div>'
                    f'<div style="font-size:0.75rem; color:#64748b; margin-top:0.15rem;">Deal-stage mapping: {stage_lbl}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        crm_form_col, crm_log_col = st.columns([1, 1.25], gap="large")
        with crm_form_col:
            st.markdown("#### Sync controls")
            st.caption(
                "Contact lifecycle fields and recorded activities are synchronized. "
                "No CRM deal/opportunity is auto-created."
            )
            with st.form(f"crm-sync-{lead_id}"):
                provider_name = st.selectbox(
                    "CRM provider", ["salesforce", "hubspot"], key=f"crm-provider-{lead_id}"
                )
                deal_id = st.text_input(
                    "Existing CRM deal/opportunity ID (optional)",
                    key=f"crm-deal-id-{lead_id}",
                )
                include_activities = st.checkbox(
                    "Synchronize unsynced activities and conversation summaries",
                    value=True,
                    key=f"crm-activities-{lead_id}",
                )
                synchronize = st.form_submit_button("Synchronize lead", type="primary")
            if synchronize:
                try:
                    result = api_request(
                        "POST",
                        f"/api/v1/leads/{lead_id}/crm-sync",
                        json={
                            "provider": provider_name,
                            "include_activities": include_activities,
                            "deal_id": deal_id or None,
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                except ApiRequestError as error:
                    show_api_error(error)
                else:
                    if result["status"] == "succeeded":
                        st.success("CRM synchronization completed.")
                    else:
                        st.warning("CRM synchronization completed with some failed operations.")
                    for operation in result["operations"]:
                        render_crm_sync_record(
                            provider=provider_name,
                            entity_type=operation["entity_type"],
                            status=operation["status"],
                            external_id=operation["external_id"],
                            error_code=operation["error_code"],
                        )

        with crm_log_col:
            try:
                sync_logs = api_request(
                    "GET", f"/api/v1/leads/{lead_id}/crm-sync-logs"
                )
            except ApiRequestError as error:
                show_api_error(error)
                sync_logs = []
            st.markdown("#### CRM Sync Status")
            if sync_logs:
                succeeded_count = sum(item["status"] == "succeeded" for item in sync_logs)
                failed_count = sum(item["status"] == "failed" for item in sync_logs)
                status_metrics = st.columns(2)
                status_metrics[0].metric("Successful operations", succeeded_count)
                status_metrics[1].metric("Failed operations", failed_count)
                for item in sync_logs:
                    render_crm_sync_record(
                        provider=item["provider"],
                        entity_type=item["entity_type"],
                        status=item["status"],
                        external_id=item["external_id"],
                        error_code=item["error_code"],
                        created_at=item["created_at"],
                    )
            else:
                st.info("No CRM sync attempts have been recorded for this lead.")

    with activity_tab:
        st.markdown("#### Recent Activity Timeline")
        try:
            activities = api_request(
                "GET", f"/api/v1/leads/{lead_id}/activities"
            )
            summaries = api_request(
                "GET", f"/api/v1/leads/{lead_id}/conversation-summaries"
            )
        except ApiRequestError as error:
            show_api_error(error)
            return
        feed = [
            {
                "occurred_at": activity["occurred_at"],
                "type": activity["activity_type"].title(),
                "kind": activity["activity_type"].lower(),
                "details": activity["details"].get("note") or "No additional details.",
            }
            for activity in activities
        ]
        feed.extend(
            {
                "occurred_at": summary["created_at"],
                "type": f"{summary['interaction_type'].title()} summary",
                "kind": "summary",
                "details": summary["summary"],
            }
            for summary in summaries
        )
        feed.sort(key=lambda item: item["occurred_at"], reverse=True)
        if not feed:
            st.info("No activity has been recorded for this lead.")
        else:
            icon_map = {
                "email": ("✉️", "#eff6ff", "#2563eb"),
                "call": ("📞", "#ecfdf5", "#16a34a"),
                "meeting": ("📅", "#f3edff", "#7c3aed"),
                "note": ("📝", "#fff7ed", "#ea580c"),
                "reply": ("💬", "#eef2ff", "#4f46e5"),
                "summary": ("✨", "#f0fdfa", "#0d9488"),
            }
            rows_html = []
            for item in feed[:20]:
                icon_ch, bg_col, fg_col = icon_map.get(item["kind"], ("📌", "#f1f5f9", "#475569"))
                ts_txt = html.escape(item["occurred_at"][:19].replace("T", " ") + " UTC")
                det_txt = html.escape(str(item["details"]))
                typ_txt = html.escape(str(item["type"]))
                rows_html.append(
                    f'<div class="sg-timeline-row">'
                    f'<div class="sg-timeline-icon" style="background:{bg_col}; color:{fg_col};">{icon_ch}</div>'
                    f'<div style="flex:1; min-width:0;">'
                    f'<div style="display:flex; justify-content:space-between; gap:0.5rem;">'
                    f'<strong style="font-size:0.86rem; color:#172b43;">{typ_txt}</strong>'
                    f'<span style="font-size:0.74rem; color:#64748b; white-space:nowrap;">{ts_txt}</span>'
                    f'</div>'
                    f'<div style="font-size:0.82rem; color:#334155; margin-top:0.15rem; line-height:1.45;">{det_txt}</div>'
                    f'<div style="font-size:0.73rem; color:#64748b; margin-top:0.15rem;">{company_lbl}</div>'
                    f'</div>'
                    f'</div>'
                )
            st.markdown(
                f'<div class="sg-outreach-card">{"".join(rows_html)}</div>',
                unsafe_allow_html=True,
            )


def main() -> None:
    st.set_page_config(
        page_title="SalesGenie AI",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(
        """
        <style>
        .stApp { background: #edf1f6; color: #1e293b; }
        .block-container { max-width: 1540px; padding-top: 2rem; padding-bottom: 3rem; }
        .sg-brandbar {
            position: sticky;
            top: 4.5rem;
            z-index: 1000;
            display: flex;
            align-items: center;
            gap: 1.1rem;
            min-height: 5.6rem;
            padding: 1.4rem 1.65rem;
            margin-bottom: 1rem;
            color: #f8fafc;
            background: linear-gradient(115deg, #14243a, #243e5c);
            border: 1px solid #314b68;
            border-radius: 14px;
            box-shadow: 0 5px 16px rgba(15, 23, 42, 0.12);
        }
        .sg-brand-mark {
            display: grid;
            place-items: center;
            width: 2.65rem;
            height: 2.65rem;
            flex: 0 0 2.65rem;
            color: #14243a;
            background: #8ed8c3;
            border-radius: 10px;
            font-size: 1.05rem;
            font-weight: 800;
        }
        .sg-brand-name { font-size: 1.25rem; font-weight: 700; line-height: 1.3; }
        .sg-brand-subtitle {
            margin-top: 0.15rem;
            color: #c1cfde;
            font-size: 0.72rem;
            letter-spacing: 0.09em;
        }
        .sg-pipeline-hero {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 2rem;
            margin: 1.4rem 0 1.35rem;
            padding: 1.8rem 2rem;
            color: #f8fafc;
            background:
                radial-gradient(ellipse at 92% 0%, rgba(142, 216, 195, 0.19), transparent 34%),
                linear-gradient(115deg, #172b43, #294967);
            border: 1px solid #38536f;
            border-radius: 16px;
            box-shadow: 0 10px 24px rgba(23, 43, 67, 0.14);
        }
        .sg-hero-copy { min-width: 0; }
        .sg-hero-eyebrow {
            margin-bottom: 0.6rem;
            color: #9de2ce;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.12em;
        }
        .sg-pipeline-hero h1 {
            margin: 0;
            color: #ffffff;
            font-size: clamp(1.55rem, 3vw, 2.15rem);
            line-height: 1.2;
        }
        .sg-pipeline-hero p {
            max-width: 38rem;
            margin: 0.6rem 0 0.8rem;
            color: #d2deea;
            font-size: 0.95rem;
        }
        .sg-hero-api { color: #c1cfde; font-size: 0.8rem; }
        .sg-hero-api a { color: #9de2ce; text-decoration: underline; }
        .sg-hero-stats {
            display: flex;
            flex: 0 0 auto;
            gap: 0.75rem;
        }
        .sg-hero-stats > div {
            display: flex;
            min-width: 8.5rem;
            flex-direction: column;
            gap: 0.2rem;
            padding: 0.85rem 1rem;
            background: rgba(255, 255, 255, 0.09);
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 12px;
        }
        .sg-hero-stats span { color: #d2deea; font-size: 0.75rem; }
        .sg-hero-stats strong { color: #ffffff; font-size: 1.8rem; line-height: 1.1; }
        .sg-hero-stats small { color: #b8c8d8; font-size: 0.7rem; }
        .sg-page-header {
            margin: 1.4rem 0 1.25rem;
            padding: 1.4rem 1.65rem;
            background:
                radial-gradient(ellipse at 92% 0%, rgba(142, 216, 195, 0.16), transparent 34%),
                linear-gradient(115deg, #ffffff, #f7fafc);
            border: 1px solid #d7e0e9;
            border-left: 4px solid #55b99b;
            border-radius: 14px;
            box-shadow: 0 5px 16px rgba(26, 45, 68, 0.06);
        }
        .sg-page-eyebrow {
            margin-bottom: 0.35rem;
            color: #388b76;
            font-size: 0.68rem;
            font-weight: 750;
            letter-spacing: 0.13em;
        }
        .sg-page-header h1 {
            margin: 0;
            color: #172b43;
            font-size: clamp(1.55rem, 3vw, 2rem);
            line-height: 1.2;
        }
        .sg-page-header p {
            max-width: 48rem;
            margin: 0.45rem 0 0;
            color: #53657a;
            font-size: 0.92rem;
        }
        @media (max-width: 720px) {
            .sg-pipeline-hero { align-items: stretch; flex-direction: column; gap: 1rem; padding: 1.25rem; }
            .sg-hero-stats > div { min-width: 0; flex: 1; }
        }
        .sg-metrics-grid {
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.85rem 0 1.25rem;
        }
        .sg-metric-card {
            display: flex;
            min-height: 6.3rem;
            flex-direction: column;
            justify-content: space-between;
            gap: 0.5rem;
            padding: 0.9rem 1rem;
            background: #ffffff;
            border: 1px solid #d7e0e9;
            border-bottom: 3px solid #94a3b8;
            border-radius: 12px;
            box-shadow: 0 3px 10px rgba(26, 45, 68, 0.05);
        }
        .sg-metric-label {
            color: #53657a;
            font-size: 0.78rem;
            font-weight: 600;
        }
        .sg-metric-value {
            color: #172b43;
            font-size: 1.8rem;
            font-weight: 700;
            line-height: 1;
        }
        .sg-metric-total {
            background: linear-gradient(145deg, #172b43, #294967);
            border-color: #294967;
            border-bottom-color: #8ed8c3;
        }
        .sg-metric-total .sg-metric-label { color: #d5e1ec; }
        .sg-metric-total .sg-metric-value { color: #ffffff; }
        .sg-metric-new { border-bottom-color: #5b8def; }
        .sg-metric-contacted { border-bottom-color: #e6a23c; }
        .sg-metric-qualified { border-bottom-color: #36a879; }
        .sg-metric-proposal { border-bottom-color: #9570d5; }
        .sg-metric-won { border-bottom-color: #159b83; }
        .sg-metric-lost { border-bottom-color: #d86b66; }
        .sg-directory-spacer { height: 0.65rem; }
        @media (max-width: 900px) {
            .sg-metrics-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        }
        .sg-detail-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
            gap: 0.65rem;
            margin: 0.55rem 0 0.65rem 0;
        }
        .sg-detail-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 0.7rem 0.85rem;
            min-width: 0;
        }
        .sg-detail-label {
            font-size: 0.67rem;
            font-weight: 700;
            color: #64748b;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }
        .sg-detail-value {
            font-size: 0.92rem;
            font-weight: 700;
            color: #172b43;
            line-height: 1.3;
            word-break: break-word;
        }
        .sg-detail-sub {
            font-size: 0.75rem;
            color: #475569;
            margin-top: 0.18rem;
            word-break: break-word;
        }
        .sg-tags-box {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 0.65rem 0.85rem;
            margin-bottom: 0.75rem;
        }
        .sg-tags-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.38rem;
            margin-top: 0.25rem;
        }
        .sg-tag-pill {
            background: #edf4ff;
            border: 1px solid #d8e7ff;
            color: #2459a6;
            border-radius: 6px;
            padding: 0.2rem 0.52rem;
            font-size: 0.74rem;
            font-weight: 600;
        }
        @media (max-width: 560px) {
            .sg-metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        div[data-testid="stRadio"] div[role="radiogroup"] {
            gap: 0.6rem;
            align-items: center;
            padding: 0.55rem;
            background: #dce4ed;
            border: 1px solid #cbd5e1;
            border-radius: 12px;
        }
        div[data-testid="stRadio"] {
            position: sticky;
            top: 9.6rem;
            z-index: 999;
            padding: 0.3rem 0;
            background: #edf1f6;
        }
        div[data-testid="stRadio"] div[role="radiogroup"] label {
            padding: 0.65rem 1rem;
            border-radius: 9px;
        }
        div[data-testid="stRadio"] input[type="radio"] { accent-color: #8ed8c3; }
        div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {
            color: #ffffff;
            background: #1e3a56;
        }
        div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p {
            color: #ffffff;
            font-weight: 600;
        }
        div[data-testid="stTabs"] [role="tablist"] {
            gap: 0.35rem;
            border-bottom: 1px solid #d7e0e9;
        }
        div[data-testid="stTabs"] button[role="tab"] {
            border-radius: 9px 9px 0 0;
            color: #53657a;
            font-weight: 600;
        }
        div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            color: #176f5b;
            border-bottom-color: #55b99b;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #ffffff;
            border-color: #d7e0e9;
            border-radius: 13px;
            box-shadow: 0 3px 12px rgba(26, 45, 68, 0.04);
        }
        .stButton > button, .stLinkButton > a {
            border-radius: 9px;
            font-weight: 550;
            transition: transform 120ms ease, box-shadow 120ms ease;
        }
        .stButton > button:hover, .stLinkButton > a:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(26, 45, 68, 0.12);
        }
        div[data-baseweb="input"] > div,
        div[data-baseweb="textarea"] > div,
        div[data-baseweb="select"] > div {
            border-color: #cbd5e1;
            border-radius: 9px;
        }
        div[data-baseweb="input"] > div:focus-within,
        div[data-baseweb="textarea"] > div:focus-within,
        div[data-baseweb="select"] > div:focus-within {
            border-color: #55b99b;
            box-shadow: 0 0 0 2px rgba(85, 185, 155, 0.16);
        }
        h1, h2, h3, h4 { color: #172b43; }
        div[data-testid="stCaptionContainer"],
        div[data-testid="stCaptionContainer"] p {
            color: #475569 !important;
            opacity: 1 !important;
        }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.22rem 0.58rem;
            border: 1px solid;
            border-radius: 999px;
            font-size: 0.73rem;
            font-weight: 650;
            white-space: nowrap;
        }
        .status-pill::before {
            width: 0.42rem;
            height: 0.42rem;
            content: "";
            background: currentColor;
            border-radius: 50%;
        }
        .status-new { color: #2459a6; background: #edf4ff; border-color: #d8e7ff; }
        .status-contacted { color: #98620b; background: #fff6e5; border-color: #f9e4b4; }
        .status-qualified { color: #17764a; background: #eaf8f0; border-color: #ccebd8; }
        .status-proposal { color: #6741a5; background: #f3edff; border-color: #e4d8ff; }
        .status-won { color: #08735c; background: #e7f8f2; border-color: #c9eee1; }
        .status-lost { color: #a63737; background: #fff0ef; border-color: #f5d3d0; }
        .sg-state-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.3rem 0.65rem;
            border: 1px solid;
            border-radius: 999px;
            font-size: 0.76rem;
            font-weight: 700;
            line-height: 1.2;
            white-space: nowrap;
        }
        .sg-state-dot { width: 0.48rem; height: 0.48rem; border-radius: 50%; }
        .sg-state-success { color: #176f4c; background: #eaf8f0; border-color: #ccebd8; }
        .sg-state-success .sg-state-dot { background: #25a56f; }
        .sg-state-error { color: #a63737; background: #fff0ef; border-color: #f5d3d0; }
        .sg-state-error .sg-state-dot { background: #d9534f; }
        .sg-state-warning { color: #98620b; background: #fff6e5; border-color: #f9e4b4; }
        .sg-state-warning .sg-state-dot { background: #d99a25; }
        .sg-state-neutral { color: #53657a; background: #f1f5f9; border-color: #d7e0e9; }
        .sg-state-neutral .sg-state-dot { background: #94a3b8; }
        .sg-intel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin: 0.75rem 0 0.65rem 0;
        }
        .sg-intel-heading {
            font-size: 1.05rem;
            font-weight: 700;
            color: #172b43;
        }
        .sg-ai-badge {
            display: inline-flex;
            align-items: center;
            padding: 0.22rem 0.65rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            color: #ffffff;
            background: linear-gradient(135deg, #6d28d9 0%, #4f46e5 100%);
            letter-spacing: 0.02em;
        }
        .sg-intel-summary {
            background: #f8fafc;
            border: 1px solid #d7e0e9;
            border-radius: 10px;
            padding: 0.85rem 1rem;
            font-size: 0.9rem;
            line-height: 1.55;
            color: #263552;
            margin-bottom: 0.85rem;
        }
        .sg-score-panel {
            background: #ffffff;
            border: 1px solid #d7e0e9;
            border-radius: 12px;
            padding: 0.95rem 1.05rem;
            margin-bottom: 0.95rem;
        }
        .sg-score-top {
            display: flex;
            align-items: center;
            gap: 0.95rem;
            padding-bottom: 0.75rem;
            margin-bottom: 0.75rem;
            border-bottom: 1px solid #eef2f6;
        }
        .sg-score-ring-wrap {
            position: relative;
            width: 74px;
            height: 74px;
            flex-shrink: 0;
        }
        .sg-score-ring {
            width: 74px;
            height: 74px;
            transform: rotate(-90deg);
            display: block;
        }
        .sg-ring-bg {
            fill: none;
            stroke: #e2e8f0;
            stroke-width: 7;
        }
        .sg-ring-fg {
            fill: none;
            stroke-width: 7;
            stroke-linecap: round;
        }
        .sg-score-value {
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            transform: translateY(-50%);
            text-align: center;
            font-size: 1.35rem;
            font-weight: 800;
            line-height: 1;
        }
        .sg-score-meta {
            min-width: 0;
            flex: 1;
        }
        .sg-score-label {
            font-size: 0.92rem;
            font-weight: 700;
            color: #172b43;
        }
        .sg-score-sub {
            font-size: 0.8rem;
            font-weight: 700;
            margin-top: 0.12rem;
        }
        .sg-score-details {
            min-width: 0;
        }
        .sg-score-details-title {
            font-size: 0.76rem;
            font-weight: 700;
            color: #172b43;
            margin-bottom: 0.45rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .sg-signal-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin-bottom: 0.5rem;
        }
        .sg-signal-chip {
            background: #f1f5f9;
            border: 1px solid #dce4ec;
            border-radius: 7px;
            padding: 0.22rem 0.5rem;
            font-size: 0.74rem;
            font-weight: 500;
            color: #263552;
            line-height: 1.35;
        }
        .sg-intel-rationale {
            font-size: 0.78rem;
            color: #475569;
            line-height: 1.48;
        }
        .sg-score-note {
            font-size: 0.71rem;
            color: #64748b;
            margin-top: 0.2rem;
        }
        .sg-intel-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 0.85rem;
            align-items: start;
        }
        .sg-col-heading {
            font-size: 0.82rem;
            font-weight: 700;
            color: #172b43;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 0.45rem;
        }
        .sg-intel-card {
            background: #ffffff;
            border: 1px solid #d7e0e9;
            border-left: 3.5px solid #2459a6;
            border-radius: 9px;
            padding: 0.7rem 0.85rem;
            margin-bottom: 0.55rem;
        }
        .sg-intel-opp {
            border-left-color: #21a3ae;
        }
        .sg-intel-empty {
            border-left-color: #94a3b8;
            background: #f8fafc;
        }
        .sg-intel-title {
            font-size: 0.86rem;
            font-weight: 700;
            color: #172b43;
            margin-bottom: 0.2rem;
        }
        .sg-intel-desc {
            font-size: 0.82rem;
            line-height: 1.45;
            color: #475569;
        }
        .sg-detail-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
            gap: 0.65rem;
            margin: 0.55rem 0 0.65rem 0;
        }
        .sg-detail-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 0.7rem 0.85rem;
            min-width: 0;
        }
        .sg-detail-label {
            font-size: 0.67rem;
            font-weight: 700;
            color: #64748b;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }
        .sg-detail-value {
            font-size: 0.92rem;
            font-weight: 700;
            color: #172b43;
            line-height: 1.3;
            word-break: break-word;
        }
        .sg-detail-sub {
            font-size: 0.75rem;
            color: #475569;
            margin-top: 0.18rem;
            word-break: break-word;
        }
        .sg-tags-box {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 0.65rem 0.85rem;
            margin-bottom: 0.75rem;
        }
        .sg-tags-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.38rem;
            margin-top: 0.25rem;
        }
        .sg-tag-pill {
            background: #edf4ff;
            border: 1px solid #d8e7ff;
            color: #2459a6;
            border-radius: 6px;
            padding: 0.2rem 0.52rem;
            font-size: 0.74rem;
            font-weight: 600;
        }
        .sg-outreach-card {
            background: #ffffff;
            border: 1px solid #d7e0e9;
            border-radius: 13px;
            padding: 1.05rem 1.15rem;
            box-shadow: 0 3px 12px rgba(26, 45, 68, 0.04);
            margin-bottom: 0.75rem;
        }
        .sg-big-ring-wrap {
            position: relative;
            width: 112px;
            height: 112px;
            margin: 0.6rem auto 0.35rem auto;
        }
        .sg-big-ring {
            width: 112px;
            height: 112px;
            transform: rotate(-90deg);
            display: block;
        }
        .sg-big-score-val {
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            transform: translateY(-50%);
            text-align: center;
            font-size: 2rem;
            font-weight: 800;
            color: #172b43;
            line-height: 1;
        }
        .sg-big-score-sub {
            text-align: center;
            font-size: 0.85rem;
            font-weight: 600;
            color: #475569;
            margin-bottom: 0.8rem;
        }
        .sg-prob-row {
            display: flex;
            justify-content: space-between;
            font-size: 0.78rem;
            color: #475569;
            margin-bottom: 0.3rem;
        }
        .sg-prob-track {
            width: 100%;
            height: 7px;
            background: #e2e8f0;
            border-radius: 999px;
            overflow: hidden;
        }
        .sg-prob-fill {
            height: 100%;
            background: linear-gradient(90deg, #10b981 0%, #21a3ae 100%);
            border-radius: 999px;
        }
        .sg-factor-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.42rem 0;
            border-bottom: 1px solid #f1f5f9;
        }
        .sg-factor-row:last-of-type { border-bottom: none; }
        .sg-factor-left {
            display: flex;
            align-items: center;
            gap: 0.45rem;
        }
        .sg-factor-icon { font-size: 0.9rem; }
        .sg-factor-name {
            font-size: 0.82rem;
            font-weight: 600;
            color: #172b43;
        }
        .sg-factor-pts {
            font-size: 0.76rem;
            font-weight: 700;
            color: #15803d;
            background: #ecfdf5;
            border: 1px solid #bbf7d0;
            border-radius: 6px;
            padding: 0.14rem 0.45rem;
        }
        .sg-strat-item {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 0.75rem 0.9rem;
            margin-bottom: 0.65rem;
        }
        .sg-strat-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 0.28rem;
        }
        .sg-strat-title {
            font-size: 0.88rem;
            font-weight: 700;
            color: #172b43;
        }
        .sg-prio-badge {
            font-size: 0.7rem;
            font-weight: 700;
            padding: 0.14rem 0.5rem;
            border-radius: 6px;
        }
        .sg-prio-high { color: #b91c1c; background: #fee2e2; }
        .sg-prio-med { color: #a16207; background: #fef3c7; }
        .sg-strat-body {
            font-size: 0.82rem;
            color: #334155;
            line-height: 1.45;
        }
        .sg-strat-meta {
            font-size: 0.73rem;
            color: #64748b;
            margin-top: 0.35rem;
        }
        .sg-email-meta-row {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 0.48rem 0.75rem;
            margin-bottom: 0.45rem;
            font-size: 0.84rem;
        }
        .sg-email-meta-label {
            color: #64748b;
            font-weight: 600;
            min-width: 56px;
        }
        .sg-email-meta-val {
            color: #172b43;
            word-break: break-word;
        }
        .sg-email-body-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 1rem 1.1rem;
            margin-top: 0.5rem;
            font-size: 0.9rem;
            line-height: 1.62;
            color: #1e293b;
        }
        .sg-point-item {
            display: flex;
            align-items: flex-start;
            gap: 0.5rem;
            font-size: 0.84rem;
            color: #263552;
            line-height: 1.45;
            margin-bottom: 0.35rem;
        }
        .sg-point-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #2563eb;
            margin-top: 0.42rem;
            flex-shrink: 0;
        }
        .sg-action-card {
            background: #fefce8;
            border: 1px solid #fde68a;
            border-radius: 8px;
            padding: 0.55rem 0.75rem;
            margin-bottom: 0.45rem;
        }
        .sg-action-meta {
            display: flex;
            justify-content: space-between;
            font-size: 0.72rem;
            font-weight: 700;
            color: #b45309;
            margin-bottom: 0.18rem;
        }
        .sg-action-text {
            font-size: 0.83rem;
            color: #1e293b;
            line-height: 1.4;
        }
        .sg-timeline-row {
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            padding: 0.65rem 0;
            border-bottom: 1px solid #f1f5f9;
        }
        .sg-timeline-row:last-child { border-bottom: none; }
        .sg-timeline-icon {
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.95rem;
            flex-shrink: 0;
        }
        @media (max-width: 560px) {
            .sg-page-header { padding: 1.1rem 1.2rem; }
            .sg-score-panel { flex-direction: column; align-items: flex-start; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="sg-brandbar">
            <div class="sg-brand-mark">SG</div>
            <div>
                <div class="sg-brand-name">SalesGenie AI</div>
                <div class="sg-brand-subtitle">LEAD INTELLIGENCE WORKSPACE</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    page = st.radio(
        "Workspace navigation",
        ["Leads", "Add Lead", "Import CSV", "Outreach", "Conversations"],
        horizontal=True,
        label_visibility="collapsed",
        key="navigation",
    )
    st.caption("Local development workspace · Authentication is not enabled")
    if page == "Leads":
        render_leads()
    elif page == "Add Lead":
        render_add_lead()
    elif page == "Import CSV":
        render_import()
    elif page == "Outreach":
        render_outreach()
    else:
        render_conversations()


if __name__ == "__main__":
    main()