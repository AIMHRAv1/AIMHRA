"""PDF report generation (reportlab). Content: patient identifier, assessment
date, risk category, probability, model version, trend, explanation, rule
alerts and a prominent disclaimer."""
import logging
from io import BytesIO

from django.core.files.base import ContentFile
from django.utils import timezone

from assessments.services import DISCLAIMER, prediction_series
from assessments.trends import compute_trend
from reports.models import Report

logger = logging.getLogger(__name__)

ACCENT = (0.10, 0.35, 0.45)
RISK_COLORS = {
    "low risk": (0.13, 0.55, 0.35),
    "mid risk": (0.85, 0.56, 0.10),
    "high risk": (0.78, 0.18, 0.18),
}


def generate_report(assessment, generated_by):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    prediction = assessment.prediction
    patient = assessment.patient
    history = prediction_series(patient)
    trend = compute_trend(history)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="AIMHRA Maternal Risk Assessment Report",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=colors.Color(*ACCENT), fontSize=16)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("Small", parent=body, fontSize=8, textColor=colors.grey)

    story = []
    story.append(Paragraph("Maternal Health Risk Assessment Report", h1))
    story.append(Paragraph(f"Generated: {timezone.localtime().strftime('%Y-%m-%d %H:%M')} — AIMHRA decision-support system", small))
    story.append(Spacer(1, 8))

    risk_color = colors.Color(*RISK_COLORS.get(prediction.risk_level, (0, 0, 0)))
    risk_style = ParagraphStyle("Risk", parent=h2, textColor=risk_color, fontSize=14)
    story.append(Paragraph(f"Risk category: {prediction.risk_level.upper()}", risk_style))
    story.append(Paragraph(f"Model confidence: {round(prediction.probability * 100, 1)}%", body))
    story.append(Paragraph(
        f"Per-class probabilities: "
        + ", ".join(f"{k}: {round(v * 100, 1)}%" for k, v in (prediction.probabilities or {}).items()),
        body,
    ))
    story.append(Paragraph(
        f"Model: {prediction.model_name} {prediction.model_version}", body))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Patient", h2))
    story.append(Paragraph(
        f"Patient identifier: {patient.patient_code}<br/>"
        f"Assessment date: {assessment.visit_date}<br/>"
        + (f"Gestational week: {assessment.gestational_week}<br/>" if assessment.gestational_week else ""),
        body))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Assessment measurements", h2))
    rows = [["Measurement", "Value"]]
    for label, value in [
        ("Age (years)", assessment.age), ("Body temperature (F)", assessment.body_temperature),
        ("Heart rate (bpm)", assessment.heart_rate), ("Systolic BP (mm Hg)", assessment.systolic_bp),
        ("Diastolic BP (mm Hg)", assessment.diastolic_bp), ("BMI (kg/m2)", assessment.bmi),
        ("HbA1c column value", assessment.hba1c), ("Fasting glucose column value", assessment.fasting_glucose),
    ]:
        rows.append([label, str(value)])
    table = Table(rows, colWidths=[70 * mm, 50 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(*ACCENT)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.97, 0.97)]),
    ]))
    story.append(table)
    story.append(Spacer(1, 6))

    story.append(Paragraph("Risk trend", h2))
    trend_line = " -> ".join(trend["sequence"]) if trend.get("sequence") else "single assessment"
    story.append(Paragraph(
        f"Stored assessment sequence: {trend_line}<br/>"
        f"Direction vs previous: {trend['direction']} ({trend['status']})", body))
    story.append(Paragraph("The system does not predict future risk; trends describe stored assessments only.", small))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Model explanation (SHAP)", h2))
    explanation = prediction.explanation or {}
    for item in (explanation.get("features") or [])[:6]:
        direction = "increased" if item["direction"] == "increasing" else ("decreased" if item["direction"] == "decreasing" else "neutral")
        story.append(Paragraph(
            f"• {item['label']} = {item['value']} — {direction} the model's risk estimate (impact {item['impact']:+.3f})",
            body))
    story.append(Paragraph(explanation.get("disclaimer", ""), small))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Rule-based alerts", h2))
    alerts = list(assessment.alerts.all())
    if alerts:
        for alert in alerts:
            story.append(Paragraph(f"• [{alert.category}] {alert.message}", body))
    else:
        story.append(Paragraph("No warning rules triggered for this assessment.", body))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Disclaimer", h2))
    story.append(Paragraph(DISCLAIMER, body))

    doc.build(story)
    pdf_bytes = buffer.getvalue()

    report = Report(patient=patient, assessment=assessment, generated_by=generated_by)
    filename = f"report_{patient.patient_code}_{assessment.id}_{timezone.localtime().strftime('%Y%m%d%H%M%S')}.pdf"
    report.file.save(filename, ContentFile(pdf_bytes), save=False)
    report.save()
    return report
