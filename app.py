import streamlit as st
import pandas as pd
import json
import os
import plotly.express as px
from core.gstr2b_parser import parse_gstr2b
from core.tally_parser import parse_tally_excel
from core.matching_engine import run_reconciliation
from core.itc_calculator import compute_itc_summary
from core.ai_insights import generate_ca_insights
from core.gst_portal import GSTPortalAutomation
from reports.pdf_generator import generate_pdf_report


# ─── PAGE CONFIG ───────────────────────────────────────────────
st.set_page_config(
    page_title="AuditPilot — AI GST Engine",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── SIDEBAR & THEME TOGGLE ────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/ios-filled/100/scales.png", width=50)
    st.markdown("## AuditPilot OS")
    st.caption("v1.5.0")
    
    st.markdown("---")
    # Premium Theme Toggle
    is_dark = st.toggle("🌙 Dark Mode", value=True)
    st.markdown("---")
    
    st.markdown("### 📌 Instructions")
    st.markdown("""
    1. Enter **Client Details**.
    2. Choose **Manual Upload** OR **Fetch**.
    3. Upload **Tally Purchase Register**.
    4. Click **Reconcile Now**.
    """)

# ─── DYNAMIC CSS (APPLE / NOTHING AESTHETIC) ───────────────────
if is_dark:
    # "NOTHING" BRAND AESTHETIC (Brutalist, Pure Black, Sharp)
    theme_css = """
    <style>
        /* Import Inter Font */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, sans-serif;
        }
        .stApp { background-color: #000000; color: #FFFFFF; }
        [data-testid="stSidebar"] { background-color: #0A0A0A; border-right: 1px solid #222; }
        
        /* Metric Cards - Nothing Style */
        div[data-testid="stMetric"] {
            background-color: #000000;
            border: 1px solid #333333;
            border-radius: 4px; /* Sharp corners */
            padding: 20px;
            box-shadow: none;
        }
        
        .main-header {
            font-size: 3rem;
            font-weight: 800;
            letter-spacing: -1.5px;
            color: #FFFFFF;
            margin-bottom: 0px;
        }
        .sub-header { color: #888888; font-size: 1.1rem; margin-bottom: 30px; letter-spacing: -0.5px; }
        
        /* Primary Button */
        .stButton>button[kind="primary"] {
            background-color: #FFFFFF;
            color: #000000;
            font-weight: 800;
            border-radius: 4px;
            border: none;
            padding: 15px 30px;
            transition: all 0.2s ease;
        }
        .stButton>button[kind="primary"]:hover { background-color: #CCCCCC; transform: scale(0.98); }
        
        /* Hide Clutter */
        #MainMenu, footer, header, .stDeployButton {display:none;}
    </style>
    """
else:
    # "APPLE" BRAND AESTHETIC (Clean, Off-white, Soft Shadows, Rounded)
    theme_css = """
    <style>
        html, body, [class*="css"] {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        .stApp { background-color: #F5F5F7; color: #1D1D1F; }
        [data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #E5E5EA; }
        
        /* Metric Cards - Apple Style */
        div[data-testid="stMetric"] {
            background-color: #FFFFFF;
            border: 1px solid #E5E5EA;
            border-radius: 18px; /* Soft Apple rounded corners */
            padding: 20px;
            box-shadow: 0 4px 14px rgba(0,0,0,0.04);
        }
        div[data-testid="stMetric"] label { color: #86868B !important; }
        div[data-testid="stMetric"] div { color: #1D1D1F !important; }
        
        .main-header {
            font-size: 3rem;
            font-weight: 700;
            letter-spacing: -1px;
            color: #1D1D1F;
            margin-bottom: 0px;
        }
        .sub-header { color: #86868B; font-size: 1.1rem; margin-bottom: 30px; }
        
        /* Primary Button */
        .stButton>button[kind="primary"] {
            background-color: #0071E3;
            color: #FFFFFF;
            font-weight: 600;
            border-radius: 20px;
            border: none;
            padding: 15px 30px;
            transition: all 0.2s ease;
        }
        .stButton>button[kind="primary"]:hover { background-color: #0077ED; transform: scale(1.02); }
        
        /* Hide Clutter */
        #MainMenu, footer, header, .stDeployButton {display:none;}
    </style>
    """

st.markdown(theme_css, unsafe_allow_html=True)


# ─── MAIN HEADER ───────────────────────────────────────────────
st.markdown('<div class="main-header">AuditPilot</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Intelligent GST Reconciliation OS.</div>', unsafe_allow_html=True)


# ─── STEP 1: CLIENT DETAILS ───────────────────────────────────
with st.expander("Client Configuration", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Client Name", value="Sharma Enterprises")
        financial_year = st.selectbox("Financial Year", ["2024-25", "2023-24", "2025-26"])
    with col2:
        client_gstin = st.text_input("Client GSTIN", value="27AABCS1234F1Z5", max_chars=15)
        return_period = st.selectbox("Return Period", ["June 2024", "May 2024", "April 2024", "March 2024"])


# ─── STEP 2: SOURCE SELECTION ──────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.header("Data Sources")

tab_manual, tab_auto = st.tabs(["📄 Manual Upload", "🌐 Auto-Fetch (GST Portal)"])

gstr2b_file_obj = None

with tab_manual:
    col1, col2 = st.columns(2)
    with col1:
        gstr2b_file = st.file_uploader("Upload GSTR-2B JSON", type=["json"], key="gstr2b_manual")
        if gstr2b_file:
            gstr2b_file_obj = gstr2b_file
    with col2:
        tally_file = st.file_uploader("Upload Tally Excel", type=["xlsx", "xls"], key="tally_manual")

with tab_auto:
    st.markdown("##### Secure GST Portal Connection")
    col_cred1, col_cred2 = st.columns(2)
    with col_cred1:
        gst_user = st.text_input("GST Username", placeholder="e.g. sharma_tax")
    with col_cred2:
        gst_pass = st.text_input("GST Password", type="password")
        
    if st.button("Load CAPTCHA"):
        if not gst_user or not gst_pass:
            st.error("Enter Username and Password.")
        else:
            with st.spinner("Connecting..."):
                automation = GSTPortalAutomation()
                session_data = automation.fetch_login_captcha()
                if session_data["success"]:
                    st.session_state["gst_session"] = session_data
                    st.success("Connected! Solve CAPTCHA below:")
                else:
                    st.error(f"Failed: {session_data.get('error')}")

    if "gst_session" in st.session_state:
        session_data = st.session_state["gst_session"]
        st.image(f"data:image/png;base64,{session_data['captcha_b64']}")
        captcha_input = st.text_input("Enter 6-character CAPTCHA:", max_chars=6)
        
        if st.button("Login & Fetch GSTR-2B"):
            if not captcha_input:
                st.error("Enter CAPTCHA.")
            else:
                with st.spinner("Downloading JSON..."):
                    automation = GSTPortalAutomation()
                    download_res = automation.login_and_download_gstr2b(
                        session_data, gst_user, gst_pass, captcha_input, financial_year, return_period
                    )
                    if download_res["success"]:
                        st.success("✅ Download complete!")
                        st.session_state["fetched_gstr2b_path"] = download_res["file_path"]
                    else:
                        st.error(f"Failed: {download_res.get('error')}")

    if "fetched_gstr2b_path" in st.session_state:
        gstr2b_file_obj = st.session_state["fetched_gstr2b_path"]


# ─── STEP 3: RECONCILE BUTTON ─────────────────────────────────
st.markdown("<br><br>", unsafe_allow_html=True)
if st.button("RUN RECONCILIATION", type="primary", use_container_width=True):
    
    if not gstr2b_file_obj or not tally_file:
        st.error("Provide both files to proceed.")
    else:
        with st.spinner("Computing match logic..."):
            try:
                df_2b = parse_gstr2b(gstr2b_file_obj)
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
                
            except Exception as e:
                st.error(f"Execution Error: {str(e)}")


# ─── STEP 4: DASHBOARD ────────────────────────────────────────
if "results_df" in st.session_state:
    results_df = st.session_state["results_df"]
    rec = st.session_state["rec_results"]
    itc = st.session_state["itc_summary"]
    ai_insights = st.session_state["ai_insights"]
    
    st.markdown("---")
    st.header("Executive Summary")
    
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Exact Match", rec["exact_count"])
    m2.metric("Fuzzy Match", rec["fuzzy_count"])
    m3.metric("Partial Match", rec["partial_count"])
    m4.metric("Missing in 2B", rec["missing_in_2b_count"])
    m5.metric("Missing in Books", rec["missing_in_books_count"])
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.header("ITC Impact")
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Eligible Claimable", f"₹{itc['itc_eligible']:,.2f}")
    i2.metric("Blocked (At Risk)", f"₹{itc['itc_at_risk']:,.2f}")
    i3.metric("Unclaimed (Books)", f"₹{itc['itc_unclaimed']:,.2f}")
    i4.metric("Match Rate", f"{itc['match_rate_pct']}%")
    
    st.markdown("---")
    st.header("CA Intelligence")
    st.info(ai_insights)
    
    st.markdown("---")
    st.header("Invoice Breakdown")
    col_search, col_filter = st.columns([2, 1])
    with col_search:
        search_term = st.text_input("Search GSTIN, Name, or Invoice", "")
    with col_filter:
        status_filter = st.selectbox(
            "Filter:",
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
    st.header("Export")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download CSV", data=results_df.to_csv(index=False).encode("utf-8"), file_name="report.csv", use_container_width=True)
    with c2:
        results_df.to_excel("temp.xlsx", index=False)
        with open("temp.xlsx", "rb") as f:
            st.download_button("Download Excel", data=f.read(), file_name="report.xlsx", use_container_width=True)
    with c3:
        os.makedirs("output", exist_ok=True)
        pdf_path = "output/report.pdf"
        generate_pdf_report(pdf_path, st.session_state["client_name"], st.session_state["client_gstin"], st.session_state["financial_year"], st.session_state["return_period"], rec, itc, ai_insights)
        with open(pdf_path, "rb") as f:
            st.download_button("Download PDF", data=f.read(), file_name="report.pdf", use_container_width=True)