from __future__ import annotations

import streamlit as st

from ui.pages.conversations import render_conversations
from ui.pages.dashboard import render_dashboard
from ui.pages.leads import render_add_lead, render_import, render_leads
from ui.pages.outreach import render_outreach
from ui.styles import load_app_css


def main() -> None:
    st.set_page_config(
        page_title="SalesGenie AI",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(load_app_css(), unsafe_allow_html=True)
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
        ["Leads", "Add Lead", "Import CSV", "Outreach", "Conversations", "Dashboard"],
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
    elif page == "Conversations":
        render_conversations()
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
