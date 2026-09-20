"""
app.py — AML Compliance Suite (Streamlit entrypoint)

Three tabs:
  1. Data Ingestion Hub  — upload policy PDFs and transaction CSVs
  2. Risk Scoring Dashboard — run the AML agent, review flagged customers
  3. Policy Chatbot — RAG-powered Q&A over uploaded policy documents
"""

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from utils.formatting import clean_llm_markdown, render_llm_markdown
from utils.ui import (
    app_header,
    inject_custom_css,
    metric_row,
    notify,
    risk_badge_html,
    risk_color,
    section_header,
    stat_card,
    sub_section,
)

load_dotenv()

st.set_page_config(
    page_title="AML Compliance Suite",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_custom_css()

# ---------------------------------------------------------------------
# Environment sanity check
# ---------------------------------------------------------------------
missing_env = [
    var for var in ["GROQ_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"]
    if not os.getenv(var)
]
if missing_env:
    st.error(
        "⚠️ Missing required environment variables: "
        f"**{', '.join(missing_env)}**.\n\n"
        "Copy `.env.example` to `.env` and fill in your Groq and Supabase "
        "credentials, then restart the app."
    )
    st.stop()

# Deferred imports after env check
from services.pdf_rag import (
    ingest_policy_pdf,
    list_policy_documents,
    delete_policy_document,
    delete_all_policy_documents,
)
from services.csv_parser import (
    ingest_transactions_csv,
    delete_customer_by_external_id,
    delete_all_customers_and_transactions,
)
from services.aml_agent import (
    get_customer_audit_details,
    get_customer_summary_table,
    run_full_evaluation,
)
from services.rag_chat import answer_question
from agents.aml_investigation_agent import run_investigation
from agents.agent_models import InvestigationResult
from services.agent_audit import log_investigation, mark_risk_update_approved, list_recent_investigations
from mcp_client.agent_mcp_client import call_tool

# ---------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []  # list of {"role", "content", "sources"}
if "last_evaluation_results" not in st.session_state:
    st.session_state.last_evaluation_results = None
if "queued_prompt" not in st.session_state:
    st.session_state.queued_prompt = None
if "last_investigation" not in st.session_state:
    st.session_state.last_investigation = None
if "last_investigation_logged" not in st.session_state:
    st.session_state.last_investigation_logged = False

# =======================================================================
# Header — clean page title without the left sidebar
# =======================================================================
app_header(
    "🛡️ AML Compliance Suite",
    "AI-assisted transaction monitoring, risk scoring, and policy Q&A for compliance teams.",
)

tab_ingest, tab_dashboard, tab_chat, tab_agent = st.tabs(
    ["📥 Data Ingestion", "📊 Risk Dashboard", "💬 Policy Chatbot", "🤖 AI Investigation Agent"]
)

# =======================================================================
# TAB 1 — Data Ingestion Hub
# =======================================================================
with tab_ingest:
    section_header("📥 Data Ingestion Hub", icon="📥")
    st.caption("Upload policy PDFs and transaction CSVs. All data is stored securely in Supabase.")
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
            <div class="section-card">
                <div class="section-card-title"><span class="emoji-icon">📄</span> Policy Documents (PDF)</div>
                <div style="color:#64748B; font-size:0.9rem;">
                    Upload AML policy PDFs. Text is chunked and embedded locally,
                    then stored in Supabase for RAG search.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        pdf_files = st.file_uploader(
            "Drop policy PDF(s) here",
            type=["pdf"],
            accept_multiple_files=True,
            key="pdf_uploader",
        )
        if pdf_files and st.button("Ingest PDF(s)", key="ingest_pdf_btn"):
            for f in pdf_files:
                with st.spinner(f"Processing {f.name}..."):
                    try:
                        result = ingest_policy_pdf(f.read(), f.name)
                        notify(f"'{result.file_name}' ingested — {result.num_chunks} chunks embedded.", "success")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        notify(f"Failed to ingest '{f.name}': {exc}", "error")
                        st.error(f"❌ Failed to ingest '{f.name}': {exc}")

        st.markdown("**Existing policy documents:**")
        try:
            docs = list_policy_documents()
            if docs:
                for doc in docs:
                    d_col1, d_col2 = st.columns([3, 1])
                    with d_col1:
                        st.markdown(
                            f"📄 **{doc['file_name']}**  "
                            f'<span class="status-pill">Indexed</span><br>'
                            f'<span style="color:#94A3B8; font-size:0.82rem;">Uploaded {doc["uploaded_at"][:10]}</span>',
                            unsafe_allow_html=True,
                        )
                    if d_col2.button("🗑️ Delete", key=f"del_{doc['id']}"):
                        delete_policy_document(doc["id"])
                        notify(f"Deleted '{doc['file_name']}'", "success")
                        st.rerun()

                st.divider()
                if st.button("🚨 Clear All Policies", key="clear_all_policies_btn"):
                    delete_all_policy_documents()
                    notify("All policy documents removed.", "success")
                    st.rerun()
            else:
                st.info("No policy documents uploaded yet.")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load document list: {exc}")

    with col2:
        st.markdown(
            """
            <div class="section-card">
                <div class="section-card-title"><span class="emoji-icon">💳</span> Transaction Data (CSV)</div>
                <div style="color:#64748B; font-size:0.9rem;">
                    Expected columns: customer_id, full_name, country, transaction_id,
                    amount, currency, sender_country, receiver_country, timestamp, transaction_type
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        csv_file = st.file_uploader(
            "Drop a transactions CSV here",
            type=["csv"],
            key="csv_uploader",
        )
        if csv_file is not None:
            preview_df = pd.read_csv(csv_file)
            st.markdown("**Preview:**")
            st.dataframe(preview_df.head(20), use_container_width=True, hide_index=True)
            csv_file.seek(0)

            if st.button("Ingest CSV", key="ingest_csv_btn"):
                with st.spinner("Parsing and uploading transactions..."):
                    try:
                        result = ingest_transactions_csv(csv_file.read())
                        notify(
                            f"Upserted {result.num_customers_upserted} customers, "
                            f"inserted {result.num_transactions_inserted} transactions.",
                            "success",
                        )
                        st.success(
                            f"✅ Upserted {result.num_customers_upserted} customers, "
                            f"inserted {result.num_transactions_inserted} transactions "
                            f"({result.num_rows_skipped} rows skipped)."
                        )
                        if result.errors:
                            with st.expander(f"⚠️ {len(result.errors)} warning(s)/error(s)"):
                                for e in result.errors[:50]:
                                    st.text(e)
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        notify(f"CSV ingestion failed: {exc}", "error")
                        st.error(f"❌ CSV ingestion failed: {exc}")

        st.markdown("**Existing customer data:**")
        try:
            summary_df = get_customer_summary_table()
            if not summary_df.empty:
                st.markdown(
                    f'<span class="status-pill high" style="background:rgba(102,126,234,.12);'
                    f'color:#4338ca;border-color:rgba(102,126,234,.4);">📂 '
                    f'{len(summary_df)} customers stored</span>',
                    unsafe_allow_html=True,
                )
                if st.button("🚨 Clear All Customer Data", key="clear_all_cust_btn"):
                    delete_all_customers_and_transactions()
                    notify("All customers and transaction history removed.", "success")
                    st.rerun()
            else:
                st.info("No customer data stored yet.")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load customer count: {exc}")

# =======================================================================
# TAB 2 — Risk Scoring Dashboard
# =======================================================================
with tab_dashboard:
    section_header("📊 Customer Risk Overview", icon="📊")
    st.caption("Real-time risk scoring powered by rule engine + Groq policy reasoning.")

    try:
        summary_df = get_customer_summary_table()
    except Exception as exc:  # noqa: BLE001
        summary_df = pd.DataFrame()
        st.warning(f"Could not load customer summary: {exc}")

    total = len(summary_df)
    high = int((summary_df["risk_level"] == "HIGH").sum()) if not summary_df.empty else 0
    medium = int((summary_df["risk_level"] == "MEDIUM").sum()) if not summary_df.empty else 0
    low = int((summary_df["risk_level"] == "LOW").sum()) if not summary_df.empty else 0

    metric_row([
        {"label": "Total Customers", "value": total},
        {"label": "High Risk", "value": high, "sublabel": "🔴 requires review", "color": risk_color("HIGH")},
        {"label": "Medium Risk", "value": medium, "sublabel": "🟡 monitor", "color": risk_color("MEDIUM")},
        {"label": "Low Risk", "value": low, "sublabel": "🟢 nominal", "color": risk_color("LOW")},
    ])

    st.markdown(
        stat_card(
            "🛡️ Protected",
            f"{total}",
            subtitle="customers monitored" if total == 1 else "customers monitored",
            color="linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
        ),
        unsafe_allow_html=True,
    )

    st.divider()

    st.markdown(
        '<div class="sub-section-label">'
        '<span class="sub-section-icon">🚀</span>'
        '<span class="sub-section-text">Run Risk Evaluation</span></div>',
        unsafe_allow_html=True,
    )
    st.caption("Rule engine + Groq policy reasoning across all customers")

    run_col, _ = st.columns([1, 3])
    with run_col:
        if st.button("▶️ Run AML Agent Evaluation", type="primary", use_container_width=True):
            with st.spinner("Running rule engine + Groq policy reasoning across all customers..."):
                try:
                    results = run_full_evaluation()
                    st.session_state.last_evaluation_results = results
                    notify(f"Evaluation complete — {len(results)} customers assessed.", "success")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    notify(f"Evaluation failed: {exc}", "error")
                    st.error(f"❌ Evaluation failed: {exc}")

    # -------------------------------------------------------------
    # Interactive charts
    # -------------------------------------------------------------
    if not summary_df.empty:
        section_header("📈 Analytics & Insights", icon="📈")
        st.markdown('<div class="section-card" style="padding:0.6rem 0.8rem;">', unsafe_allow_html=True)
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.markdown("**Risk Tier Distribution**")
            tier_counts = (
                summary_df["risk_level"].value_counts().reindex(["HIGH", "MEDIUM", "LOW"]).fillna(0)
            )
            donut = go.Figure(
                data=[
                    go.Pie(
                        labels=["High", "Medium", "Low"],
                        values=tier_counts.values,
                        hole=0.55,
                        marker=dict(colors=[risk_color("HIGH"), risk_color("MEDIUM"), risk_color("LOW")]),
                        textinfo="label+percent",
                        sort=False,
                    )
                ]
            )
            donut.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                showlegend=True,
                height=340,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(donut, use_container_width=True)

        with chart_col2:
            st.markdown("**Transaction Volume by Risk Level**")
            volume_by_risk = (
                summary_df.groupby("risk_level")["total_volume"]
                .sum()
                .reindex(["HIGH", "MEDIUM", "LOW"])
                .fillna(0)
            )
            bar = go.Figure(
                data=[
                    go.Bar(
                        x=["High", "Medium", "Low"],
                        y=volume_by_risk.values,
                        marker_color=[risk_color("HIGH"), risk_color("MEDIUM"), risk_color("LOW")],
                        text=[f"${v:,.0f}" for v in volume_by_risk.values],
                        textposition="outside",
                    )
                ]
            )
            bar.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                height=340,
                yaxis_title="Total transaction volume",
                xaxis_title=None,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(bar, use_container_width=True)

        st.markdown('</div>', unsafe_allow_html=True)

    section_header("📋 Customer Risk Table", icon="📋")
    if summary_df.empty:
        st.info("No customers found yet. Upload a transactions CSV in the Data Ingestion tab first.")
    else:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        # ----------------- search + filter controls -----------------
        f_col1, f_col2 = st.columns([2, 1])
        with f_col1:
            search_term = st.text_input(
                "🔍 Search by Customer ID or Name",
                key="risk_table_search",
                placeholder="e.g. CUST-1042 or Jane Doe",
            )
        with f_col2:
            risk_filter = st.multiselect(
                "Filter by Risk Level",
                options=["HIGH", "MEDIUM", "LOW"],
                default=["HIGH", "MEDIUM", "LOW"],
                key="risk_table_filter",
            )

        filtered_df = summary_df.copy()
        if risk_filter:
            filtered_df = filtered_df[filtered_df["risk_level"].isin(risk_filter)]
        else:
            filtered_df = filtered_df.iloc[0:0]
        if search_term.strip():
            term = search_term.strip().lower()
            filtered_df = filtered_df[
                filtered_df["external_id"].str.lower().str.contains(term, na=False)
                | filtered_df["full_name"].str.lower().str.contains(term, na=False)
            ]

        def badge(level: str) -> str:
            return {"HIGH": "🔴 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "🟢 LOW"}.get(level, level)

        display_df = filtered_df.copy()
        display_df["risk_level"] = display_df["risk_level"].apply(badge)
        display_df = display_df.rename(columns={
            "external_id": "Customer ID",
            "full_name": "Name",
            "country": "Country",
            "risk_level": "Risk",
            "transaction_count": "Txn Count",
            "total_volume": "Total Volume",
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.markdown(
            f'<span class="status-pill neutral">📊 Showing {len(filtered_df)} of {len(summary_df)} customers</span>',
            unsafe_allow_html=True,
        )

        export_col, _ = st.columns([1, 3])
        with export_col:
            st.download_button(
                "⬇️ Export Risk Report (CSV)",
                data=filtered_df.to_csv(index=False).encode("utf-8"),
                file_name="aml_risk_report.csv",
                mime="text/csv",
                use_container_width=True,
            )

        sub_section("🔍 Customer Audit View")
        selected_customer = st.selectbox(
            "Select a customer to inspect",
            options=summary_df["external_id"].tolist(),
        )
        if selected_customer:
            row = summary_df[summary_df["external_id"] == selected_customer].iloc[0]

            head_col1, head_col2 = st.columns([3, 1])
            with head_col1:
                st.markdown(
                    f'<div class="audit-reasoning-box">'
                    f'<div style="display:flex;align-items:gap:0.8rem;justify-content:space-between;">'
                    f'<div>'
                    f'<div style="font-size:1.3rem;font-weight:700;color:#0f172a;">'
                    f'{row["full_name"]}</div>'
                    f'<div style="color:#64748b;font-size:0.88rem;">'
                    f'ID: <b>{selected_customer}</b>  ·  🌍 {row["country"]}  ·  '
                    f'📊 {row["transaction_count"]} txns  ·  💰 {row["total_volume"]:,.2f}</div>'
                    f'</div></div></div>',
                    unsafe_allow_html=True,
                )
            with head_col2:
                if st.button("🗑️ Delete Customer", key=f"del_cust_{selected_customer}"):
                    delete_customer_by_external_id(selected_customer)
                    notify(f"Deleted customer '{selected_customer}'", "success")
                    st.rerun()

            try:
                from database.supabase_client import get_supabase_client

                client = get_supabase_client()
                customer_resp = (
                    client.table("customers")
                    .select("id")
                    .eq("external_id", selected_customer)
                    .limit(1)
                    .execute()
                )
                customer_id = customer_resp.data[0]["id"] if customer_resp.data else None
                assessment, customer_txns = (
                    get_customer_audit_details(customer_id)
                    if customer_id
                    else (None, pd.DataFrame())
                )

                risk_level = (assessment or {}).get("risk_level", row["risk_level"])
                st.markdown(f"### Risk Status: {risk_badge_html(risk_level)}", unsafe_allow_html=True)

                sub_section("Triggered Flags", icon="🚩")
                flags = (assessment or {}).get("flags") or []
                if flags:
                    for flag in flags:
                        if isinstance(flag, dict):
                            st.warning(f"**{flag.get('rule', 'Flag')}**: {flag.get('detail', '')}")
                        else:
                            st.warning(str(flag))
                else:
                    st.success("No red or yellow flags were triggered.")

                sub_section("AI Audit Justification", icon="🧠")
                reasoning = (assessment or {}).get("reasoning")
                if reasoning:
                    box_bg = {"HIGH": "#FEF2F2", "MEDIUM": "#FFFBEB", "LOW": "#F0FDFA"}.get(risk_level, "#F1F5F9")
                    box_border = {"HIGH": "#FCA5A5", "MEDIUM": "#FDE68A", "LOW": "#99F6E4"}.get(risk_level, "#E2E8F0")
                    st.markdown(
                        f'<div class="audit-reasoning-box" '
                        f'style="background:{box_bg}; border:1px solid {box_border};">'
                        f'{clean_llm_markdown(reasoning)}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("No saved assessment is available for this customer yet.")

                sub_section("Transaction History", icon="📄")
                if customer_txns.empty:
                    st.info("No transactions found for this customer.")
                else:
                    st.dataframe(customer_txns, use_container_width=True, hide_index=True)
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Could not load audit details: {exc}")
        st.markdown('</div>', unsafe_allow_html=True)

# =======================================================================
# TAB 3 — Policy Chatbot
# =======================================================================
with tab_chat:
    section_header("💬 Policy Chatbot", icon="💬")
    st.caption("Ask questions about your uploaded AML policy documents. Answers are grounded in retrieved policy excerpts.")

    def _render_sources(sources) -> None:
        with st.expander("📚 View Cited Policy Sources"):
            for i, s in enumerate(sources, start=1):
                doc_label = s.document_name or "Unknown document"
                if getattr(s, "page_number", None):
                    doc_label += f" — page {s.page_number}"
                st.markdown(f"**Source {i}: {doc_label}**  ·  confidence {s.similarity:.2f}")
                st.text(s.content[:800])
                if i < len(sources):
                    st.divider()

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            render_llm_markdown(st, msg["content"])
            if msg.get("sources"):
                _render_sources(msg["sources"])

    st.markdown("**Quick prompts — tap one to get started:**")
    st.markdown('<div class="section-card" style="padding:0.4rem 0.8rem;">', unsafe_allow_html=True)
    chip_col1, chip_col2, chip_col3 = st.columns(3)
    quick_prompts = [
        "What is Customer Due Diligence?",
        "What are the PEP screening requirements?",
        "What are the transaction reporting thresholds?",
    ]
    for col, prompt_text in zip([chip_col1, chip_col2, chip_col3], quick_prompts):
        with col:
            if st.button(prompt_text, key=f"chip_{prompt_text}", use_container_width=True):
                st.session_state.queued_prompt = prompt_text
                st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    user_question = st.chat_input("Ask about AML policy, thresholds, reporting obligations...")
    if not user_question and st.session_state.queued_prompt:
        user_question = st.session_state.queued_prompt
        st.session_state.queued_prompt = None

    if user_question:
        st.session_state.chat_messages.append({"role": "user", "content": user_question, "sources": None})
        with st.chat_message("user"):
            st.write(user_question)

        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.chat_messages[:-1]
        ]

        with st.chat_message("assistant"):
            with st.spinner("Searching policy documents and generating answer..."):
                try:
                    response = answer_question(user_question, chat_history=history)
                    render_llm_markdown(st, response.answer)
                    if response.sources:
                        _render_sources(response.sources)
                    st.session_state.chat_messages.append({
                        "role": "assistant",
                        "content": response.answer,
                        "sources": response.sources,
                    })
                except Exception as exc:  # noqa: BLE001
                    error_msg = f"❌ Error generating answer: {exc}"
                    notify("Error generating answer.", "error")
                    st.error(error_msg)
                    st.session_state.chat_messages.append({
                        "role": "assistant", "content": error_msg, "sources": None
                    })

# =======================================================================
# TAB 4 — AI Investigation Agent
# =======================================================================
with tab_agent:
    section_header("🤖 AI Investigation Agent", icon="🤖")
    st.caption(
        "A tool-using agent: it decides for itself whether to pull transaction history, "
        "search policy documents, or propose a risk update — you approve any risk change "
        "before it touches the database."
    )

    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(
            """<div class="section-card" style="padding:0.8rem 1rem;">
               <div class="section-card-title" style="margin-bottom:0.4rem;"><span class="emoji-icon">🆔</span> Customer Identifier</div>
            </div>""",
            unsafe_allow_html=True,
        )
        agent_customer_id = st.text_input(
            "Customer ID",
            key="agent_customer_id",
            placeholder="CUST-101",
            label_visibility="collapsed",
        )
    with col2:
        st.markdown(
            """<div class="section-card" style="padding:0.8rem 1rem;">
               <div class="section-card-title" style="margin-bottom:0.4rem;"><span class="emoji-icon">📝</span> Investigation Request</div>
            </div>""",
            unsafe_allow_html=True,
        )
        agent_request = st.text_area(
            "Investigation Request",
            key="agent_request",
            value="Investigate this customer and determine whether the activity is suspicious.",
            height=80,
            label_visibility="collapsed",
        )

    if st.button("▶️ Start Investigation", type="primary", key="start_investigation_btn"):
        if not agent_customer_id.strip():
            st.warning("Enter a customer ID first.")
        else:
            final_result = None
            tool_events = []
            with st.status("🤖 Agent investigation in progress...", expanded=True) as status:
                try:
                    for event in run_investigation(agent_customer_id.strip(), agent_request.strip()):
                        if isinstance(event, InvestigationResult):
                            final_result = event
                        else:
                            st.write(event.label)
                            if event.detail:
                                st.caption(event.detail[:300])
                            if event.tool_result is not None:
                                tool_events.append(event)
                except Exception as exc:  # noqa: BLE001
                    status.update(label="❌ Investigation failed", state="error")
                    st.error(f"Investigation failed: {exc}")
                    final_result = None

            for ev in tool_events:
                with st.expander(f"Raw result — {ev.tool_name}", expanded=False):
                    st.json(ev.tool_result)

            if final_result is not None:
                status.update(
                    label=f"📄 Investigation complete — {final_result.risk_level}",
                    state="error" if final_result.error else "complete",
                )
                st.session_state.last_investigation = final_result
                log_investigation(final_result)

    inv = st.session_state.last_investigation
    if inv:
        st.divider()
        summary_df = get_customer_summary_table()
        current_risk = "UNKNOWN"
        if not summary_df.empty:
            customer_match = summary_df[summary_df["external_id"].astype(str).str.upper() == str(inv.customer_id).upper()]
            if not customer_match.empty:
                current_risk = str(customer_match.iloc[0].get("risk_level", "UNKNOWN")).upper()

        head_col1, head_col2 = st.columns([3, 1])
        with head_col1:
            st.markdown(
                f'<div class="audit-reasoning-box">'
                f'<div style="display:flex;align-items:center;gap:0.6rem;">'
                f'<span style="font-size:1.6rem;">🤖</span>'
                f'<div><div style="font-size:1.2rem;font-weight:700;color:#0f172a;">'
                f'Investigation: <code style="background:rgba(0,0,0,.06);'
                f'padding:0.1rem 0.4rem;border-radius:4px;">{inv.customer_id}</code></div>'
                f'<div style="color:#64748b;font-size:0.85rem;">{inv.user_request}</div></div></div></div>',
                unsafe_allow_html=True,
            )
        with head_col2:
            st.markdown(f"<div style='display:flex;flex-direction:column;gap:0.3rem;align-items:flex-end;'>"
                        f"{risk_badge_html(current_risk if current_risk in {'LOW','MEDIUM','HIGH'} else inv.risk_level)}"
                        f"</div>", unsafe_allow_html=True)
            if inv.risk_update_recommendation and inv.risk_update_recommendation.risk_level.upper() != current_risk:
                st.caption(f"Recommended update: {risk_badge_html(inv.risk_update_recommendation.risk_level)}", unsafe_allow_html=True)

        if inv.insufficient_information:
            st.warning("⚠️ The agent flagged this investigation as having insufficient information.")
        if inv.truncated:
            st.warning("⚠️ The investigation was truncated (too many tool-call rounds without a conclusion).")
        if inv.error:
            st.error(f"Agent error: {inv.error}")

        detail_col1, detail_col2 = st.columns(2, gap="large")
        with detail_col1:
            st.markdown('<div class="investigation-column">', unsafe_allow_html=True)
            sub_section("🚩 Suspicious Patterns")
            if inv.suspicious_patterns:
                for p in inv.suspicious_patterns:
                    st.markdown(f"- {p}")
            else:
                st.caption("None identified.")

            sub_section("📎 Evidence")
            if inv.evidence:
                for e in inv.evidence:
                    st.markdown(f"- {e}")
            else:
                st.caption("No specific evidence recorded.")
            st.markdown('</div>', unsafe_allow_html=True)

        with detail_col2:
            st.markdown('<div class="investigation-column">', unsafe_allow_html=True)
            sub_section("📚 Policy References")
            if inv.policy_references:
                for r in inv.policy_references:
                    st.markdown(f"- {r}")
            else:
                st.caption("No policy documents were cited.")

            sub_section("✅ Recommended Action")
            st.markdown(inv.recommended_action or "_None provided._")
            st.markdown('</div>', unsafe_allow_html=True)

        sub_section("🧠 Agent Analysis")
        render_llm_markdown(st, inv.analysis or "_No analysis provided._")

        if inv.risk_update_recommendation:
            rec = inv.risk_update_recommendation
            sub_section("🔔 Recommended Risk Update — Requires Human Approval")
            box_bg = {"HIGH": "#FEF2F2", "MEDIUM": "#FFFBEB", "LOW": "#F0FDFA"}.get(rec.risk_level, "#F1F5F9")
            box_border = {"HIGH": "#FCA5A5", "MEDIUM": "#FDE68A", "LOW": "#99F6E4"}.get(rec.risk_level, "#E2E8F0")
            st.markdown(
                f'<div class="audit-reasoning-box" '
                f'style="background:{box_bg}; border:1px solid {box_border};">'
                f'<b>Recommended Risk Level:</b> {rec.risk_level}<br>'
                f'<b>Reason:</b> {rec.reason}</div>',
                unsafe_allow_html=True,
            )
            if rec.approved:
                st.success("✅ This risk update has been approved and applied.")
            else:
                if st.button("✅ Approve Risk Update", key=f"approve_{inv.investigation_id}"):
                    exec_result = call_tool(
                        "update_customer_risk_score",
                        customer_id=rec.customer_id,
                        risk_level=rec.risk_level,
                        reason=rec.reason,
                    )
                    if exec_result.get("success"):
                        rec.approved = True
                        mark_risk_update_approved(inv.investigation_id)
                        notify(f"Risk update applied for {rec.customer_id}.", "success")
                        st.rerun()
                    else:
                        st.error(f"Failed to apply update: {exec_result.get('error', 'unknown error')}")

        with st.expander("🔎 View full agent trace"):
            for step in inv.steps:
                st.markdown(f"**{step.label}**")
                if step.detail:
                    st.caption(step.detail[:500])
                if step.tool_result is not None:
                    st.json(step.tool_result)
                st.markdown("---")

    st.markdown("---")
    section_header("🗂️ Recent Investigations (Audit Trail)", icon="🗂️")
    with st.expander("🔍 View full audit trail", expanded=False):
        try:
            recents = list_recent_investigations()
            if recents:
                st.dataframe(pd.DataFrame(recents), use_container_width=True, hide_index=True)
            else:
                st.caption("No investigations logged yet.")
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Could not load audit trail: {exc}")
