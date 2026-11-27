from __future__ import annotations

import html

import streamlit as st

from ui.client import (
    ANALYSIS_TIMEOUT,
    REQUEST_TIMEOUT,
    ApiRequestError,
    api_request,
    fetch_all_leads,
    show_api_error,
)
from ui.components import (
    crm_status_badge,
    render_crm_sync_record,
    render_page_header,
    set_navigation,
)
from ui.pages.outreach import _extract_activity_file_note

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


