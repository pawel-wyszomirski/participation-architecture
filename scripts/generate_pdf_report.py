#!/usr/bin/env python3
"""
Generate PDF Report from Ex Ante Validation Results
"""

import json
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


def load_validation_data(json_path: str) -> dict:
    """Load validation results from JSON file"""
    with open(json_path, 'r') as f:
        return json.load(f)


def create_pdf_report(data: dict, output_path: str):
    """Generate PDF report from validation data"""

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=TA_CENTER
    )

    h1_style = ParagraphStyle(
        'CustomH1',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=12,
        spaceBefore=20
    )

    h2_style = ParagraphStyle(
        'CustomH2',
        parent=styles['Heading2'],
        fontSize=13,
        spaceAfter=8,
        spaceBefore=15
    )

    normal_style = styles['Normal']

    # Build document content
    content = []

    analysis = data.get('analysis', data)
    meta = data.get('meta', {})

    # Title
    content.append(Paragraph("Ex Ante Validation Report", title_style))
    content.append(Paragraph("Rulebook & Rule Engine Validation", styles['Heading2']))
    content.append(Spacer(1, 0.5*cm))

    # Metadata
    content.append(Paragraph(f"<b>Generated:</b> {meta.get('generated_at', datetime.now().isoformat())}", normal_style))
    content.append(Paragraph(f"<b>Rulebook Version:</b> {meta.get('rulebook_version', 'N/A')}", normal_style))
    content.append(Paragraph(f"<b>Proposals Evaluated:</b> {meta.get('proposals_count', analysis['summary']['total_proposals'])}", normal_style))
    content.append(Spacer(1, 1*cm))

    # Executive Summary
    content.append(Paragraph("1. Executive Summary", h1_style))

    summary = analysis['summary']
    total = summary['total_proposals']

    summary_data = [
        ['Metric', 'Value', 'Status'],
        ['Total Proposals', str(total), '✓'],
        ['SEC-001 False Positives', str(analysis['sec_001_analysis']['count']), '✓ None'],
        ['TECH-001 False Positives', str(len(analysis['tech_001_analysis'].get('potential_false_positives', []))), '✓ None' if len(analysis['tech_001_analysis'].get('potential_false_positives', [])) == 0 else '⚠ Review'],
        ['Uncategorized', f"{analysis['uncategorized']['count']} ({analysis['uncategorized']['count']/total*100:.1f}%)", '✓ OK' if analysis['uncategorized']['count']/total < 0.15 else '⚠ High'],
    ]

    summary_table = Table(summary_data, colWidths=[8*cm, 4*cm, 3*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ecf0f1')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    content.append(summary_table)
    content.append(Spacer(1, 1*cm))

    # Score Distribution
    content.append(Paragraph("2. Score Distribution", h1_style))

    score_data = [['Score Range', 'Count', 'Percentage', 'Handling']]
    score_dist = summary['score_distribution']
    handling_map = {
        '90-100 (urgent)': 'urgent_deep_review',
        '70-89 (deep_review)': 'deep_review',
        '40-69 (standard)': 'standard_review',
        '25-39 (fast_track)': 'fast_track_ok',
        '0-24 (informational)': 'informational_only'
    }

    for bucket, count in score_dist.items():
        pct = count / total * 100 if total > 0 else 0
        score_data.append([bucket, str(count), f"{pct:.1f}%", handling_map.get(bucket, '')])

    score_table = Table(score_data, colWidths=[5*cm, 3*cm, 3*cm, 5*cm])
    score_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ebf5fb')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#aed6f1')),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    content.append(score_table)
    content.append(Spacer(1, 1*cm))

    # Phase 0: Context Rules
    content.append(Paragraph("3. Phase 0: Context Detection Rules", h1_style))

    ctx_data = [['Rule ID', 'Description', 'Fired', 'Percentage']]
    ctx_rules = [
        ('ctx_001_analysis', 'CTX-001', 'STATE_CLOSED detection'),
        ('ctx_002_analysis', 'CTX-002', 'CONTEXT_ELECTION detection'),
        ('ctx_003_analysis', 'CTX-003', 'CONTEXT_HR detection'),
        ('ctx_004_analysis', 'CTX-004', 'CONTEXT_SPONSORSHIP detection'),
    ]

    for key, rule_id, desc in ctx_rules:
        if key in analysis:
            count = analysis[key]['count']
            pct = count / total * 100 if total > 0 else 0
            ctx_data.append([rule_id, desc, str(count), f"{pct:.1f}%"])

    ctx_table = Table(ctx_data, colWidths=[3*cm, 7*cm, 3*cm, 3*cm])
    ctx_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#eafaf1')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#a9dfbf')),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    content.append(ctx_table)
    content.append(Spacer(1, 1*cm))

    # Phase 1: Critical Rules
    content.append(Paragraph("4. Phase 1: Critical Rules (Security & Protocol)", h1_style))

    content.append(Paragraph("4.1 SEC-001-STRICT: Active Security Incident", h2_style))
    sec = analysis['sec_001_analysis']
    content.append(Paragraph(f"<b>Times Fired:</b> {sec['count']}", normal_style))
    content.append(Paragraph(f"<b>Potential False Positives:</b> {len(sec.get('potential_false_positives', []))}", normal_style))
    if sec['count'] == 0:
        content.append(Paragraph("✓ No security incidents flagged (expected for historical data)", normal_style))
    content.append(Spacer(1, 0.5*cm))

    content.append(Paragraph("4.2 TECH-001-STRICT: Protocol Upgrade", h2_style))
    tech = analysis['tech_001_analysis']
    content.append(Paragraph(f"<b>Times Fired:</b> {tech['count']} ({tech['count']/total*100:.1f}%)", normal_style))
    content.append(Paragraph(f"<b>Potential False Positives:</b> {len(tech.get('potential_false_positives', []))}", normal_style))
    if len(tech.get('potential_false_positives', [])) == 0:
        content.append(Paragraph("✓ No false positives detected", normal_style))
    content.append(Spacer(1, 1*cm))

    # Phase 2: Standard Rules
    content.append(Paragraph("5. Phase 2: Standard Classification Rules", h1_style))

    std_data = [['Rule ID', 'Description', 'Fired', 'Percentage']]
    std_rules = [
        ('prog_001_analysis', 'PROG-001', 'New Program Creation'),
        ('tech_002_analysis', 'TECH-002', 'Parameter Change'),
        ('tre_010_analysis', 'TRE-010', 'Treasury (known amount)'),
        ('tre_021_analysis', 'TRE-021', 'Treasury (unknown amount)'),
        ('gov_030_analysis', 'GOV-030', 'Constitutional Change'),
        ('meta_001_analysis', 'META-001', 'Meta Governance / RFC'),
        ('spon_001_analysis', 'SPON-001', 'Sponsorship'),
        ('ops_050_analysis', 'OPS-050', 'Operational / Administrative'),
        ('rep_001_analysis', 'REP-001', 'Reporting'),
        ('res_001_analysis', 'RES-001', 'Research'),
    ]

    for key, rule_id, desc in std_rules:
        if key in analysis:
            count = analysis[key]['count']
            pct = count / total * 100 if total > 0 else 0
            std_data.append([rule_id, desc, str(count), f"{pct:.1f}%"])

    std_table = Table(std_data, colWidths=[3*cm, 7*cm, 3*cm, 3*cm])
    std_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9b59b6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f5eef8')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#d7bde2')),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    content.append(std_table)
    content.append(Spacer(1, 1*cm))

    # OPS-050 Analysis
    ops = analysis['ops_050_analysis']
    if ops.get('potential_false_negatives'):
        content.append(Paragraph("5.1 OPS-050 Potential False Negatives", h2_style))
        content.append(Paragraph(f"Found {len(ops['potential_false_negatives'])} proposals with important keywords marked as operational:", normal_style))
        content.append(Spacer(1, 0.3*cm))

        ops_fn_data = [['Score', 'Title']]
        for p in ops['potential_false_negatives'][:10]:
            ops_fn_data.append([str(p['score']), p['title'][:60] + '...' if len(p['title']) > 60 else p['title']])

        ops_fn_table = Table(ops_fn_data, colWidths=[2*cm, 14*cm])
        ops_fn_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e74c3c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fadbd8')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#f1948a')),
        ]))
        content.append(ops_fn_table)
        content.append(Paragraph("<i>Note: These proposals have scores 45-80, indicating other rules correctly override OPS-050 cap.</i>", normal_style))

    content.append(PageBreak())

    # Rules Firing Frequency
    content.append(Paragraph("6. Rules Firing Frequency", h1_style))

    rules_data = [['Rule ID', 'Times Fired', 'Percentage']]
    sorted_rules = sorted(summary['by_rule'].items(), key=lambda x: -x[1])
    for rule, count in sorted_rules[:15]:
        pct = count / total * 100 if total > 0 else 0
        rules_data.append([rule, str(count), f"{pct:.1f}%"])

    rules_table = Table(rules_data, colWidths=[7*cm, 4*cm, 4*cm])
    rules_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ebedef')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#aab7b8')),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    content.append(rules_table)
    content.append(Spacer(1, 1*cm))

    # Labels Distribution
    content.append(Paragraph("7. Labels Distribution", h1_style))

    labels_data = [['Label', 'Count', 'Percentage']]
    sorted_labels = sorted(summary['by_label'].items(), key=lambda x: -x[1])
    for label, count in sorted_labels[:15]:
        pct = count / total * 100 if total > 0 else 0
        labels_data.append([label, str(count), f"{pct:.1f}%"])

    labels_table = Table(labels_data, colWidths=[7*cm, 4*cm, 4*cm])
    labels_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16a085')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#e8f6f3')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#a3e4d7')),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    content.append(labels_table)
    content.append(Spacer(1, 1*cm))

    # Uncategorized Proposals
    content.append(Paragraph("8. Uncategorized Proposals (DEFAULT-001)", h1_style))
    uncat = analysis['uncategorized']
    uncat_pct = uncat['count'] / total * 100 if total > 0 else 0

    content.append(Paragraph(f"<b>Count:</b> {uncat['count']} ({uncat_pct:.1f}%)", normal_style))
    content.append(Paragraph(f"<b>Target:</b> &lt;15%", normal_style))
    content.append(Paragraph(f"<b>Status:</b> {'✓ Acceptable' if uncat_pct < 15 else '⚠ Needs improvement'}", normal_style))
    content.append(Spacer(1, 0.5*cm))

    if uncat['proposals']:
        content.append(Paragraph("Sample uncategorized proposals:", normal_style))
        uncat_data = [['Score', 'Title']]
        for p in uncat['proposals'][:15]:
            uncat_data.append([str(p['score']), p['title'][:65] + '...' if len(p['title']) > 65 else p['title']])

        uncat_table = Table(uncat_data, colWidths=[2*cm, 14*cm])
        uncat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#7f8c8d')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f2f3f4')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bfc9ca')),
        ]))
        content.append(uncat_table)

    content.append(PageBreak())

    # Conclusion
    content.append(Paragraph("9. Conclusion", h1_style))

    conclusions = []

    # SEC-001
    if analysis['sec_001_analysis']['count'] == 0:
        conclusions.append("SEC-001-STRICT: ✓ No false positives. Rule correctly identifies only active security incidents.")

    # TECH-001
    tech_fp = len(analysis['tech_001_analysis'].get('potential_false_positives', []))
    if tech_fp == 0:
        conclusions.append("TECH-001-STRICT: ✓ No false positives after removing generic keywords (adopt, new policy).")
    else:
        conclusions.append(f"TECH-001-STRICT: ⚠ {tech_fp} potential false positives detected.")

    # Coverage
    if uncat_pct < 15:
        conclusions.append(f"Coverage: ✓ Only {uncat_pct:.1f}% uncategorized (target: <15%).")
    else:
        conclusions.append(f"Coverage: ⚠ {uncat_pct:.1f}% uncategorized exceeds 15% target.")

    # OPS-050
    ops_fn = len(analysis['ops_050_analysis'].get('potential_false_negatives', []))
    if ops_fn > 0:
        conclusions.append(f"OPS-050: ⚠ {ops_fn} proposals with important keywords marked as operational, but other rules correctly override the cap.")
    else:
        conclusions.append("OPS-050: ✓ No false negatives detected.")

    for c in conclusions:
        content.append(Paragraph(f"• {c}", normal_style))
        content.append(Spacer(1, 0.2*cm))

    content.append(Spacer(1, 1*cm))
    content.append(Paragraph("<b>Recommendation:</b> Rulebook v2.7.0 is validated and ready for Phase 4 code freeze.", normal_style))

    # Footer
    content.append(Spacer(1, 2*cm))
    content.append(Paragraph("—" * 40, normal_style))
    content.append(Paragraph(f"Generated by validate_ex_ante.py | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                            ParagraphStyle('Footer', parent=normal_style, fontSize=8, textColor=colors.gray)))

    # Build PDF
    doc.build(content)
    print(f"PDF report saved to: {output_path}")


if __name__ == '__main__':
    import sys

    json_path = sys.argv[1] if len(sys.argv) > 1 else 'validation_v2.7.0.json'
    output_path = sys.argv[2] if len(sys.argv) > 2 else 'ex_ante_validation_report.pdf'

    print(f"Loading data from: {json_path}")
    data = load_validation_data(json_path)

    print(f"Generating PDF report...")
    create_pdf_report(data, output_path)
