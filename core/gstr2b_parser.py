import json
from typing import Union, BinaryIO
import pandas as pd
from core.normalizer import (
    normalize_gstin,
    normalize_invoice_number,
    normalize_date,
    normalize_amount
)


def parse_gstr2b(file_or_path: Union[str, BinaryIO]) -> pd.DataFrame:
    """
    Parses a GSTR-2B JSON file (or uploaded file buffer from Streamlit)
    and extracts B2B invoices and Credit/Debit notes into a standard DataFrame.
    """
    # 1. Load JSON data
    if isinstance(file_or_path, str):
        with open(file_or_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = json.load(file_or_path)

    records = []

    # 2. Extract B2B (Regular Invoices)
    b2b_sections = data.get("b2b", [])
    for supplier in b2b_sections:
        ctin = supplier.get("ctin", "")
        trade_name = supplier.get("trdnm", "")

        for inv in supplier.get("inv", []):
            inv_num = inv.get("inum", "")
            inv_date = inv.get("idt", "")
            inv_val = inv.get("val", 0.0)
            inv_type = inv.get("inv_typ", "R")
            itc_elg = inv.get("itc_elg", "Y")

            # Sum up tax amounts from all line items in the invoice
            txval_sum = 0.0
            iamt_sum = 0.0
            camt_sum = 0.0
            samt_sum = 0.0
            csamt_sum = 0.0

            # Some files have top-level tax values, others have items array
            if "items" in inv and isinstance(inv["items"], list):
                for item in inv["items"]:
                    txval_sum += normalize_amount(item.get("txval", 0.0))
                    iamt_sum += normalize_amount(item.get("iamt", 0.0))
                    camt_sum += normalize_amount(item.get("camt", 0.0))
                    samt_sum += normalize_amount(item.get("samt", 0.0))
                    csamt_sum += normalize_amount(item.get("csamt", 0.0))
            else:
                txval_sum = normalize_amount(inv.get("txval", 0.0))
                iamt_sum = normalize_amount(inv.get("iamt", 0.0))
                camt_sum = normalize_amount(inv.get("camt", 0.0))
                samt_sum = normalize_amount(inv.get("samt", 0.0))
                csamt_sum = normalize_amount(inv.get("csamt", 0.0))

            total_tax = round(iamt_sum + camt_sum + samt_sum + csamt_sum, 2)

            records.append({
                "source": "GSTR-2B",
                "doc_type": "INVOICE",
                "supplier_gstin": normalize_gstin(ctin),
                "supplier_name": trade_name.strip(),
                "invoice_number": str(inv_num).strip(),
                "norm_inv_num": normalize_invoice_number(str(inv_num)),
                "invoice_date": normalize_date(inv_date),
                "taxable_value": round(txval_sum, 2),
                "igst": round(iamt_sum, 2),
                "cgst": round(camt_sum, 2),
                "sgst": round(samt_sum, 2),
                "cess": round(csamt_sum, 2),
                "total_tax": total_tax,
                "total_value": normalize_amount(inv_val) or round(txval_sum + total_tax, 2),
                "itc_eligibility": itc_elg
            })

    # 3. Extract CDNR (Credit / Debit Notes)
    cdnr_sections = data.get("cdnr", [])
    for supplier in cdnr_sections:
        ctin = supplier.get("ctin", "")
        trade_name = supplier.get("trdnm", "")

        for nt in supplier.get("nt", []):
            nt_num = nt.get("nt_num", "")
            nt_date = nt.get("nt_dt", "")
            nt_val = nt.get("val", 0.0)
            nt_type = nt.get("ntty", "C")  # 'C' for Credit Note, 'D' for Debit Note
            itc_elg = nt.get("itc_elg", "Y")

            txval_sum = 0.0
            iamt_sum = 0.0
            camt_sum = 0.0
            samt_sum = 0.0
            csamt_sum = 0.0

            if "items" in nt and isinstance(nt["items"], list):
                for item in nt["items"]:
                    txval_sum += normalize_amount(item.get("txval", 0.0))
                    iamt_sum += normalize_amount(item.get("iamt", 0.0))
                    camt_sum += normalize_amount(item.get("camt", 0.0))
                    samt_sum += normalize_amount(item.get("samt", 0.0))
                    csamt_sum += normalize_amount(item.get("csamt", 0.0))
            else:
                txval_sum = normalize_amount(nt.get("txval", 0.0))
                iamt_sum = normalize_amount(nt.get("iamt", 0.0))
                camt_sum = normalize_amount(nt.get("camt", 0.0))
                samt_sum = normalize_amount(nt.get("samt", 0.0))
                csamt_sum = normalize_amount(nt.get("csamt", 0.0))

            total_tax = round(iamt_sum + camt_sum + samt_sum + csamt_sum, 2)

            records.append({
                "source": "GSTR-2B",
                "doc_type": "CREDIT_NOTE" if nt_type == "C" else "DEBIT_NOTE",
                "supplier_gstin": normalize_gstin(ctin),
                "supplier_name": trade_name.strip(),
                "invoice_number": str(nt_num).strip(),
                "norm_inv_num": normalize_invoice_number(str(nt_num)),
                "invoice_date": normalize_date(nt_date),
                "taxable_value": round(txval_sum, 2),
                "igst": round(iamt_sum, 2),
                "cgst": round(camt_sum, 2),
                "sgst": round(samt_sum, 2),
                "cess": round(csamt_sum, 2),
                "total_tax": total_tax,
                "total_value": normalize_amount(nt_val) or round(txval_sum + total_tax, 2),
                "itc_eligibility": itc_elg
            })

    df = pd.DataFrame(records)
    if df.empty:
        # Return empty DataFrame with defined columns to prevent downstream crashes
        return pd.DataFrame(columns=[
            "source", "doc_type", "supplier_gstin", "supplier_name",
            "invoice_number", "norm_inv_num", "invoice_date",
            "taxable_value", "igst", "cgst", "sgst", "cess",
            "total_tax", "total_value", "itc_eligibility"
        ])

    return df