from __future__ import annotations

import html
from collections import Counter
from math import ceil

import streamlit as st

from api.enrichment import get_lead_firmographics
from ui.client import (
    ANALYSIS_TIMEOUT,
    API_BASE_URL,
    STATUSES,
    ApiRequestError,
    api_request,
    fetch_all_leads,
    show_api_error,
)
from ui.components import (
    clear_lead_filters,
    render_crm_sync_record,
    render_page_header,
    render_saved_analysis,
    select_dashboard_lead,
    set_navigation,
)
from ui.pages.outreach import _extract_activity_file_note

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


