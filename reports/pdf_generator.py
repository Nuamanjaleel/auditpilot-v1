import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def generate_pdf_report(
    file_path: str,
    client_name: str,
    client_gstin: str,
    fy: str,
    period: str,
    rec_summary: dict,
    itc_summary: dict,
    ai_insights: str
) -> str:
    """
    Generates a professional PDF reconciliation report using ReportLab.
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    doc = SimpleDocTemplate(file_path, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=20, textColor=colors.HexColor('#1E1E2F'), spaceAfter=6)
    subtitle_style = ParagraphStyle('SubTitleStyle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#666666'), spaceAfter=15)
    section_heading = ParagraphStyle('SectionStyle', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#1E1E2F'), spaceBefore=12, spaceAfter=6)
    normal_text = ParagraphStyle('NormalText', parent=styles['Normal'], fontSize=9, leading=12)

    # Header
    story.append(Paragraph("🏛️ AUDITPILOT — GST RECONCILIATION REPORT", title_style))
    story.append(Paragraph(f"<b>Client:</b> {client_name} | <b>GSTIN:</b> {client_gstin} | <b>Period:</b> {period} (FY {fy})", subtitle_style))
    story.append(Spacer(1, 10))

    # ITC Summary Table
    story.append(Paragraph("1. Financial & ITC Summary", section_heading))
    itc_data = [
        ["Metric", "Amount (₹)"],
        ["Eligible Claimable ITC", f"Rs. {itc_summary['itc_eligible']:,.2f}"],
        ["ITC At Risk (Blocked) ⚠️", f"Rs. {itc_summary['itc_at_risk']:,.2f}"],
        ["Unclaimed ITC in Books", f"Rs. {itc_summary['itc_unclaimed']:,.2f}"],
        ["Total Claimed in Books", f"Rs. {itc_summary['total_books_itc']:,.2f}"],
        ["Reconciliation Match Rate", f"{itc_summary['match_rate_pct']}%"]
    ]
    t_itc = Table(itc_data, colWidths=[250, 250])
    t_itc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E1E2F')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#DDDDDD')),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    story.append(t_itc)
    story.append(Spacer(1, 15))

    # Match Stats Table
    story.append(Paragraph("2. Reconciliation Breakdown", section_heading))
    rec_data = [
        ["Category", "Invoice Count"],
        ["Exact Matches", str(rec_summary['exact_count'])],
        ["Fuzzy Matches", str(rec_summary['fuzzy_count'])],
        ["Partial Matches", str(rec_summary['partial_count'])],
        ["Missing in GSTR-2B (ITC Blocked)", str(rec_summary['missing_in_2b_count'])],
        ["Missing in Books (Unclaimed)", str(rec_summary['missing_in_books_count'])],
    ]
    t_rec = Table(rec_data, colWidths=[250, 250])
    t_rec.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4A4A6A')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#DDDDDD')),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    story.append(t_rec)
    story.append(Spacer(1, 15))

    # AI Insights
    story.append(Paragraph("3. CA Advisory & Action Items", section_heading))
    formatted_insights = ai_insights.replace("\n", "<br/>")
    story.append(Paragraph(formatted_insights, normal_text))

    doc.build(story)
    return file_path