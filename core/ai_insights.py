import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()


def generate_ca_insights(client_name: str, rec_summary: Dict[str, Any], itc_summary: Dict[str, Any]) -> str:
    """
    Uses Groq API (Llama 3) to generate professional CA advisory notes.
    Includes a fallback rule-based engine if no API key is present.
    """
    groq_key = os.getenv("GROQ_API_KEY")
    
    # ── Fallback Rule-Based Insights (if no API Key or Network Fail) ──
    fallback_insights = f"""
📌 **1. ITC Risk Warning:** 
You have **₹{itc_summary['itc_at_risk']:,.2f}** in ITC at risk across **{rec_summary['missing_in_2b_count']} invoice(s)** that appear in Tally but are missing in GSTR-2B. Contact these suppliers immediately to file their GSTR-1.

📌 **2. Unclaimed Tax Credit:** 
There is **₹{itc_summary['itc_unclaimed']:,.2f}** in unclaimed ITC from **{rec_summary['missing_in_books_count']} invoice(s)** present in GSTR-2B but missing in your accounting books. Verify if these purchases were recorded under a different account.

📌 **3. Match Rate Health:** 
Your current reconciliation match rate is **{itc_summary['match_rate_pct']}%**. 
- Total Claimable ITC: **₹{itc_summary['itc_eligible']:,.2f}**
- Total Books Claim: **₹{itc_summary['total_books_itc']:,.2f}**
"""

    if not groq_key or groq_key == "gsk_YOUR_ACTUAL_KEY_HERE":
        return fallback_insights.strip()

    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        
        prompt = f"""
You are a senior Indian Chartered Accountant specializing in GST compliance and audits.
Analyze the following GST reconciliation summary for client '{client_name}':

- Total GSTR-2B Invoices: {rec_summary['total_2b_count']}
- Total Tally Invoices: {rec_summary['total_tally_count']}
- Exact Matches: {rec_summary['exact_count']}
- Fuzzy Matches: {rec_summary['fuzzy_count']}
- Missing in GSTR-2B (In Books but not in 2B): {rec_summary['missing_in_2b_count']}
- Missing in Books (In 2B but not in Books): {rec_summary['missing_in_books_count']}
- Eligible ITC: ₹{itc_summary['itc_eligible']}
- ITC At Risk (Blocked): ₹{itc_summary['itc_at_risk']}
- Unclaimed ITC: ₹{itc_summary['itc_unclaimed']}
- Overall Match Rate: {itc_summary['match_rate_pct']}%

Write a professional, concise, 3-bullet-point "CA Advisory & Action Items" note for this client.
Use professional GST terminology (GSTR-1, Section 16(2)(aa), ITC eligibility, supplier follow-up).
Keep it bulleted, clear, and actionable. Do not write introductory chatter.
"""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
        
    except Exception:
        return fallback_insights.strip()