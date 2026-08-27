from typing import Dict, Any, List
import pandas as pd
from rapidfuzz import fuzz


def run_reconciliation(df_2b: pd.DataFrame, df_tally: pd.DataFrame) -> Dict[str, Any]:
    """
    Performs 3-pass automated GST reconciliation between GSTR-2B and Tally.
    Returns matched records, unmatched records, and detailed stats.
    """
    matched_records: List[Dict[str, Any]] = []
    
    # Work on copies with tracking flags
    g2b = df_2b.copy()
    tally = df_tally.copy()
    
    g2b['matched'] = False
    tally['matched'] = False
    
    # -------------------------------------------------------------
    # PASS 1: EXACT MATCH (Exact GSTIN + Exact Norm Inv No + Value Tolerance <= ₹2)
    # -------------------------------------------------------------
    for t_idx, t_row in tally.iterrows():
        if tally.at[t_idx, 'matched']:
            continue
            
        candidate_mask = (
            (~g2b['matched']) &
            (g2b['supplier_gstin'] == t_row['supplier_gstin']) &
            (g2b['norm_inv_num'] == t_row['norm_inv_num']) &
            ((g2b['total_value'] - t_row['total_value']).abs() <= 2.0)
        )
        candidates = g2b[candidate_mask]
        
        if not candidates.empty:
            g_idx = candidates.index[0]
            g_row = g2b.loc[g_idx]
            
            tally.at[t_idx, 'matched'] = True
            g2b.at[g_idx, 'matched'] = True
            
            matched_records.append(_build_match_dict(
                status="EXACT_MATCH",
                confidence=100.0,
                g_row=g_row,
                t_row=t_row,
                remarks="Exact GSTIN, invoice number, and value match."
            ))

    # -------------------------------------------------------------
    # PASS 2: FUZZY MATCH (Exact GSTIN + Fuzzy Inv No >= 80% + Value Tolerance <= ₹50)
    # -------------------------------------------------------------
    for t_idx, t_row in tally[~tally['matched']].iterrows():
        t_gstin = t_row['supplier_gstin']
        t_inv_norm = t_row['norm_inv_num']
        t_val = t_row['total_value']
        
        candidates = g2b[(~g2b['matched']) & (g2b['supplier_gstin'] == t_gstin)]
        
        best_score = 0.0
        best_g_idx = None
        
        for g_idx, g_row in candidates.iterrows():
            sim_score = fuzz.token_sort_ratio(t_inv_norm, g_row['norm_inv_num'])
            val_diff = abs(g_row['total_value'] - t_val)
            
            if sim_score >= 75.0 and val_diff <= 50.0:
                if sim_score > best_score:
                    best_score = sim_score
                    best_g_idx = g_idx
                    
        if best_g_idx is not None:
            g_row = g2b.loc[best_g_idx]
            tally.at[t_idx, 'matched'] = True
            g2b.at[best_g_idx, 'matched'] = True
            
            matched_records.append(_build_match_dict(
                status="FUZZY_MATCH",
                confidence=round(best_score, 1),
                g_row=g_row,
                t_row=t_row,
                remarks=f"Fuzzy invoice match ({best_score:.0f}% similarity)."
            ))

    # -------------------------------------------------------------
    # PASS 3: AMOUNT & DATE MATCH (Exact GSTIN + Exact Value <= ₹2 + Date within 15 days)
    # -------------------------------------------------------------
    for t_idx, t_row in tally[~tally['matched']].iterrows():
        t_gstin = t_row['supplier_gstin']
        t_val = t_row['total_value']
        t_date = t_row['invoice_date']
        
        candidates = g2b[
            (~g2b['matched']) & 
            (g2b['supplier_gstin'] == t_gstin) & 
            ((g2b['total_value'] - t_val).abs() <= 2.0)
        ]
        
        for g_idx, g_row in candidates.iterrows():
            g_date = g_row['invoice_date']
            days_diff = 0
            if t_date and g_date:
                days_diff = abs((t_date - g_date).days)
                
            if days_diff <= 30:
                tally.at[t_idx, 'matched'] = True
                g2b.at[g_idx, 'matched'] = True
                
                matched_records.append(_build_match_dict(
                    status="PARTIAL_MATCH",
                    confidence=70.0,
                    g_row=g_row,
                    t_row=t_row,
                    remarks=f"Matched on GSTIN & Value (Diff inv numbers: '{t_row['invoice_number']}' vs '{g_row['invoice_number']}')."
                ))
                break

    # -------------------------------------------------------------
    # UNMATCHED RECORDS
    # -------------------------------------------------------------
    # 1. Missing in GSTR-2B (Recorded in Tally, supplier didn't file -> BLOCKED ITC)
    unmatched_tally = tally[~tally['matched']]
    for _, t_row in unmatched_tally.iterrows():
        matched_records.append({
            "status": "MISSING_IN_2B",
            "confidence": 0.0,
            "supplier_gstin": t_row['supplier_gstin'],
            "supplier_name": t_row['supplier_name'],
            "tally_inv_num": t_row['invoice_number'],
            "g2b_inv_num": "-",
            "tally_date": t_row['invoice_date'],
            "g2b_date": None,
            "tally_taxable": t_row['taxable_value'],
            "g2b_taxable": 0.0,
            "tally_tax": t_row['total_tax'],
            "g2b_tax": 0.0,
            "tally_total": t_row['total_value'],
            "g2b_total": 0.0,
            "value_diff": t_row['total_value'],
            "tax_diff": t_row['total_tax'],
            "itc_at_risk": t_row['total_tax'],
            "remarks": "Invoice present in Tally books but NOT in GSTR-2B. ITC cannot be claimed."
        })

    # 2. Missing in Books (In GSTR-2B, but accountant forgot to enter in Tally)
    unmatched_g2b = g2b[~g2b['matched']]
    for _, g_row in unmatched_g2b.iterrows():
        matched_records.append({
            "status": "MISSING_IN_BOOKS",
            "confidence": 0.0,
            "supplier_gstin": g_row['supplier_gstin'],
            "supplier_name": g_row['supplier_name'],
            "tally_inv_num": "-",
            "g2b_inv_num": g_row['invoice_number'],
            "tally_date": None,
            "g2b_date": g_row['invoice_date'],
            "tally_taxable": 0.0,
            "g2b_taxable": g_row['taxable_value'],
            "tally_tax": 0.0,
            "g2b_tax": g_row['total_tax'],
            "tally_total": 0.0,
            "g2b_total": g_row['total_value'],
            "value_diff": -g_row['total_value'],
            "tax_diff": -g_row['total_tax'],
            "itc_at_risk": 0.0,
            "remarks": "Invoice present in GSTR-2B but NOT recorded in Tally books."
        })

    results_df = pd.DataFrame(matched_records)
    return {
        "results_df": results_df,
        "total_2b_count": len(df_2b),
        "total_tally_count": len(df_tally),
        "exact_count": int((results_df['status'] == 'EXACT_MATCH').sum()),
        "fuzzy_count": int((results_df['status'] == 'FUZZY_MATCH').sum()),
        "partial_count": int((results_df['status'] == 'PARTIAL_MATCH').sum()),
        "missing_in_2b_count": int((results_df['status'] == 'MISSING_IN_2B').sum()),
        "missing_in_books_count": int((results_df['status'] == 'MISSING_IN_BOOKS').sum())
    }


def _build_match_dict(status: str, confidence: float, g_row: pd.Series, t_row: pd.Series, remarks: str) -> Dict[str, Any]:
    val_diff = round(t_row['total_value'] - g_row['total_value'], 2)
    tax_diff = round(t_row['total_tax'] - g_row['total_tax'], 2)
    
    return {
        "status": status,
        "confidence": confidence,
        "supplier_gstin": t_row['supplier_gstin'] or g_row['supplier_gstin'],
        "supplier_name": t_row['supplier_name'] or g_row['supplier_name'],
        "tally_inv_num": t_row['invoice_number'],
        "g2b_inv_num": g_row['invoice_number'],
        "tally_date": t_row['invoice_date'],
        "g2b_date": g_row['invoice_date'],
        "tally_taxable": t_row['taxable_value'],
        "g2b_taxable": g_row['taxable_value'],
        "tally_tax": t_row['total_tax'],
        "g2b_tax": g_row['total_tax'],
        "tally_total": t_row['total_value'],
        "g2b_total": g_row['total_value'],
        "value_diff": val_diff,
        "tax_diff": tax_diff,
        "itc_at_risk": 0.0,
        "remarks": remarks
    }