from typing import Union, BinaryIO
import pandas as pd
from core.normalizer import (
    normalize_gstin,
    normalize_invoice_number,
    normalize_date,
    normalize_amount
)


# Column aliases dictionary for flexible header detection
COLUMN_ALIASES = {
    "date": [
        "date", "voucher date", "inv date", "invoice date", "bill date"
    ],
    "supplier_name": [
        "particulars", "party name", "party particulars", "supplier name",
        "vendor name", "party", "account"
    ],
    "voucher_type": [
        "voucher type", "vch type", "type"
    ],
    "invoice_number": [
        "voucher no", "vch no", "voucher no.", "vch no.", "invoice no",
        "invoice no.", "supplier inv no", "supplier invoice no", "bill no", "doc no"
    ],
    "supplier_gstin": [
        "gstin", "gstin/uin", "party gstin", "supplier gstin", "uin", "gst in"
    ],
    "taxable_value": [
        "taxable value", "taxable amount", "assessable value", "taxable val", "taxable"
    ],
    "igst": [
        "integrated tax", "igst", "igst amount", "igst amt", "integrated tax amount"
    ],
    "cgst": [
        "central tax", "cgst", "cgst amount", "cgst amt", "central tax amount"
    ],
    "sgst": [
        "state tax", "sgst", "sgst amount", "sgst amt", "state/ut tax", "utgst"
    ],
    "cess": [
        "cess", "cess amount", "cess amt"
    ],
    "total_value": [
        "total", "total amount", "gross total", "invoice amount", "inv amount", "net amount"
    ]
}


def _find_header_row(df_raw: pd.DataFrame) -> int:
    """
    Scans the first 15 rows of an Excel file to find where the actual table headers start.
    """
    for idx, row in df_raw.head(15).iterrows():
        row_values = [str(val).lower().strip() for val in row.values if pd.notna(val)]
        # Check if at least 2 key accounting column terms exist in this row
        match_count = sum(
            1 for val in row_values
            if any(alias in val for aliases in COLUMN_ALIASES.values() for alias in aliases)
        )
        if match_count >= 2:
            return idx
    return 0


def _map_columns(df: pd.DataFrame) -> dict:
    """
    Maps detected Excel column names to standard internal field names.
    """
    column_mapping = {}
    cleaned_df_cols = {col: str(col).lower().strip() for col in df.columns}

    for standard_col, aliases in COLUMN_ALIASES.items():
        for original_col, clean_name in cleaned_df_cols.items():
            if clean_name in aliases or any(alias == clean_name for alias in aliases):
                column_mapping[original_col] = standard_col
                break

    return column_mapping


def parse_tally_excel(file_or_path: Union[str, BinaryIO]) -> pd.DataFrame:
    """
    Parses a Tally Purchase Register exported as Excel (.xlsx / .xls)
    and returns a clean, standardized DataFrame.
    """
    # 1. Read first 20 rows to detect header position
    df_preview = pd.read_excel(file_or_path, header=None, nrows=20)
    header_row_idx = _find_header_row(df_preview)

    # 2. Re-read the full Excel sheet with the correct header row
    if hasattr(file_or_path, 'seek'):
        file_or_path.seek(0)
    df = pd.read_excel(file_or_path, skiprows=header_row_idx)

    # 3. Map columns to our standard names
    col_map = _map_columns(df)
    df = df.rename(columns=col_map)

    # 4. Filter out blank rows or summary/total rows
    if "supplier_name" in df.columns:
        df = df[df["supplier_name"].notna()]
        df = df[~df["supplier_name"].astype(str).str.lower().str.contains("total|grand total|balance", na=False)]
    
    if "invoice_number" in df.columns:
        df = df[df["invoice_number"].notna()]

    records = []
    for _, row in df.iterrows():
        inv_num = str(row.get("invoice_number", "")).strip()
        if not inv_num or inv_num.lower() in ("nan", "none", "-"):
            continue

        raw_gstin = str(row.get("supplier_gstin", "")).strip()
        supplier_name = str(row.get("supplier_name", "")).strip()

        tx_val = normalize_amount(row.get("taxable_value", 0.0))
        igst_val = normalize_amount(row.get("igst", 0.0))
        cgst_val = normalize_amount(row.get("cgst", 0.0))
        sgst_val = normalize_amount(row.get("sgst", 0.0))
        cess_val = normalize_amount(row.get("cess", 0.0))
        total_tax = round(igst_val + cgst_val + sgst_val + cess_val, 2)

        tot_val = normalize_amount(row.get("total_value", 0.0))
        if tot_val == 0.0:
            tot_val = round(tx_val + total_tax, 2)

        vch_type = str(row.get("voucher_type", "Purchase")).strip().upper()
        doc_type = "CREDIT_NOTE" if "DEBIT" in vch_type or "CREDIT" in vch_type else "INVOICE"

        records.append({
            "source": "TALLY",
            "doc_type": doc_type,
            "supplier_gstin": normalize_gstin(raw_gstin),
            "supplier_name": supplier_name,
            "invoice_number": inv_num,
            "norm_inv_num": normalize_invoice_number(inv_num),
            "invoice_date": normalize_date(row.get("date", None)),
            "taxable_value": tx_val,
            "igst": igst_val,
            "cgst": cgst_val,
            "sgst": sgst_val,
            "cess": cess_val,
            "total_tax": total_tax,
            "total_value": tot_val,
            "itc_eligibility": "Y"
        })

    result_df = pd.DataFrame(records)
    if result_df.empty:
        return pd.DataFrame(columns=[
            "source", "doc_type", "supplier_gstin", "supplier_name",
            "invoice_number", "norm_inv_num", "invoice_date",
            "taxable_value", "igst", "cgst", "sgst", "cess",
            "total_tax", "total_value", "itc_eligibility"
        ])

    return result_df