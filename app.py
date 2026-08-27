import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from core.gstr2b_parser import parse_gstr2b
from core.tally_parser import parse_tally_excel
from core.matching_engine import run_reconciliation
from core.itc_calculator import compute_itc_summary
from core.ai_insights import generate_ca_insights
from reports.pdf_generator import generate_pdf_report


# ─── PAGE CONFIG ───────────────────────────────────────────────
st.set_page_config(
    page_title="AuditPilot — AI GST Reconciliation Engine",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── CUSTOM CSS ────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(90deg, #00d4aa, #0072ff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0px;
    }
    .sub-header {
        color: #888;
        font-size: 1rem;
        margin-bottom: 25px;
    }
    .stMetric {
        background-color: #1a1c24;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #2d313e;
    }
</style>
""", unsafe_allow_html=True)


# ─── SIDEBAR ───────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/scales.png", width=60)
    st.title("AuditPilot V1.0")
    st.caption("AI-Powered GST Reconciliation")
    st.markdown("---")
    st.markdown("### 📌 Quick Instructions")
    st.markdown("""
    1. Enter **Client Details**.
    2. Upload **GSTR-2B JSON** from GST Portal.
    3. Upload **Tally Purchase Register** Excel.
    4. Click **Reconcile Now**.
    5. Download **PDF/Excel Reports**.
    """)
    st.markdown("---")
    st.caption("Built for CA Firms & Tax Professionals")


# ─── MAIN HEADER ───────────────────────────────────────────────
st.markdown('<div class="main-header">🏛️ AuditPilot</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Automated GST Reconciliation & Input Tax Credit (ITC) Intelligence Engine</div>', unsafe_allow_html=True)


# ─── STEP 1: CLIENT DETAILS ───────────────────────────────────
with st.expander("📋 Step 1: Client Details", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Client Name", value="Sharma Enterprises")
        financial_year = st.selectbox("Financial Year", ["2024-25", "2023-24", "2025-26"])
    with col2:
        client_gstin = st.text_input("Client GSTIN", value="27AABCS1234F1Z5", max_chars=15)
        return_period = st.selectbox("Return Period", ["June 2024", "May 2024", "April 2024", "March 2024"])


# ─── STEP 2: FILE UPLOAD ──────────────────────────────────────
with st.expander("📁 Step 2: Upload Source Files", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📄 GSTR-2B JSON** *(from GST Portal)*")
        gstr2b_file = st.file_uploader("Upload GSTR-2B JSON", type=["json"], key="gstr2b")
    with col2:
        st.markdown("**📊 Tally Purchase Register** *(Excel Export)*")
        tally_file = st.file_uploader("Upload Tally Excel", type=["xlsx", "xls"], key="tally")


# ─── STEP 3: RECONCILE BUTTON ─────────────────────────────────
st.markdown("")
if st.button("🚀 RUN AUTOMATED RECONCILIATION", type="primary", use_container_width=True):
    
    if not gstr2b_file or not tally_file:
        st.error("⚠️ Please upload BOTH GSTR-2B JSON and Tally Excel files to proceed.")
    else:
        with st.spinner("⏳ Parsing files, matching invoices, and running ITC intelligence..."):
            try:
                df_2b = parse_gstr2b(gstr2b_file)
                tally_file.seek(0)
                df_tally = parse_tally_excel(tally_file)
                
                rec_results = run_reconciliation(df_2b, df_tally)
                results_df = rec_results["results_df"]
                itc_summary = compute_itc_summary(results_df)
                ai_insights = generate_ca_insights(client_name, rec_results, itc_summary)
                
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
                st.error(f"❌ Error during execution: {str(e)}")


# ─── STEP 4: DASHBOARD & ANALYTICS ────────────────────────────
if "results_df" in st.session_state:
    results_df = st.session_state["results_df"]
    rec = st.session_state["rec_results"]
    itc = st.session_state["itc_summary"]
    ai_insights = st.session_state["ai_insights"]
    
    st.markdown("---")
    st.header(f"📊 Audit Executive Dashboard — {st.session_state['client_name']}")
    st.write(f"**GSTIN:** `{st.session_state['client_gstin']}` | **Period:** {st.session_state['return_period']} (FY {st.session_state['financial_year']})")
    
    # Summary Metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🟢 Exact Match", rec["exact_count"])
    m2.metric("🟡 Fuzzy Match", rec["fuzzy_count"])
    m3.metric("🟠 Partial Match", rec["partial_count"])
    m4.metric("🔴 Missing in 2B", rec["missing_in_2b_count"])
    m5.metric("🟠 Missing in Books", rec["missing_in_books_count"])
    
    st.markdown("")
    
    # Financial ITC Cards
    st.subheader("💰 Input Tax Credit (ITC) Summary")
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Eligible Claimable ITC", f"₹{itc['itc_eligible']:,.2f}")
    i2.metric("ITC At Risk (Blocked) ⚠️", f"₹{itc['itc_at_risk']:,.2f}", delta=f"-₹{itc['itc_at_risk']:,.2f}", delta_color="inverse")
    i3.metric("Unclaimed in Books", f"₹{itc['itc_unclaimed']:,.2f}")
    i4.metric("Reconciliation Match Rate", f"{itc['match_rate_pct']}%")
    
    st.markdown("---")
    
    # ─── CHARTS & VISUAL ANALYTICS ────────────────────────────
    st.subheader("📈 Visual Analytics")
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        # Chart 1: Donut Chart for ITC Distribution
        itc_labels = ['Eligible ITC', 'ITC At Risk (Blocked)', 'Unclaimed ITC']
        itc_values = [itc['itc_eligible'], itc['itc_at_risk'], itc['itc_unclaimed']]
        
        fig_donut = px.pie(
            values=itc_values,
            names=itc_labels,
            hole=0.5,
            title="ITC Breakdown Structure",
            color_discrete_sequence=['#00d4aa', '#ff4d4d', '#ff8c42']
        )
        fig_donut.update_layout(margin=dict(t=40, b=0, l=0, r=0), height=300)
        st.plotly_chart(fig_donut, use_container_width=True)
        
    with chart_col2:
        # Chart 2: Bar Chart for Invoice Counts
        status_counts = pd.DataFrame({
            "Status": ["Exact Match", "Fuzzy Match", "Missing in 2B", "Missing in Books"],
            "Count": [rec["exact_count"], rec["fuzzy_count"], rec["missing_in_2b_count"], rec["missing_in_books_count"]]
        })
        fig_bar = px.bar(
            status_counts,
            x="Status",
            y="Count",
            title="Invoice Reconciliation Distribution",
            color="Status",
            color_discrete_sequence=['#00d4aa', '#f5a623', '#ff4d4d', '#ff8c42']
        )
        fig_bar.update_layout(margin=dict(t=40, b=0, l=0, r=0), height=300, showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)
        
    st.markdown("---")

    # 🤖 AI Advisory Box
    st.subheader("🤖 CA Advisory Notes & Action Plan")
    st.info(ai_insights)

    st.markdown("---")

    # ─── SUPPLIER RISK ANALYSIS TABLE ─────────────────────────
    st.subheader("⚠️ Top Suppliers Causing Blocked ITC")
    st.caption("Send this list to suppliers who haven't filed their GSTR-1 returns.")
    
    blocked_df = results_df[results_df["status"] == "MISSING_IN_2B"]
    if not blocked_df.empty:
        supplier_summary = (
            blocked_df.groupby(["supplier_gstin", "supplier_name"])
            .agg(
                Unfiled_Invoices=("tally_inv_num", "count"),
                Total_Blocked_ITC=("tally_tax", "sum"),
                Total_Invoice_Value=("tally_total", "sum")
            )
            .reset_index()
            .sort_values(by="Total_Blocked_ITC", ascending=False)
        )
        supplier_summary.columns = ["Supplier GSTIN", "Supplier Name", "Unfiled Invoices", "Blocked ITC (₹)", "Total Value (₹)"]
        st.dataframe(supplier_summary, use_container_width=True, hide_index=True)
    else:
        st.success("🎉 Great news! Zero suppliers have unfiled returns causing blocked ITC.")

    st.markdown("---")

    # ─── FULL INVOICE COMPARISON TABLE ────────────────────────
    st.subheader("📑 Full Invoice Comparison Table")
    
    col_search, col_filter = st.columns([2, 1])
    with col_search:
        search_term = st.text_input("🔍 Search Supplier Name, GSTIN, or Invoice #", "")
    with col_filter:
        status_filter = st.selectbox(
            "Filter by Status:",
            ["All Invoices", "EXACT_MATCH", "FUZZY_MATCH", "PARTIAL_MATCH", "MISSING_IN_2B", "MISSING_IN_BOOKS"]
        )
    
    filtered_df = results_df.copy()
    
    if status_filter != "All Invoices":
        filtered_df = filtered_df[filtered_df["status"] == status_filter]
        
    if search_term:
        term = search_term.lower()
        filtered_df = filtered_df[
            filtered_df["supplier_name"].str.lower().str.contains(term, na=False) |
            filtered_df["supplier_gstin"].str.lower().str.contains(term, na=False) |
            filtered_df["tally_inv_num"].str.lower().str.contains(term, na=False) |
            filtered_df["g2b_inv_num"].str.lower().str.contains(term, na=False)
        ]
        
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)
    
    st.markdown("---")

    # ─── EXPORT OPTIONS ───────────────────────────────────────
    st.subheader("📥 Export Audit Reports")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        csv_bytes = results_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📊 Download CSV Data",
            data=csv_bytes,
            file_name=f"reconciliation_{st.session_state['client_name']}.csv",
            mime="text/csv",
            use_container_width=True
        )
        
    with col2:
        excel_path = "output/reconciliation_report.xlsx"
        results_df.to_excel(excel_path, index=False)
        with open(excel_path, "rb") as f:
            st.download_button(
                "📗 Download Excel Audit Sheet",
                data=f.read(),
                file_name=f"reconciliation_{st.session_state['client_name']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
    with col3:
        pdf_path = "output/reconciliation_report.pdf"
        generate_pdf_report(
            pdf_path,
            st.session_state["client_name"],
            st.session_state["client_gstin"],
            st.session_state["financial_year"],
            st.session_state["return_period"],
            rec,
            itc,
            ai_insights
        )
        with open(pdf_path, "rb") as f:
            st.download_button(
                "📕 Download PDF Client Report",
                data=f.read(),
                file_name=f"reconciliation_report_{st.session_state['client_name']}.pdf",
                mime="application/pdf",
                use_container_width=True
            )