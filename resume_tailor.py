"""
resume_tailor.py
────────────────
Sends a job description to Claude API.
Gets back a tailored resume summary + skills section + cover letter.
Saves a new PDF resume for that specific job.

UPDATED: 
  - Better keyword extraction from JD
  - Honest injection of legitimate missing keywords
  - Calibrated scoring for career-transition candidates
  - Higher application rate for adjacent roles
"""

import anthropic
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.profile import CANDIDATE, SKILLS, EXPERIENCE_SUMMARY, SEARCH

# ── Claude client ─────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ── Master resume template ────────────────────────────────────
MASTER_RESUME_TEXT = f"""
NAME: {CANDIDATE['name']}
EMAIL: {CANDIDATE['email']} | PHONE: {CANDIDATE['phone']}
LINKEDIN: {CANDIDATE['linkedin']} | LOCATION: {CANDIDATE['location']}

PROFILE SUMMARY:
[TO BE WRITTEN BY AI FOR EACH JD]

CORE SKILLS:
[TO BE WRITTEN BY AI FOR EACH JD]

WORK EXPERIENCE:
{EXPERIENCE_SUMMARY}

EDUCATION:
- BE Mechanical Engineering, Mumbai University, 2013
- Data Science & Machine Learning (In Progress), Scaler Academy, Jul 2024–Present

PROJECTS:
- Ola Driver Churn Prediction: Ensemble ML model, Streamlit deployment, feature engineering
- LoanTap Credit Risk Model: Logistic regression, live loan default prediction app
- Walmart CLT Analysis: Confidence intervals, demographic purchasing behavior insights
- Yulu Hypothesis Testing: T-test, ANOVA, Chi-square on bike-sharing demand data
- Target SQL Project: 100k+ e-commerce orders, customer behavior & logistics analysis
- Netflix EDA: Genre trends, regional availability, content strategy insights
- Aerofit Descriptive Analysis: Customer profiling, probability estimation, marketing insights
"""


def tailor_resume(job_title: str, company: str, job_description: str) -> dict:
    """
    Input:  job title, company name, full JD text
    Output: dict with keys:
            - summary       (2-3 line profile summary with JD keywords injected)
            - skills        (comma-separated relevant skills + legit missing keywords)
            - cover_letter  (3 paragraph cover letter)
            - match_score   (0-100 integer, calibrated for career transitions)
            - match_reason  (1 line why this score)
            - keywords_added (which JD keywords got injected)
    """

    prompt = f"""
You are an expert resume writer and ATS optimizer for Data Analytics / Data Science / Business Analytics roles in India.

CANDIDATE BACKGROUND (source of truth — do NOT fabricate beyond this):
{MASTER_RESUME_TEXT}

CANDIDATE CONTEXT (important for scoring):
- 10 years total professional experience (mostly maintenance/operations)
- Actively transitioning to Data Analytics/Science
- Has hands-on Python, SQL, Power BI, Statistics via Scaler Academy
- Has 6+ deployed ML projects (Streamlit apps)
- Has business analysis, dashboard building, stakeholder reporting experience
- Consider him as a mid-level analytics candidate for scoring (NOT a fresher)

TARGET JOB:
Title: {job_title}
Company: {company}
Job Description:
{job_description}

YOUR TASK:
Analyze the JD carefully and produce the following. Reply ONLY in valid JSON, no explanation outside JSON.

{{
  "match_score": <integer 0-100. See scoring guide below>,
  "match_reason": "<one line explaining the score>",
  "summary": "<2-3 sentence profile summary written specifically for this JD. AGGRESSIVELY use keywords from the JD. Highlight most relevant experience. Do NOT mention maintenance unless the JD values it. Sound like a Data professional.>",
  "skills": "<comma-separated list of 12-18 skills. Include: (a) candidate's core skills relevant to JD, (b) LEGITIMATE JD keywords the candidate has but hasn't explicitly listed (e.g., data storytelling, KPI reporting, stakeholder management, dashboard design, ETL, data cleaning, requirement gathering, ad-hoc analysis, exploratory data analysis) — ONLY add these if they're truly implicit in his experience. Do NOT add tools/technologies he genuinely doesn't have (e.g., Snowflake if he never used it).>",
  "cover_letter": "<3 paragraph professional cover letter. Para 1: why this role excites you + key match. Para 2: 2 specific achievements with numbers. Para 3: forward-looking close. Tone: confident, not desperate. Max 200 words total.>",
  "keywords_added": "<comma-separated list of JD keywords you legitimately injected into summary/skills that weren't previously explicit>"
}}

SCORING GUIDE (be generous for adjacent roles — better to apply than miss):
- 80-100: Direct fit — Data Analyst, BI Analyst, Power BI Developer, Business Analyst, ML Engineer
- 65-80: Adjacent fit — Analytics Consultant, MIS Analyst, Reporting Analyst, Operations Analyst, Data Engineer (Python-based)
- 50-65: Stretch fit — Senior Data Analyst, Data Scientist, Financial Analyst (with data focus), Product Analyst
- 30-50: Weak fit — pure finance/accounting roles, healthcare-specific (Cerner), niche tools (Workday-only, SAP-only)
- 0-30: No fit — pure development roles (C++, .NET), QA/testing, sales, non-data domains

IMPORTANT SCORING RULES:
- Trainee/Intern/Junior roles: score 65+ (candidate can fit, willing to accept)
- Roles matching 3+ of his tools (Python, SQL, Power BI, Excel, Tableau, Statistics, ML): score 65+
- Roles requiring 5+ years in a specific domain he doesn't have (SAP FICO, Workday, Cerner, C++): score below 50
- If JD says "experience with dashboards / reporting / SQL / analytics" — score 70+
- If JD mentions manufacturing/operations/production analytics — score 75+ (his sweet spot)
- Do NOT skip roles just because company culture / seniority level differs — those are recruiter judgments

RESUME MODIFICATION RULES:
- Never invent experience or skills the candidate does not have
- LEGITIMATE additions (safe): data storytelling, KPI reporting, stakeholder management, requirement gathering, dashboard design, data cleaning, EDA, ad-hoc analysis, business intelligence, data visualization, analytical thinking, problem-solving, cross-functional collaboration
- ILLEGITIMATE additions (never): specific tools he doesn't use (Snowflake, Databricks, AWS, Azure, GCP, Airflow, dbt, Spark unless he specifically uses them), specific years in tools he barely used, certifications he doesn't have, domain expertise he lacks
- Prioritize Python, SQL, Power BI, Excel, Statistics, ML based on what the JD emphasizes
- Write summary in first person without using "I"
- Keep cover letter under 200 words
"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",   # fast + cheap for this task
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    result = json.loads(raw)
    return result


def should_apply(tailor_result: dict) -> bool:
    """Returns True if match score is good enough to apply."""
    score = tailor_result.get("match_score", 0)
    reason = tailor_result.get("match_reason", "")
    if "LOW MATCH - SKIP" in reason:
        return False
    return score >= SEARCH["min_match_score"]


# ── Quick test ────────────────────────────────────────────────
if __name__ == "__main__":
    test_jd = """
    We are looking for a Data Analyst with 3+ years of experience.
    Requirements: Python, SQL, Power BI or Tableau, statistical analysis,
    dashboard creation, stakeholder reporting. Experience in manufacturing
    or operations analytics is a plus. Scaler/upGrad background preferred.
    """

    print("Testing resume tailor with sample JD...\n")
    result = tailor_resume("Data Analyst", "Test Company", test_jd)
    print(f"Match Score : {result['match_score']}/100")
    print(f"Match Reason: {result['match_reason']}")
    print(f"\nSummary:\n{result['summary']}")
    print(f"\nSkills:\n{result['skills']}")
    print(f"\nCover Letter:\n{result['cover_letter']}")
    print(f"\nKeywords added: {result['keywords_added']}")
    print(f"\nShould apply: {should_apply(result)}")
