import streamlit as st
import pandas as pd
import os
import plotly.express as px
from core.gstr2b_parser import parse_gstr2b
from core.tally_parser import parse_tally_excel
from core.matching_engine import run_reconciliation
from core.itc_calculator import compute_itc_summary
from core.ai_insights import generate_ca_insights
from core.gst_portal import GSTPortalAutomation
from reports.pdf_generator import generate_pdf_report


st.set_page_config(
    page_title="AuditPilot — AI GST Engine",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    footer {visibility: hidden;}
    .stDeployButton {display: none !important;}
    a[href*="github.com"] {display: none !important;}
    button[title*="Star"], a[aria-label*="Star"], button[aria-label*="Star"] {
        display: none !important;
    }
    header[data-testid="stHeader"] {
        background: rgba(14, 17, 23, 0.75);
        backdrop-filter: blur(8px);
    }
    div[data-testid="stMetric"] {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-radius: 10px;
        padding: 14px;
    }
</style>
""",
    unsafe_allow_html=True,
)


def show_gst_failure_debug(result: dict):
    st.error(result.get("error", "Failed to connect to GST Portal."))

    page_url = result.get("page_url") or ""
    page_title = result.get("page_title") or ""
    tech = result.get("technical_error") or ""
    html_snippet = result.get("html_snippet") or ""
    shot_b64 = result.get("debug_screenshot_b64") or ""

    if page_url or page_title:
        st.caption(f"**Page URL:** `{page_url}`")
        st.caption(f"**Page title:** `{page_title}`")

    if shot_b64:
        st.warning("Debug screenshot of what the server actually loaded:")
        st.image(
            f"data:image/png;base64,{shot_b64}",
            caption="GST portal page as seen by Render (headless Chrome)",
            use_container_width=True,
        )
    else:
        st.info("No debug screenshot was captured (browser may have crashed before paint).")

    with st.expander("Technical details", expanded=True):
        if tech:
            st.code(tech)
        if html_snippet:
            st.markdown("**HTML snippet (first 4000 chars):**")
            st.code(html_snippet[:4000])


with st.sidebar:
    st.title("🏛️ AuditPilot V1.5")
    st.caption("AI-Powered GST Reconciliation Engine")
    st.divider()
    st.markdown("### 📌 Navigation & Help")
    st.markdown(
        """
    1. **Step 1:** Configure Client Details.  
    2. **Step 2:** Upload GSTR-2B (**recommended**) or try Auto-Fetch.  
    3. **Step 3:** Upload Tally Purchase Register.  
    4. **Step 4:** Click **Run Reconciliation**.
    """
    )
    st.divider()
    st.info(
        "Cloud tip: Use **Option A (Manual Upload)** for reliable demos. "
        "Option B needs GST portal captcha issuance from this server IP."
    )
    st.caption("Built for CA Firms & Tax Professionals")


st.title("🏛️ AuditPilot")
st.markdown(
    "**Automated GST Reconciliation & Input Tax Credit (ITC) Intelligence Engine**"
)
st.divider()


with st.expander("📋 Step 1: Client Details", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Client Name", value="Sharma Enterprises")
        financial_year = st.selectbox(
            "Financial Year", ["2024-25", "2023-24", "2025-26"]
        )
    with col2:
        client_gstin = st.text_input(
            "Client GSTIN", value="27AABCS1234F1Z5", max_chars=15
        )
        return_period = st.selectbox(
            "Return Period",
            ["June 2024", "May 2024", "April 2024", "March 2024"],
        )


st.header("📁 Step 2: Source Data Selection")

tab_manual, tab_auto = st.tabs(
    ["📄 Option A: Manual File Upload", "🌐 Option B: Auto-Fetch from GST Portal"]
)

gstr2b_file_obj = None
tally_file = None

with tab_manual:
    st.success("Recommended for live demos and production use.")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📄 GSTR-2B JSON** *(from GST Portal)*")
        gstr2b_file = st.file_uploader(
            "Upload GSTR-2B JSON", type=["json"], key="gstr2b_manual"
        )
        if gstr2b_file:
            gstr2b_file_obj = gstr2b_file
    with col2:
        st.markdown("**📊 Tally Purchase Register** *(Excel Export)*")
        tally_file_manual = st.file_uploader(
            "Upload Tally Excel", type=["xlsx", "xls"], key="tally_manual"
        )
        if tally_file_manual:
            tally_file = tally_file_manual

with tab_auto:
    st.warning(
        "Experimental on cloud. If captcha does not appear on the GST page "
        "(username/password only), the portal is not issuing captcha to this server. "
        "Use Option A on Render, or run Option B locally."
    )
    st.markdown("### 🔒 Fetch GSTR-2B Directly from GST Portal")

    col_cred1, col_cred2 = st.columns(2)
    with col_cred1:
        gst_user = st.text_input(
            "GST Portal Username", placeholder="e.g. sharma_tax"
        )
    with col_cred2:
        gst_pass = st.text_input("GST Portal Password", type="password")

    load_captcha = st.button("🖼️ Step 1: Load GST Portal CAPTCHA")

    if load_captcha:
        if not gst_user or not gst_pass:
            st.error("Please enter Username and Password first.")
        else:
            st.session_state.pop("gst_session", None)
            st.session_state.pop("gst_last_failure", None)

            with st.spinner(
                "Connecting to GST Portal (30–90 sec on free tier). Please wait..."
            ):
                try:
                    automation = GSTPortalAutomation()
                    # Pass username so portal can lazy-load captcha after typing it
                    session_data = automation.fetch_login_captcha(username=gst_user)
                    if session_data.get("success"):
                        st.session_state["gst_session"] = session_data
                        st.success("Connected to GST Portal! Solve CAPTCHA below:")
                        if session_data.get("captcha_strategy"):
                            st.caption(
                                f"CAPTCHA detection strategy: `{session_data['captcha_strategy']}`"
                            )
                    else:
                        st.session_state["gst_last_failure"] = session_data
                except Exception as e:
                    st.session_state["gst_last_failure"] = {
                        "error": (
                            "GST Auto-Fetch crashed on this server. "
                            "Please use Option A: Manual File Upload."
                        ),
                        "technical_error": str(e),
                    }

    if st.session_state.get("gst_last_failure") and not st.session_state.get(
        "gst_session"
    ):
        show_gst_failure_debug(st.session_state["gst_last_failure"])

    if st.session_state.get("gst_session", {}).get("success"):
        session_data = st.session_state["gst_session"]
        if session_data.get("captcha_b64"):
            st.image(
                f"data:image/png;base64,{session_data['captcha_b64']}",
                caption="GST Portal CAPTCHA",
            )

        captcha_input = st.text_input(
            "Enter CAPTCHA shown above:",
            max_chars=8,
            key="gst_captcha_input",
        )

        if st.button("🚀 Step 2: Login & Fetch GSTR-2B Data"):
            if not captcha_input:
                st.error("Please enter the CAPTCHA text.")
            else:
                with st.spinner("Logging in and downloading GSTR-2B JSON..."):
                    try:
                        automation = GSTPortalAutomation()
                        download_res = automation.login_and_download_gstr2b(
                            session_data,
                            gst_user,
                            gst_pass,
                            captcha_input,
                            financial_year,
                            return_period,
                        )
                        if download_res.get("success"):
                            st.success(
                                "✅ GSTR-2B JSON successfully downloaded from GST Portal!"
                            )
                            st.session_state["fetched_gstr2b_path"] = download_res[
                                "file_path"
                            ]
                            st.session_state.pop("gst_session", None)
                            st.session_state.pop("gst_last_failure", None)
                        else:
                            st.error(download_res.get("error", "Download failed."))
                            st.session_state.pop("gst_session", None)
                    except Exception as e:
                        st.error(
                            "Auto-fetch failed. Please use Option A: Manual Upload."
                        )
                        with st.expander("Technical details"):
                            st.code(str(e))
                        st.session_state.pop("gst_session", None)

    if "fetched_gstr2b_path" in st.session_state:
        st.info(f"Using fetched file: `{st.session_state['fetched_gstr2b_path']}`")
        gstr2b_file_obj = st.session_state["fetched_gstr2b_path"]

    st.markdown("**📊 Upload Tally Purchase Register**")
    tally_file_auto = st.file_uploader(
        "Upload Tally Excel (Required)", type=["xlsx", "xls"], key="tally_auto"
    )
    if tally_file_auto:
        tally_file = tally_file_auto


st.divider()
if st.button(
    "🚀 RUN AUTOMATED RECONCILIATION", type="primary", use_container_width=True
):
    if not gstr2b_file_obj or not tally_file:
        st.error(
            "⚠️ Please provide BOTH GSTR-2B (via upload or auto-fetch) and Tally Excel file."
        )
    else:
        with st.spinner("⏳ Processing reconciliation & running AI analysis..."):
            try:
                df_2b = parse_gstr2b(gstr2b_file_obj)
                tally_file.seek(0)
                df_tally = parse_tally_excel(tally_file)

                rec_results = run_reconciliation(df_2b, df_tally)
                results_df = rec_results["results_df"]
                itc_summary = compute_itc_summary(results_df)
                ai_insights = generate_ca_insights(
                    client_name, rec_results, itc_summary
                )

                st.session_state["results_df"] = results_df
                st.session_state["rec_results"] = rec_results
                st.session_state["itc_summary"] = itc_summary
                st.session_state["ai_insights"] = ai_insights
                st.session_state["client_name"] = client_name
                st.session_state["client_gstin"] = client_gstin
                st.session_state["financial_year"] = financial_year
                st.session_state["return_period"] = return_period

                st.success("✅ Reconciliation completed successfully!")
            except Exception as e:
                st.error(f"❌ Execution Error: {str(e)}")


if "results_df" in st.session_state:
    results_df = st.session_state["results_df"]
    rec = st.session_state["rec_results"]
    itc = st.session_state["itc_summary"]
    ai_insights = st.session_state["ai_insights"]

    st.divider()
    st.header(f"📊 Executive Dashboard — {st.session_state['client_name']}")
    st.write(
        f"**GSTIN:** `{st.session_state['client_gstin']}` | "
        f"**Period:** {st.session_state['return_period']} "
        f"(FY {st.session_state['financial_year']})"
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🟢 Exact Match", rec["exact_count"])
    m2.metric("🟡 Fuzzy Match", rec["fuzzy_count"])
    m3.metric("🟠 Partial Match", rec["partial_count"])
    m4.metric("🔴 Missing in 2B", rec["missing_in_2b_count"])
    m5.metric("🟠 Missing in Books", rec["missing_in_books_count"])

    st.markdown("")
    st.subheader("💰 Input Tax Credit (ITC) Summary")
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Eligible Claimable ITC", f"₹{itc['itc_eligible']:,.2f}")
    i2.metric(
        "ITC At Risk (Blocked) ⚠️",
        f"₹{itc['itc_at_risk']:,.2f}",
        delta=f"-₹{itc['itc_at_risk']:,.2f}",
        delta_color="inverse",
    )
    i3.metric("Unclaimed in Books", f"₹{itc['itc_unclaimed']:,.2f}")
    i4.metric("Reconciliation Match Rate", f"{itc['match_rate_pct']}%")

    st.divider()
    st.subheader("📈 Visual Analytics")
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        fig_donut = px.pie(
            values=[itc["itc_eligible"], itc["itc_at_risk"], itc["itc_unclaimed"]],
            names=["Eligible ITC", "ITC At Risk (Blocked)", "Unclaimed ITC"],
            hole=0.5,
            title="ITC Breakdown Structure",
            color_discrete_sequence=["#00D4AA", "#FF4D4D", "#FF8C42"],
        )
        fig_donut.update_layout(
            margin=dict(t=40, b=0, l=0, r=0),
            height=300,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#E6EDF3"),
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    with chart_col2:
        status_counts = pd.DataFrame(
            {
                "Status": [
                    "Exact Match",
                    "Fuzzy Match",
                    "Missing in 2B",
                    "Missing in Books",
                ],
                "Count": [
                    rec["exact_count"],
                    rec["fuzzy_count"],
                    rec["missing_in_2b_count"],
                    rec["missing_in_books_count"],
                ],
            }
        )
        fig_bar = px.bar(
            status_counts,
            x="Status",
            y="Count",
            title="Invoice Reconciliation Distribution",
            color="Status",
            color_discrete_sequence=["#00D4AA", "#F5A623", "#FF4D4D", "#FF8C42"],
        )
        fig_bar.update_layout(
            margin=dict(t=40, b=0, l=0, r=0),
            height=300,
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#E6EDF3"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()
    st.subheader("🤖 CA Advisory Notes & Action Plan")
    st.info(ai_insights)

    st.divider()
    st.subheader("⚠️ Top Suppliers Causing Blocked ITC")
    blocked_df = results_df[results_df["status"] == "MISSING_IN_2B"]
    if not blocked_df.empty:
        supplier_summary = (
            blocked_df.groupby(["supplier_gstin", "supplier_name"])
            .agg(
                Unfiled_Invoices=("tally_inv_num", "count"),
                Total_Blocked_ITC=("tally_tax", "sum"),
                Total_Invoice_Value=("tally_total", "sum"),
            )
            .reset_index()
            .sort_values(by="Total_Blocked_ITC", ascending=False)
        )
        supplier_summary.columns = [
            "Supplier GSTIN",
            "Supplier Name",
            "Unfiled Invoices",
            "Blocked ITC (₹)",
            "Total Value (₹)",
        ]
        st.dataframe(supplier_summary, use_container_width=True, hide_index=True)
    else:
        st.success("🎉 Zero suppliers have unfiled returns causing blocked ITC.")

    st.divider()
    st.subheader("📑 Full Invoice Comparison Table")
    col_search, col_filter = st.columns([2, 1])
    with col_search:
        search_term = st.text_input(
            "🔍 Search Supplier Name, GSTIN, or Invoice #", ""
        )
    with col_filter:
        status_filter = st.selectbox(
            "Filter by Status:",
            [
                "All Invoices",
                "EXACT_MATCH",
                "FUZZY_MATCH",
                "PARTIAL_MATCH",
                "MISSING_IN_2B",
                "MISSING_IN_BOOKS",
            ],
        )

    filtered_df = results_df.copy()
    if status_filter != "All Invoices":
        filtered_df = filtered_df[filtered_df["status"] == status_filter]

    if search_term:
        term = search_term.lower()
        filtered_df = filtered_df[
            filtered_df["supplier_name"]
            .astype(str)
            .str.lower()
            .str.contains(term, na=False)
            | filtered_df["supplier_gstin"]
            .astype(str)
            .str.lower()
            .str.contains(term, na=False)
            | filtered_df["tally_inv_num"]
            .astype(str)
            .str.lower()
            .str.contains(term, na=False)
            | filtered_df["g2b_inv_num"]
            .astype(str)
            .str.lower()
            .str.contains(term, na=False)
        ]

    st.dataframe(filtered_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📥 Export Audit Reports")
    col1, col2, col3 = st.columns(3)

    with col1:
        csv_bytes = results_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📊 Download CSV Data",
            data=csv_bytes,
            file_name=f"reconciliation_{st.session_state['client_name']}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col2:
        excel_path = "output/reconciliation_report.xlsx"
        os.makedirs("output", exist_ok=True)
        results_df.to_excel(excel_path, index=False)
        with open(excel_path, "rb") as f:
            st.download_button(
                "📗 Download Excel Audit Sheet",
                data=f.read(),
                file_name=f"reconciliation_{st.session_state['client_name']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    with col3:
        pdf_path = "output/reconciliation_report.pdf"
        os.makedirs("output", exist_ok=True)
        generate_pdf_report(
            pdf_path,
            st.session_state["client_name"],
            st.session_state["client_gstin"],
            st.session_state["financial_year"],
            st.session_state["return_period"],
            rec,
            itc,
            ai_insights,
        )
        with open(pdf_path, "rb") as f:
            st.download_button(
                "📕 Download PDF Client Report",
                data=f.read(),
                file_name=f"reconciliation_report_{st.session_state['client_name']}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )