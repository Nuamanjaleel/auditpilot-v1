from typing import Dict, Any
import pandas as pd


def compute_itc_summary(results_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Computes financial metrics, eligible ITC, at-risk ITC, and match percentages.
    """
    if results_df.empty:
        return {
            "itc_eligible": 0.0,
            "itc_at_risk": 0.0,
            "itc_unclaimed": 0.0,
            "total_books_itc": 0.0,
            "match_rate_pct": 0.0
        }
    
    # 1. Eligible ITC = Tax from all Matched Invoices (Exact, Fuzzy, Partial)
    matched_mask = results_df['status'].isin(['EXACT_MATCH', 'FUZZY_MATCH', 'PARTIAL_MATCH'])
    itc_eligible = round(results_df[matched_mask]['g2b_tax'].sum(), 2)
    
    # 2. ITC At Risk = Tax from Invoices in Tally but MISSING in GSTR-2B
    at_risk_mask = results_df['status'] == 'MISSING_IN_2B'
    itc_at_risk = round(results_df[at_risk_mask]['tally_tax'].sum(), 2)
    
    # 3. Unclaimed ITC in Books = Tax from Invoices in 2B but MISSING in Tally
    unclaimed_mask = results_df['status'] == 'MISSING_IN_BOOKS'
    itc_unclaimed = round(results_df[unclaimed_mask]['g2b_tax'].sum(), 2)
    
    # 4. Total Claimed in Tally Books
    total_books_itc = round(itc_eligible + itc_at_risk, 2)
    
    # 5. Safe Match Rate Percentage
    match_rate = round((itc_eligible / total_books_itc * 100), 1) if total_books_itc > 0 else 0.0
    
    return {
        "itc_eligible": itc_eligible,
        "itc_at_risk": itc_at_risk,
        "itc_unclaimed": itc_unclaimed,
        "total_books_itc": total_books_itc,
        "match_rate_pct": match_rate
    }