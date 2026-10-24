from __future__ import annotations

import os
from collections import Counter
from math import ceil

import requests
import streamlit as st
from dotenv import load_dotenv


load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = 10
ANALYSIS_TIMEOUT = 180
STATUSES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]


class ApiRequestError(Exception):
    pass


def api_request(
    method: str,
    path: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
    **kwargs: object,
) -> dict:
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
        raise ApiRequestError(message)
    if not isinstance(body, dict):
        raise ApiRequestError("The API returned an unexpected response.")
    return body


def show_api_error(error: ApiRequestError) -> None:
    st.error(str(error))


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
        first_page = api_request(
            "GET", "/api/v1/leads", params={"page": 1, "page_size": 100}
        )
        leads = first_page["items"]
        api_page_count = ceil(first_page["total"] / 100)
        for page_number in range(2, api_page_count + 1):
            page_result = api_request(
                "GET",
                "/api/v1/leads",
                params={"page": page_number, "page_size": 100},
            )
            leads.extend(page_result["items"])
    except ApiRequestError as error:
        show_api_error(error)
        return

    st.caption(f"API connected · {API_BASE_URL}")
    st.markdown("### Lead overview")
    st.caption("Search, manage, and review your sales prospects.")

    counts = Counter(lead["lead_status"] for lead in leads)
    metrics = [("Total leads", len(leads))] + [
        (status, counts[status]) for status in STATUSES
    ]
    for column, (label, value) in zip(st.columns(7), metrics):
        with column:
            st.metric(label, value)

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

    add_action, import_action = st.columns(2)
    with add_action:
        with st.expander("＋ Add lead", expanded=False):
            render_add_lead()
    with import_action:
        with st.expander("⇧ Import CSV", expanded=False):
            render_import()

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


def main() -> None:
    st.set_page_config(
        page_title="SalesGenie AI",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .stApp { background: #f7f8fc; color: #1f2937; }
        .block-container { max-width: 1680px; padding-top: 1.4rem; }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e6e9f0;
            border-radius: 10px;
            padding: 0.7rem 0.85rem;
        }
        div[data-testid="stMetricLabel"] { color: #667085; }
        div[data-testid="stMetricValue"] { color: #1f2937; }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #ffffff;
            border-color: #e6e9f0;
            border-radius: 10px;
        }
        .stButton > button { border-radius: 7px; }
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
    st.sidebar.warning("Local development only. Authentication is not included.")
    page = st.sidebar.radio(
        "Navigation", ["Leads", "Add Lead", "Import CSV"], key="navigation"
    )
    if page == "Leads":
        title, add_action, import_action, docs_action = st.columns([3.8, 1, 1, 0.8])
        with title:
            st.title("SalesGenie AI | Leads")
            st.caption("Sales workspace · Lead management and company intelligence")
        add_action.button(
            "Add lead",
            use_container_width=True,
            on_click=set_navigation,
            args=("Add Lead",),
        )
        import_action.button(
            "Import CSV",
            use_container_width=True,
            on_click=set_navigation,
            args=("Import CSV",),
        )
        docs_action.link_button(
            "API docs",
            f"{API_BASE_URL}/docs",
            use_container_width=True,
        )
        render_leads()
    elif page == "Add Lead":
        st.title("SalesGenie AI")
        st.caption("Lead pipeline · Company intelligence")
        render_add_lead()
    else:
        st.title("SalesGenie AI")
        st.caption("Lead pipeline · Company intelligence")
        render_import()


if __name__ == "__main__":
    main()