from __future__ import annotations

import html
import io
import re
import zlib
from urllib.parse import quote

import streamlit as st
from PIL import Image

from api.enrichment import get_lead_firmographics
from ui.client import (
    ANALYSIS_TIMEOUT,
    ApiRequestError,
    api_request,
    fetch_all_leads,
    show_api_error,
)
from ui.components import (
    render_crm_sync_record,
    render_page_header,
    set_navigation,
)

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


