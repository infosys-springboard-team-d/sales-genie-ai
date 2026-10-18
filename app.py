from __future__ import annotations

import os

import requests
import streamlit as st
from dotenv import load_dotenv


load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = 10
ANALYSIS_TIMEOUT = 60
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
            "Cannot reach the SalesGenie API. Start it on http://127.0.0.1:8000."
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
    st.caption("UTF-8 CSV. Required column: company_name. Import is all-or-nothing: any invalid or duplicate row rejects the whole file.")
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
            st.success(
                f"Import complete: created {result['created']}."
            )
        else:
            st.error(
                f"Nothing imported. Duplicates: {result['duplicates']} · "
                f"invalid rows: {result['rejected']} · "
                f"valid rows rolled back: {len(result['rolled_back_rows'])}"
            )
        if result["row_errors"]:
            st.dataframe(result["row_errors"], use_container_width=True, hide_index=True)


def render_leads() -> None:
    st.subheader("Leads")
    with st.form("lead_search"):
        query = st.text_input("Search company, contact, email, or industry")
        status = st.selectbox("Status", ["All"] + STATUSES)
        st.form_submit_button("Search")
    page_size = 20
    params: dict[str, object] = {"page": 1, "page_size": page_size}
    if query.strip():
        params["q"] = query.strip()
    if status != "All":
        params["status"] = status
    try:
        result = api_request("GET", "/api/v1/leads", params=params)
    except ApiRequestError as error:
        show_api_error(error)
        return
    st.caption(f"{result['total']} lead(s)")
    if result["total"] == 0:
        st.info("No leads match this search.")
        return
    page_count = max(1, (result["total"] + page_size - 1) // page_size)
    if st.session_state.get("lead_page", 1) > page_count:
        st.session_state["lead_page"] = 1
    page = st.selectbox("Page", range(1, page_count + 1), key="lead_page")
    if page != result["page"]:
        params["page"] = page
        try:
            result = api_request("GET", "/api/v1/leads", params=params)
        except ApiRequestError as error:
            show_api_error(error)
            return
    leads = result["items"]
    st.dataframe(
        [
            {
                "ID": item["lead_id"],
                "Company": item["company_name"],
                "Industry": item["industry"],
                "Contact": item["contact_name"],
                "Email": item["email"],
                "Status": item["lead_status"],
            }
            for item in leads
        ],
        use_container_width=True,
        hide_index=True,
    )
    labels = {
        f"{item['company_name']} · ID {item['lead_id']}": item["lead_id"]
        for item in leads
    }
    selection = st.selectbox("Lead details", list(labels))
    lead_id = labels[selection]
    try:
        lead = api_request("GET", f"/api/v1/leads/{lead_id}")
    except ApiRequestError as error:
        show_api_error(error)
        return

    st.markdown("#### Update lead")
    with st.form(f"update-lead-{lead_id}"):
        company_name = st.text_input("Company", value=lead["company_name"])
        industry = st.text_input("Industry", value=lead["industry"] or "")
        contact_name = st.text_input("Contact", value=lead["contact_name"] or "")
        email = st.text_input("Email", value=lead["email"] or "")
        phone = st.text_input("Phone", value=lead["phone"] or "")
        save = st.form_submit_button("Save lead changes")
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
            st.success("Lead details saved.")
            st.rerun()
        except ApiRequestError as error:
            show_api_error(error)

    with st.form(f"update-status-{lead_id}"):
        new_status = st.selectbox(
            "Lifecycle status",
            STATUSES,
            index=STATUSES.index(lead["lead_status"]),
        )
        save_status = st.form_submit_button("Save status")
    if save_status:
        try:
            api_request(
                "PATCH",
                f"/api/v1/leads/{lead_id}/status",
                json={"lead_status": new_status},
            )
            st.success("Lead status saved.")
            st.rerun()
        except ApiRequestError as error:
            show_api_error(error)

    st.markdown("#### Company intelligence")
    context = st.text_area(
        "Optional company/industry notes for analysis",
        key=f"analysis-context-{lead_id}",
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


def main() -> None:
    st.set_page_config(page_title="SalesGenie AI", page_icon="📈", layout="wide")
    st.title("SalesGenie AI")
    st.caption("Milestone 1 · Lead management and saved company intelligence")
    st.sidebar.warning("Local development only. Authentication is not included.")
    page = st.sidebar.radio("Navigation", ["Leads", "Add Lead", "Import CSV"])
    if page == "Leads":
        render_leads()
    elif page == "Add Lead":
        render_add_lead()
    else:
        render_import()


if __name__ == "__main__":
    main()
