"""Printable report generated from the persisted report, without model calls."""
from io import BytesIO
import json
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether


def report_pdf(title, report_id, content):
    stream = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=colors.HexColor("#153b33"), spaceAfter=16))
    styles.add(ParagraphStyle(name="Section", fontName="Helvetica-Bold", fontSize=15, leading=20, textColor=colors.HexColor("#153b33"), spaceBefore=20, spaceAfter=10, keepWithNext=True))
    styles.add(ParagraphStyle(name="ReportBody", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=9, splitLongWords=True, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="Metadata", parent=styles["ReportBody"], fontSize=8, leading=12, textColor=colors.HexColor("#52635e")))
    styles.add(ParagraphStyle(name="EvidenceBody", parent=styles["ReportBody"], fontName="Courier", fontSize=8, leading=12))

    def clean(value):
        # Built-in PDF fonts support Latin-1; escape untrusted XML and replace
        # unsupported glyphs visibly instead of rendering missing-character boxes.
        return escape(str(value).replace("—", " - ").replace("–", "-").replace("’", "'").encode("latin-1", "backslashreplace").decode("latin-1")).replace("\n", "<br/>")

    def para(value, style="ReportBody"):
        return Paragraph(clean(value), styles[style])

    story = [para("CORTEXOPS AI / INVESTIGATION REPORT", "Metadata"), para(title, "ReportTitle"),
             para(f"Report {report_id}\nGenerated {content.get('generated_at', '')}\nOutcome: {content.get('outcome', 'hypothesis_report')}", "Metadata"),
             para("Working explanation", "Section"), para(content.get("summary", ""))]
    evidence = content.get("evidence", [])
    source_numbers = {item["id"]: i + 1 for i, item in enumerate(evidence)}

    def references(ids):
        return ", ".join(f"[{source_numbers[x]}]" if x in source_numbers else f"[unavailable: {x}]" for x in ids) or "None"

    for heading, key in [("Verified observations", "verified_findings"), ("Root-cause hypotheses", "hypotheses")]:
        story.append(para(heading, "Section"))
        if not content.get(key):
            story.append(para("No supported findings in this category."))
        for finding in content.get(key, []):
            story.append(para(f"{finding.get('classification', 'hypothesis').upper()} / {finding.get('confidence', 'low')} confidence", "Metadata"))
            story.append(para(finding["statement"]))
            story.append(para("Supporting sources: " + references(finding.get("evidence_ids", [])) + "\nContradictory/context sources: " + references(finding.get("contradictory_evidence_ids", [])), "Metadata"))
    for heading, key in [("Recommended actions", "recommendations"), ("Limitations and uncertainty", "limitations")]:
        story.append(para(heading, "Section"))
        story.extend(para(f"{i + 1}. {item}") for i, item in enumerate(content.get(key, [])))
    story.extend([para("Source evidence", "Section"), para("Citation numbers below refer to recorded source outputs. Citation presence does not establish semantic entailment or causality.", "Metadata")])
    for i, item in enumerate(evidence):
        story.append(KeepTogether([para(f"[{i + 1}] {item.get('title', 'Source')}", "Heading3"), para(f"ID: {item['id']}\nSource: {item.get('source', '')}", "Metadata")]))
        story.append(para(json.dumps(item.get("reference", {}), ensure_ascii=True, sort_keys=True), "Metadata"))
        # Preserve the exact stored text; long evidence can flow across pages.
        for start in range(0, len(item.get("content", "")), 4000):
            story.append(para(item["content"][start:start + 4000], "EvidenceBody"))
        story.append(Spacer(1, 8))

    def page_chrome(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d8e4dd"))
        canvas.line(48, 43, doc.pagesize[0] - 48, 43)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#52635e"))
        canvas.drawString(48, 29, "CortexOps AI | Evidence-backed decision support")
        canvas.drawRightString(doc.pagesize[0] - 48, 29, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(stream, pagesize=(8.27 * inch, 11.69 * inch), leftMargin=48, rightMargin=48, topMargin=42, bottomMargin=58,
                            title=title, author="CortexOps AI")
    doc.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)
    return stream.getvalue()
