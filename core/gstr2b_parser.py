import json
import zipfile
import io
import pandas as pd
from typing import Union, Dict, Any, List
from core.normalizer import normalize_gstin, normalize_invoice_number, normalize_date, normalize_amount


def _extract_bytes(file_input: Union[str, io.BytesIO, Any]) -> bytes:
    """Extract raw bytes regardless of whether file_input is a string path or BytesIO stream."""
    if isinstance(file_input, str):
        with open(file_input, "rb") as f:
            return f.read()
    elif hasattr(file_input, "read"):
        content = file_input.read()
        if hasattr(file_input, "seek"):
            file_input.seek(0)
        return content
    else:
        raise ValueError("Unsupported input format for GSTR-2B file.")


def load_gstr2b_json(file_input: Union[str, Any]) -> Dict[str, Any]:
    """
    Intelligently opens GSTR-2B files.
    Handles ZIP archives, UTF-8, UTF-8-SIG, UTF-16, and Latin-1 encodings.
    """
    raw_bytes = _extract_bytes(file_input)

    # Detect PDF mismatch early and give a helpful message
    if raw_bytes.startswith(b"%PDF"):
        raise Exception(
            "The downloaded file is a PDF summary report, not a raw GSTR-2B JSON file. "
            "Please ensure you select 'DOWNLOAD JSON' on the GST Portal."
        )

    # 1. Check if the file is a ZIP archive
    if zipfile.is_zipfile(io.BytesIO(raw_bytes)):
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
            json_files = [f for f in z.namelist() if f.lower().endswith(".json")]
            if not json_files:
                json_files = z.namelist()  # Fallback to first file inside ZIP
            if not json_files:
                raise Exception("The downloaded ZIP file from GST portal contains no valid files.")

            with z.open(json_files[0]) as jf:
                raw_bytes = jf.read()

    # 2. Try decoding with multiple standard encodings
    encodings = ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "latin-1"]
    for enc in encodings:
        try:
            decoded_text = raw_bytes.decode(enc)
            return json.loads(decoded_text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

    raise Exception(
        "Could not parse GSTR-2B file. The file format or encoding is unsupported."
    )


def parse_gstr2b(file_input: Union[str, Any]) -> pd.DataFrame:
    """
    Parses GSTR-2B JSON (B2B, B2BA, CDNR, CDNRA) into a clean Pandas DataFrame.
    """
    data = load_gstr2b_json(file_input)

    # Support nested 'docdata' structure if wrapped by GST portal
    if "docdata" in data and isinstance(data["docdata"], dict):
        data = data["docdata"]

    records: List[Dict[str, Any]] = []

    # ── 1. PARSE B2B INVOICES ─────────────────────────────────────────
    b2b_sections = data.get("b2b", [])
    for supplier in b2b_sections:
        supplier_gstin = supplier.get("ctin", "")
        supplier_name = supplier.get("cfs", "")
        
        invoices = supplier.get("inv", [])
        for inv in invoices:
            inv_no = str(inv.get("inum", ""))
            inv_date = str(inv.get("idt", ""))
            val = normalize_amount(inv.get("val", 0))
            txval = normalize_amount(inv.get("txval", 0))
            igst = normalize_amount(inv.get("iamt", 0))
            cgst = normalize_amount(inv.get("camt", 0))
            sgst = normalize_amount(inv.get("samt", 0))
            cess = normalize_amount(inv.get("csamt", 0))
            itc_elg = inv.get("itc_elg", "Y")

            records.append({
                "supplier_gstin": normalize_gstin(supplier_gstin),
                "supplier_name": str(supplier_name).strip(),
                "invoice_number": inv_no,
                "norm_inv_num": normalize_invoice_number(inv_no),
                "invoice_date": inv_date,
                "parsed_date": normalize_date(inv_date),
                "taxable_value": txval,
                "igst": igst,
                "cgst": cgst,
                "sgst": sgst,
                "cess": cess,
                "total_tax": igst + cgst + sgst + cess,
                "total_value": val,
                "itc_eligibility": itc_elg,
                "section": "B2B"
            })

    # ── 2. PARSE CDNR (CREDIT / DEBIT NOTES) ──────────────────────────
    cdnr_sections = data.get("cdnr", [])
    for supplier in cdnr_sections:
        supplier_gstin = supplier.get("ctin", "")
        supplier_name = supplier.get("cfs", "")
        
        notes = supplier.get("nt", [])
        for note in notes:
            note_no = str(note.get("nt_num", note.get("inum", "")))
            note_date = str(note.get("nt_dt", note.get("idt", "")))
            val = normalize_amount(note.get("val", 0))
            txval = normalize_amount(note.get("txval", 0))
            igst = normalize_amount(note.get("iamt", 0))
            cgst = normalize_amount(note.get("camt", 0))
            sgst = normalize_amount(note.get("samt", 0))
            cess = normalize_amount(note.get("csamt", 0))
            itc_elg = note.get("itc_elg", "Y")

            records.append({
                "supplier_gstin": normalize_gstin(supplier_gstin),
                "supplier_name": str(supplier_name).strip(),
                "invoice_number": note_no,
                "norm_inv_num": normalize_invoice_number(note_no),
                "invoice_date": note_date,
                "parsed_date": normalize_date(note_date),
                "taxable_value": txval,
                "igst": igst,
                "cgst": cgst,
                "sgst": sgst,
                "cess": cess,
                "total_tax": igst + cgst + sgst + cess,
                "total_value": val,
                "itc_eligibility": itc_elg,
                "section": "CDNR"
            })

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=[
            "supplier_gstin", "supplier_name", "invoice_number", "norm_inv_num",
            "invoice_date", "parsed_date", "taxable_value", "igst", "cgst",
            "sgst", "cess", "total_tax", "total_value", "itc_eligibility", "section"
        ])

    return df