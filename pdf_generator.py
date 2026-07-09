"""
pdf_generator.py
────────────────
Generates a tailored PDF resume for each job application.
Uses the Claude-generated summary + skills, combined with
the static experience/education/projects from profile.py.
"""

import os
import sys
import re
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable
)
from reportlab.lib import colors

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config.profile import CANDIDATE, EXPERIENCE_SUMMARY, BASE_DIR


def _safe_filename(text: str) -> str:
    """Convert company/job title into a safe filename."""
    text = re.sub(r"[^a-zA-Z0-9_\- ]", "", text)
    return text.strip().replace(" ", "_")[:40]


def generate_tailored_resume(job_title: str, company: str,
                              summary: str, skills: str) -> str:
    """
    Creates a PDF resume tailored for this specific job.
    Returns the absolute file path of the generated PDF.
    """

    output_dir = os.path.join(BASE_DIR, "resumes", "generated")
    os.makedirs(output_dir, exist_ok=True)

    fname = f"Resume_{CANDIDATE['name'].replace(' ', '_')}_{_safe_filename(company)}_{_safe_filename(job_title)}.pdf"
    filepath = os.path.join(output_dir, fname)

    styles = getSampleStyleSheet()

    name_style = ParagraphStyle(
        "Name", parent=styles["Title"], fontSize=18,
        spaceAfter=2, textColor=colors.HexColor("#1a1a1a")
    )
    contact_style = ParagraphStyle(
        "Contact", parent=styles["Normal"], fontSize=9,
        textColor=colors.HexColor("#555555"), spaceAfter=8
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading2"], fontSize=12,
        textColor=colors.HexColor("#0a66c2"), spaceBefore=10, spaceAfter=4,
        borderPadding=0
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=9.5,
        leading=14, alignment=TA_LEFT, spaceAfter=4
    )
    bullet_style = ParagraphStyle(
        "Bullet", parent=body_style, leftIndent=12, bulletIndent=2
    )

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        topMargin=18*mm, bottomMargin=15*mm,
        leftMargin=18*mm, rightMargin=18*mm
    )

    elements = []

    # ── Header ──
    elements.append(Paragraph(CANDIDATE["name"], name_style))
    contact_line = (
        f"{CANDIDATE['email']} | {CANDIDATE['phone']} | "
        f"{CANDIDATE['location']}<br/>"
        f'<a href="{CANDIDATE["linkedin"]}">{CANDIDATE["linkedin"]}</a>'
    )
    elements.append(Paragraph(contact_line, contact_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0a66c2")))

    # ── Profile Summary (AI-tailored) ──
    elements.append(Paragraph("PROFILE SUMMARY", section_style))
    elements.append(Paragraph(summary, body_style))

    # ── Core Skills (AI-tailored) ──
    elements.append(Paragraph("CORE SKILLS", section_style))
    skills_formatted = " &nbsp;•&nbsp; ".join([s.strip() for s in skills.split(",")])
    elements.append(Paragraph(skills_formatted, body_style))

    # ── Work Experience (static) ──
    elements.append(Paragraph("WORK EXPERIENCE", section_style))
    exp_lines = EXPERIENCE_SUMMARY.strip().split("\n")
    for line in exp_lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("-"):
            elements.append(Paragraph(f"• {line[1:].strip()}", bullet_style))
        elif line.endswith(":") or "Currently:" in line or "Previous:" in line or "Education:" in line.split(":")[0] or "Key projects" in line:
            elements.append(Paragraph(f"<b>{line}</b>", body_style))
        else:
            elements.append(Paragraph(line, body_style))

    # ── Footer note ──
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=7,
        textColor=colors.HexColor("#999999"), alignment=TA_LEFT
    )
    elements.append(Paragraph(
        f"Tailored for: {job_title} at {company} | Generated: {datetime.now().strftime('%d-%b-%Y')}",
        footer_style
    ))

    doc.build(elements)
    return filepath


# ── Quick test ────────────────────────────────────────────────
if __name__ == "__main__":
    test_summary = (
        "Data professional with 10 years of experience transitioning from operations "
        "to analytics, specializing in Python, SQL, and Power BI for data-driven "
        "decision making. Proven track record building dashboards that reduced "
        "downtime by 15% and predictive models for business insights."
    )
    test_skills = "Python, SQL, Power BI, Tableau, Machine Learning, Statistics, Excel, Data Visualization, Hypothesis Testing, Predictive Analytics"

    path = generate_tailored_resume(
        job_title="Data Analyst",
        company="Test Company Pvt Ltd",
        summary=test_summary,
        skills=test_skills
    )
    print(f"Resume generated at: {path}")
