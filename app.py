from __future__ import annotations

import os
from collections import Counter
from math import ceil
from urllib.parse import quote

import requests
import streamlit as st
from dotenv import load_dotenv


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
    st.subheader("Add a lead")
    with st.form("add_lead_form", clear_on_submit=True):
        company_name = st.text_input("Company name *")
        industry = st.text_input("Industry")
        contact_name = st.text_input("Contact name")
        email = st.text_input("Email")
        phone = st.text_input("Phone")
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
                },
            )
            st.success(f"Added {lead['company_name']} (lead ID {lead['lead_id']}).")
        except ApiRequestError as error:
            show_api_error(error)


def render_import() -> None:
    st.subheader("Import leads from CSV")
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
            title, status_column = st.columns([3, 1])
            title.markdown(f"#### {lead['company_name']}")
            status_column.markdown(
                f"<span class='status-pill status-{lead['lead_status'].lower()}'>"
                f"{lead['lead_status']}</span>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"Lead #{lead_id} · {lead['industry'] or 'Industry not set'}"
            )
            st.markdown("##### Contact")
            contact_left, contact_right = st.columns(2)
            contact_left.write(lead["contact_name"] or "No contact name")
            contact_left.caption(lead["email"] or "No email")
            contact_right.write(lead["phone"] or "No phone")
            st.divider()

            with st.expander("Edit lead", expanded=True):
                with st.form(f"update-lead-{lead_id}"):
                    company_name = st.text_input("Company", value=lead["company_name"])
                    industry = st.text_input("Industry", value=lead["industry"] or "")
                    contact_name = st.text_input("Contact", value=lead["contact_name"] or "")
                    email = st.text_input("Email", value=lead["email"] or "")
                    phone = st.text_input("Phone", value=lead["phone"] or "")
                    new_status = st.selectbox(
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
            if st.button("Analyze company", type="primary", key=f"analyze-{lead_id}"):
                with st.spinner("Generating and saving company insights..."):
                    try:
                        result = api_request(
                            "POST",
                            f"/api/v1/leads/{lead_id}/analysis",
                            json={"context": context or None},
                            timeout=ANALYSIS_TIMEOUT,
                        )
                        st.session_state[f"analysis-{lead_id}"] = result
                    except ApiRequestError as error:
                        show_api_error(error)
            render_saved_analysis(lead_id)


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
    st.markdown("##### Saved insights")
    st.write(saved["summary"])
    left, right = st.columns(2)
    with left:
        st.markdown("**Potential needs**")
        st.write(saved["potential_needs"] or ["No needs were identified."])
    with right:
        st.markdown("**Opportunities**")
        st.write(saved["opportunities"] or ["No opportunities were identified."])
    qualification = saved["qualification"]
    st.metric("Estimated qualification score", f"{qualification['score']}/100")
    st.caption(qualification["rationale"])
    st.caption("Estimate only; this is not a predicted conversion probability.")


def set_navigation(page: str) -> None:
    st.session_state["navigation"] = page


def render_outreach() -> None:
    st.title("Outreach strategy")
    st.caption(
        "Review an explainable readiness estimate and create personalized drafts. "
        "Drafts are saved for human review; SalesGenie does not send email."
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
    selected_label = st.selectbox("Select a lead", labels, key="outreach-lead")
    lead = lead_by_label[selected_label]
    lead_id = lead["lead_id"]
    st.markdown(
        f"**{lead['company_name']}** · {lead['contact_name'] or 'Contact not set'} · "
        f"{lead['industry'] or 'Industry not set'} · {lead['lead_status']}"
    )

    st.markdown("### Lead score and next-best action")
    if st.button("Calculate / refresh score", type="primary", key=f"score-{lead_id}"):
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
        score_column, label_column = st.columns([1, 3])
        score_column.metric(
            "Estimated sales readiness",
            f"{score['score']}/100",
            score["score_label"].title(),
        )
        label_column.caption(score["rationale"])
        st.caption("Rule-based estimate, not a calibrated conversion probability.")
        factor_columns = st.columns(4)
        for column, factor in zip(
            factor_columns,
            ("fit", "engagement", "intent", "decision_readiness"),
        ):
            column.metric(factor.replace("_", " ").title(), f"{score['factors'][factor]}/25")
        recommendation = score["recommendation"]
        with st.container(border=True):
            st.markdown("**Recommended next action**")
            st.write(recommendation["action"])
            st.caption(
                f"{recommendation['timing']} · {recommendation['channel']} · "
                f"{recommendation['rationale']}"
            )

    with st.expander("Log a sales activity", expanded=False):
        with st.form(f"activity-form-{lead_id}"):
            activity_type = st.selectbox(
                "Activity", ["call", "email", "meeting", "reply", "note"]
            )
            activity_note = st.text_area("Outcome or notes", max_chars=2000)
            activity_submitted = st.form_submit_button("Save activity")
        if activity_submitted:
            try:
                api_request(
                    "POST",
                    f"/api/v1/leads/{lead_id}/activities",
                    json={
                        "activity_type": activity_type,
                        "details": activity_note or None,
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

    st.markdown("### Generate personalized outreach")
    with st.form(f"outreach-form-{lead_id}"):
        draft_type = st.selectbox("Draft type", ["email", "message"])
        tone = st.selectbox(
            "Tone", ["professional", "friendly", "concise", "persuasive"]
        )
        length = st.selectbox("Length", ["short", "medium", "long"])
        goal = st.text_input("Goal", value="Start a relevant sales conversation")
        pain_point_text = st.text_area(
            "Known prospect needs or pain points",
            help="Use verified notes only. Enter one item per line.",
        )
        generate = st.form_submit_button("Generate / regenerate draft", type="primary")
    if generate:
        pain_points = [
            item.strip() for item in pain_point_text.splitlines() if item.strip()
        ]
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

    try:
        drafts = api_request("GET", f"/api/v1/leads/{lead_id}/outreach-drafts")
    except ApiRequestError as error:
        show_api_error(error)
        return
    if not drafts:
        st.info("No outreach drafts saved for this lead yet.")
        return
    draft = drafts[0]
    st.markdown("#### Latest saved draft")
    st.caption("Use the copy control on the draft below, or download it for review.")
    st.code(draft["content"])
    st.download_button(
        "Download draft",
        data=draft["content"],
        file_name=f"salesgenie-{draft['draft_type']}-draft-{draft['draft_id']}.txt",
        mime="text/plain",
        key=f"download-draft-{draft['draft_id']}",
    )
    with st.form(f"edit-draft-{draft['draft_id']}"):
        edited_content = st.text_area(
            "Edit draft",
            value=draft["content"],
            height=240,
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
            subject, separator, body = draft["content"].partition("\n\n")
            if subject.startswith("Subject: "):
                subject = subject.removeprefix("Subject: ")
            else:
                body = draft["content"]
                subject = ""
            mailto_url = (
                f"mailto:{quote(lead['email'], safe='@')}"
                f"?subject={quote(subject)}&body={quote(body if separator else draft['content'])}"
            )
            st.link_button("Open in email client", mailto_url)
            st.caption("Review the recipient and content in your email client before sending.")
        else:
            st.info("Add an email address to open this draft in your email client.")


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
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #ffffff;
            border-color: #d7e0e9;
            border-radius: 13px;
            box-shadow: 0 3px 12px rgba(26, 45, 68, 0.04);
        }
        .stButton > button, .stLinkButton > a {
            border-radius: 9px;
            font-weight: 550;
        }
        h1, h2, h3, h4 { color: #172b43; }
        div[data-testid="stCaptionContainer"],
        div[data-testid="stCaptionContainer"] p {
            color: #475569 !important;
            opacity: 1 !important;
        }
        .status-pill {
            display: inline-block;
            padding: 0.15rem 0.5rem;
            border: 1px solid transparent;
            border-radius: 999px;
            font-size: 0.72rem;
            white-space: nowrap;
        }
        .status-new { color: #2459a6; background: #edf4ff; border-color: #d8e7ff; }
        .status-contacted { color: #98620b; background: #fff6e5; border-color: #f9e4b4; }
        .status-qualified { color: #17764a; background: #eaf8f0; border-color: #ccebd8; }
        .status-proposal { color: #6741a5; background: #f3edff; border-color: #e4d8ff; }
        .status-won { color: #08735c; background: #e7f8f2; border-color: #c9eee1; }
        .status-lost { color: #a63737; background: #fff0ef; border-color: #f5d3d0; }
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
        ["Leads", "Add Lead", "Import CSV", "Outreach"],
        horizontal=True,
        label_visibility="collapsed",
        key="navigation",
    )
    st.caption("Local development workspace · Authentication is not enabled")
    if page == "Leads":
        render_leads()
    elif page == "Add Lead":
        st.title("Add a lead")
        st.caption("Create a prospect record for your sales pipeline.")
        render_add_lead()
    elif page == "Import CSV":
        st.title("Import leads")
        st.caption("Add multiple prospects to your sales pipeline from a CSV file.")
        render_import()
    else:
        render_outreach()


if __name__ == "__main__":
    main()