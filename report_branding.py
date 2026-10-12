"""Shared letterhead for PDF reports."""
from pathlib import Path
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm

def letterhead_flowables(app_root, org_name='Project Financial Management Workflow',
                         subtitle='Benin City · CONTRAconnect programme'):
    styles = getSampleStyleSheet()
    title = ParagraphStyle('LHTitle', parent=styles['Heading2'], textColor=colors.HexColor('#0a4f4f'), spaceAfter=2)
    sub = ParagraphStyle('LHSub', parent=styles['Normal'], textColor=colors.HexColor('#555555'), fontSize=9)
    logo = None
    for p in [Path(app_root)/'static'/'branding'/'knowsoft_logo.png',
              Path(app_root)/'static'/'icons'/'favicon-32.png']:
        if p.is_file():
            try:
                logo = Image(str(p), width=18*mm, height=18*mm)
            except Exception:
                logo = None
            break
    left = [Paragraph(org_name, title), Paragraph(subtitle, sub)]
    if logo:
        t = Table([[logo, left]], colWidths=[22*mm, 150*mm])
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        return [t, Spacer(1, 6)]
    return left + [Spacer(1, 6)]
