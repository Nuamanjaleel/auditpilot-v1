"""
AuditPilot V1.6 — Synthetic Test Data Generator
Generates realistic GSTR-2B JSON + Tally Purchase Register Excel
matching AuditPilot's exact core parser schemas.
"""

import json
import os

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip install openpyxl")
    exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GSTR2B_PATH = os.path.join(SCRIPT_DIR, "test_gstr2b_aug2024.json")
TALLY_PATH = os.path.join(SCRIPT_DIR, "test_tally_purchase_aug2024.xlsx")

CLIENT_GSTIN = "29AABCU9603R1ZM"
CLIENT_NAME = "Sharma & Associates CA"
FILING_PERIOD = "082024"

SUPPLIERS = {
    "ABC": {"gstin": "29AABCA1234A1Z5", "name": "ABC Traders Pvt Ltd"},
    "XYZ": {"gstin": "27AABCX5678B1Z3", "name": "XYZ Enterprises"},
    "PQR": {"gstin": "33AABCP9012C1Z7", "name": "PQR Industries Ltd"},
    "LMN": {"gstin": "07AABCL3456D1Z9", "name": "LMN Corporation"},
    "DEF": {"gstin": "29AABCD7890E1Z1", "name": "DEF Solutions"},
}

INVOICES = [
    # Exact Matches (8)
    ("ABC", "INV/24-25/001", "05-08-2024", 100000.00, 18000.00, 0, 0, 0, "exact"),
    ("ABC", "INV/24-25/002", "12-08-2024", 50000.00, 0, 4500.00, 4500.00, 0, "exact"),
    ("XYZ", "XZ/2024/101", "03-08-2024", 200000.00, 36000.00, 0, 0, 0, "exact"),
    ("PQR", "PQR/INV/201", "07-08-2024", 150000.00, 27000.00, 0, 0, 0, "exact"),
    ("LMN", "LMN-2024-301", "10-08-2024", 300000.00, 54000.00, 0, 0, 0, "exact"),
    ("LMN", "LMN-2024-302", "15-08-2024", 120000.00, 21600.00, 0, 0, 0, "exact"),
    ("DEF", "DEF/INV/401", "01-08-2024", 60000.00, 0, 5400.00, 5400.00, 0, "exact"),
    ("PQR", "PQR/INV/203", "14-08-2024", 95000.00, 17100.00, 0, 0, 0, "exact"),

    # Amount Mismatches (2)
    ("XYZ", "XZ/2024/102", "18-08-2024", 75000.00, 13500.00, 0, 0, 0, "amount_mismatch"),
    ("LMN", "LMN-2024-303", "19-08-2024", 250000.00, 45000.00, 0, 0, 0, "amount_mismatch"),

    # GSTR-2B Only (2)
    ("ABC", "INV/24-25/005", "22-08-2024", 80000.00, 14400.00, 0, 0, 0, "gstr2b_only"),
    ("XYZ", "XZ/2024/105", "28-08-2024", 180000.00, 32400.00, 0, 0, 0, "gstr2b_only"),

    # Tally Only (2)
    ("PQR", "PQR/INV/206", "26-08-2024", 140000.00, 25200.00, 0, 0, 0, "tally_only"),
    ("DEF", "DEF/INV/406", "29-08-2024", 55000.00, 0, 4950.00, 4950.00, 0, "tally_only"),

    # GSTIN Typo (1)
    ("DEF", "DEF/INV/402", "20-08-2024", 90000.00, 0, 8100.00, 8100.00, 0, "gstin_typo"),

    # Date Difference (1)
    ("ABC", "INV/24-25/004", "30-08-2024", 110000.00, 19800.00, 0, 0, 0, "date_diff"),
]


def build_gstr2b_json():
    supplier_invoices = {}
    for inv in INVOICES:
        sup_key, inum, idt, txval, igst, cgst, sgst, cess, dtype = inv
        if dtype == "tally_only":
            continue

        gstin = SUPPLIERS[sup_key]["gstin"]
        sup_name = SUPPLIERS[sup_key]["name"]

        if gstin not in supplier_invoices:
            supplier_invoices[gstin] = {"trdnm": sup_name, "invs": []}

        total_val = txval + igst + cgst + sgst + cess
        supplier_invoices[gstin]["invs"].append({
            "inum": inum,
            "idt": idt,
            "val": round(total_val, 2),
            "txval": round(txval, 2),
            "iamt": round(igst, 2),
            "camt": round(cgst, 2),
            "samt": round(sgst, 2),
            "csamt": round(cess, 2),
            "pos": gstin[:2],
            "rchrg": "N",
            "inv_typ": "R",
            "itc_elg": "Y",
            "itms": [
                {
                    "num": 1,
                    "itm_det": {
                        "txval": round(txval, 2),
                        "iamt": round(igst, 2),
                        "camt": round(cgst, 2),
                        "samt": round(sgst, 2),
                        "csamt": round(cess, 2),
                        "rt": 18
                    }
                }
            ]
        })

    b2b = []
    for gstin, data in supplier_invoices.items():
        b2b.append({
            "ctin": gstin,
            "trdnm": data["trdnm"],
            "cfs": "Y",
            "inv": data["invs"]
        })

    return {
        "gstin": CLIENT_GSTIN,
        "fp": FILING_PERIOD,
        "b2b": b2b,
        "b2ba": [], "cdnr": [], "cdnra": [], "isup_rev": [], "impg": []
    }


def build_tally_excel():
    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase Register"

    header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    data_font = Font(name="Arial", size=10)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )

    ws.merge_cells("A1:J1")
    ws["A1"] = "Purchase Register"
    ws["A1"].font = Font(name="Arial", size=14, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")

    headers = [
        "Date", "Particulars", "Vch Type", "Supplier Invoice No.",
        "GSTIN/UIN", "Taxable Value", "IGST", "CGST", "SGST", "Invoice Amount"
    ]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    row = 5
    for inv in INVOICES:
        sup_key, inum, idt, txval, igst, cgst, sgst, cess, dtype = inv
        if dtype == "gstr2b_only":
            continue

        sup_name = SUPPLIERS[sup_key]["name"]
        sup_gstin = SUPPLIERS[sup_key]["gstin"]

        tally_txval = txval
        tally_igst = igst
        tally_cgst = cgst
        tally_sgst = sgst
        tally_gstin = sup_gstin
        tally_date = idt

        if dtype == "amount_mismatch":
            if inum == "XZ/2024/102":
                tally_txval = 72000.00
                tally_igst = 12960.00
            elif inum == "LMN-2024-303":
                tally_txval = 248000.00
                tally_igst = 44640.00
        elif dtype == "gstin_typo":
            tally_gstin = "29AABCD7890E1ZZ"
        elif dtype == "date_diff":
            tally_date = "31-08-2024"

        total_val = tally_txval + tally_igst + tally_cgst + tally_sgst + cess

        data = [
            tally_date, sup_name, "Purchase", inum, tally_gstin,
            round(tally_txval, 2), round(tally_igst, 2), round(tally_cgst, 2),
            round(tally_sgst, 2), round(total_val, 2)
        ]

        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.font = data_font
            cell.border = thin_border
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center")
            elif col_idx >= 6:
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
        row += 1

    widths = [12, 28, 12, 22, 20, 16, 14, 14, 14, 18]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    return wb


def main():
    print("=" * 60)
    print("  AUDITPILOT V1.6 — Test Data Generator")
    print("=" * 60)

    gstr2b = build_gstr2b_json()
    with open(GSTR2B_PATH, "w", encoding="utf-8") as f:
        json.dump(gstr2b, f, indent=2, ensure_ascii=False)
    print(f"\n✅ GSTR-2B JSON created: {GSTR2B_PATH}")

    wb = build_tally_excel()
    wb.save(TALLY_PATH)
    print(f"\n✅ Tally Excel created: {TALLY_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()