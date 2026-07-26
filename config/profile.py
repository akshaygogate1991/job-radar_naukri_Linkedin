# ============================================================
#  JOB AGENT — MASTER CONFIG
#  Edit this file only. Everything else reads from here.
# ============================================================

import os

# ── Secrets (NEVER hard-code these; kept out of git) ─────────
# Local laptop : put the real values in  secret_config.py  (gitignored).
# Cloud / CI   : set them as environment variables instead.
try:
    import secret_config as _sec
except Exception:
    _sec = None

def _secret(name, default=""):
    if _sec is not None and hasattr(_sec, name):
        return getattr(_sec, name)
    return os.getenv(name, default)

GMAIL_APP_PASSWORD = _secret("GMAIL_APP_PASSWORD")
ACCOUNT_PASSWORD   = _secret("ACCOUNT_PASSWORD")     # LinkedIn / Naukri / Hirist login
TELEGRAM_BOT_TOKEN = _secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = _secret("TELEGRAM_CHAT_ID")

# ── Personal details ─────────────────────────────────────────
CANDIDATE = {
    "name":         "Akshay Vinayak Gogate",
    "email":        "akshaygogate1991@gmail.com",
    "phone":        "+91 9767563384",
    "linkedin":     "https://www.linkedin.com/in/akshay-gogate-08a66278/",
    "location":     "Maharashtra, India",
    "notice_period": "30 days",          # update if needed
    "current_ctc":   "940000",  # fill actual value
    "expected_ctc":  "8-12 LPA",
}

# ── Job search settings ──────────────────────────────────────
SEARCH = {
    "roles": [
        # Core target roles
        "Data Analyst",
        "Senior Data Analyst",
        "Data Scientist",
        "Business Analyst",
        "Senior Business Analyst",
        # ML / Engineering roles
        "ML Engineer",
        "Machine Learning Engineer",
        "Analytics Engineer",
        # Additional roles matching your profile
        "BI Analyst",
        "Power BI Developer",
        "Operations Analyst",
        "MIS Analyst",
        "Reporting Analyst",
        # AI / Agent roles (new target)
        "AI Agent Developer",
        "AI Engineer",
        "Generative AI Engineer",
        "AI Automation Engineer",
        "Agentic AI Developer",
    ],
    "locations": [
        # Preferred cities
        "Mumbai",
        "Pune",
        "Remote",
        "Work from home",
        # Additional cities (remote-friendly or worth relocating)
        "Bangalore",
        "Hyderabad",
        "Navi Mumbai",
        "Thane",
    ],
    "experience_years": 2,
    "salary_min_lpa":   8,
    "salary_max_lpa":   12,

    # Jobs per day per platform (stay safe from bans)
    "max_per_day_linkedin": 10,
    "max_per_day_naukri":   10,
    "max_per_day_hirist": 10,

    # Minimum AI match score (0-100) to apply
    "min_match_score": 45,

    # Skip if already applied in last N days
    "skip_if_applied_within_days": 30,
}

# ── Skills master list (used for resume tailoring) ───────────
SKILLS = {
    "languages":    ["Python", "SQL"],
    "libraries":    ["Pandas", "NumPy", "Matplotlib", "Seaborn",
                     "Scikit-learn", "Streamlit"],
    "ml":           ["Linear Regression", "Logistic Regression",
                     "Decision Trees", "Random Forest", "XGBoost",
                     "K-Means Clustering", "PCA",
                     "Supervised Learning", "Unsupervised Learning"],
    "viz_tools":    ["Power BI", "Tableau", "Excel (Advanced)"],
    "databases":    ["SQL", "MySQL"],
    "erp_iot":      ["SAP", "INFOR LN", "Microsoft Navision",
                     "IoT Sensor Integration", "Power Automate"],
    "statistics":   ["Hypothesis Testing", "CLT", "ANOVA",
                     "Chi-Square", "T-Test", "Descriptive Statistics",
                     "Probability", "Confidence Intervals"],
    "soft_skills":  ["Root Cause Analysis", "Stakeholder Reporting",
                     "Cross-functional Collaboration",
                     "Predictive Maintenance", "Dashboard Design"],
    "learning_now": ["Neural Networks", "Computer Vision",
                     "Deep Learning"],
}

# ── Experience summary (used in Claude resume prompt) ────────
EXPERIENCE_SUMMARY = """
2 years of experience spanning Data/Business Analysis.
Currently: Business & Operations Analyst at Godrej & Boyce Interio (Oct 2022–Present).
  - Built Power BI dashboards that reduced machine downtime by 15%
  - Developed Power App for mobile-based inventory lookup eliminating manual SAP queries
  - Automated supplier communication via Microsoft Power Automate
  - Applied IoT sensor data + ERP systems for predictive maintenance

Previous: Assistant Manager – Maintenance (Data-Oriented) at Godrej & Boyce Aerospace (Nov 2019–Oct 2022)
  - INFOR LN for equipment reliability reports
  - Excel modeling cut excess inventory by 25%
  - Dashboards reduced downtime by 10%

Earlier roles at Glatt Systems (Sr. Maintenance Engineer) and Bombay Dyeing (Graduate Engineer Trainee).

Education: BE Mechanical – Mumbai University (2013)
Certification: Data Science & ML – Scaler Academy (Jul 2024–Present)
  Learning: Python, ML models, SQL, Statistics, Tableau, Product Analysis
  In progress: Neural Networks, Computer Vision

Key projects:
  - AI Job-Application Agent: Built an autonomous agent that scrapes multiple job portals, uses the Claude LLM API to match job descriptions and tailor resumes/cover letters, automates applications with Playwright, and surfaces results in a Streamlit + Supabase cloud dashboard. Demonstrates LLM/agent building, prompt engineering, and end-to-end automation.
  - Ola Driver Churn: Ensemble ML model with live prediction interface
  - LoanTap Credit Risk: Logistic regression for loan default prediction
  - Walmart CLT Analysis: Confidence intervals on Black Friday sales data
  - Yulu Hypothesis Testing: T-test/ANOVA on bike-sharing demand data
  - Target SQL Project: 100,000+ e-commerce orders analysis
"""

# ── Portfolio links (added to every tailored resume) ────────
GITHUB = "https://github.com/akshaygogate1991"

PROJECTS = [
    {
        "name":  "AI Job-Application Agent",
        "desc":  "Autonomous multi-portal agent — Claude LLM API for JD matching & resume tailoring, Playwright browser automation, Streamlit + Supabase dashboard",
        "url":   "https://github.com/akshaygogate1991/job-radar_naukri_Linkedin",
        "label": "GitHub",
    },
    {
        "name":  "Ola Driver Churn Prediction",
        "desc":  "Ensemble ML model with a live prediction app",
        "url":   "https://ola---ml-model-ensemble-learning-ypzklghpr6qff66jhjr7xp.streamlit.app/",
        "label": "Live app",
    },
    {
        "name":  "LoanTap Credit Risk Model",
        "desc":  "Logistic-regression loan-default prediction, deployed on Streamlit",
        "url":   "https://loantap-ml-model-logistic-regression-eqegxlmuxedm7fyyn4us2q.streamlit.app/",
        "label": "Live app",
    },
    {
        "name":  "Walmart CLT & Confidence Intervals",
        "desc":  "Statistical analysis of Black Friday purchasing behaviour",
        "url":   "https://github.com/akshaygogate1991/Walmart---Confidence-Interval-and-CLT",
        "label": "GitHub",
    },
    {
        "name":  "Yulu Hypothesis Testing",
        "desc":  "T-test, ANOVA & Chi-square on bike-sharing demand",
        "url":   "https://github.com/akshaygogate1991/Yulu---Hypothesis-Testing",
        "label": "GitHub",
    },
]

# Skills guaranteed to appear on EVERY tailored resume (merged with the
# JD-tailored skills the AI generates, so they never get dropped).
CORE_SKILLS = [
    "Power BI", "Power Automate", "Python", "SQL",
    "Machine Learning", "Generative AI (LLM) Integration", "Workflow Automation",
]

# ── Easy Apply default answers ───────────────────────────────
# Bot matches question text (lowercase, partial match) to these answers.
# If NO match is found, bot skips that job & sends Telegram alert
# with the exact question — add it here for next time.
EASY_APPLY_ANSWERS = {
    # Notice & relocation
    "notice period":                        "30",
    "how many days":                        "30",
    "relocate":                             "Yes",
    "willing to relocate":                  "Yes",

    # Work authorization — answers based on country
    "authorized to work in india":          "Yes",
    "authorized to work":                   "Yes",
    "legally authorized to work in india":  "Yes",
    "authorized to work in the united":     "No",
    "legally authorized to work in the":    "No",
    "require sponsorship":                  "No",
    "require employer sponsorship":         "No",
    "visa sponsorship":                     "No",
    "evidence of your right to work":       "Yes",
    "right to work":                        "Yes",
    "country of residence":                 "India",
    "preferred work location":              "Any",
    "opt or stem opt":                      "No",
    "currently on opt":                     "No",

    # Experience
    "years of experience":                  "2",
    "hands-on experience":                  "2",
    "hands on experience":                  "2",
    "years of hands":                       "2",
    "how many years":                       "2",
    "total experience":                     "10",
    "experience in data":                   "2",
    "experience in python":                 "2",
    "experience in sql":                    "2",
    "experience in power bi":               "3",
    "experience in tableau":                "2",
    "experience in machine learning":       "1",
    "experience in analytics":              "3",

    # Education — BE Mechanical 2013 (NOT masters)
    "master":                               "No",
    "have a master":                        "No",
    "bachelor":                             "Yes",
    "undergraduate":                        "Yes",
    "graduation year":                      "2013",
    "year.*degree":                         "2013",
    "year did you complete":                "2013",

    # Salary
    "current ctc":                          CANDIDATE["current_ctc"],
    "current salary":                       CANDIDATE["current_ctc"],
    "expected ctc":                         "10",
    "expected salary":                      "10",

    # Contact
    "phone number":                         CANDIDATE["phone"],
    "mobile number":                        CANDIDATE["phone"],
    "email":                                CANDIDATE["email"],
    "linkedin profile":                     CANDIDATE["linkedin"],
    "passport":                             "Yes",

    # Location  (edit "Mumbai" here if you relocate)
    "current location":                     "Mumbai",
    "current city":                         "Mumbai",
    "present location":                     "Mumbai",
    "where are you located":                "Mumbai",
    "preferred location":                   "Mumbai",
    "base location":                        "Mumbai",

    # Current job
    "current company":                      "Godrej & Boyce",
    "current employer":                     "Godrej & Boyce",
    "current designation":                  "Business & Operations Analyst",
    "current role":                         "Business & Operations Analyst",
    "current job title":                    "Business & Operations Analyst",

    # Availability / joining
    "when can you join":                    "Immediate",
    "available to join":                    "Immediate",
    "date of joining":                      "Immediate",
    "joining time":                         "Immediate",
    "earliest you can start":               "Immediate",

    # Work mode / general Yes-type screeners
    "work from office":                     "Yes",
    "willing to work from office":          "Yes",
    "comfortable working from":             "Yes",
    "work from home":                       "Yes",
    "shift":                                "Yes",
    "comfortable with":                     "Yes",

    # Education (extra phrasings)
    "highest qualification":                "Bachelor's Degree",
    "highest degree":                       "Bachelor's Degree",
    "qualification":                        "BE Mechanical",

    # Job change
    "reason for job change":                "Seeking growth and to fully transition into a data analytics role.",
    "reason for change":                    "Seeking growth and to fully transition into a data analytics role.",
    "reason for looking":                   "Seeking growth and to fully transition into a data analytics role.",

    # Company-website (Workday etc.) application questions
    "previously worked for":                "No",
    "previously been employed":             "No",
    "previously employed by":               "No",
    "worked for this organization":         "No",
    "worked for this company":              "No",
    "former employee":                      "No",
    "planned vacation":                     "No",
    "planned leave":                        "No",
    "appointments in the first":            "No",
    "criminal":                             "No",
    "convicted":                            "No",
    "non-compete":                          "No",
    "conflict of interest":                 "No",
    "related to any employee":              "No",
    "relative working":                     "No",
    "referred by":                          "No",
    "government official":                  "No",
    "background check":                     "Yes",
    "background verification":              "Yes",
    "drug test":                            "Yes",
    "terms and conditions":                 "Yes",
    "privacy policy":                       "Yes",
    "18 years":                             "Yes",
    "immediately available":                "Yes",
    "willing to work":                      "Yes",
    "how did you hear":                     "Job portal",
    "gender":                               "Male",
    # "date of birth":  "DD-MM-YYYY",   # <-- uncomment and fill your real DOB
}

# ── Address (used by company-site application forms) ─────────
# EDIT THESE with your real address — Workday forms require them.
ADDRESS = {
    "line1":       "Gogate Wada, vitthal nagar",              # <-- put your street address here
    "city":        "Karjat",
    "state":       "Maharashtra",
    "postal_code": "410201",              # <-- put your real PIN code here
    "country":     "India",
}

# ── Platforms ────────────────────────────────────────────────
PLATFORMS = {
    "linkedin": {
        "enabled":  True,
        "email":    CANDIDATE["email"],
        "password": ACCOUNT_PASSWORD,
        "easy_apply_only": True,
    },
    "naukri": {
        "enabled":  True,
        "email":    CANDIDATE["email"],
        "password": ACCOUNT_PASSWORD,
    },
   "hirist": {
        "enabled": True,
        "email": CANDIDATE["email"],
        "password": ACCOUNT_PASSWORD,
    },
}

# ── Notification ─────────────────────────────────────────────
TELEGRAM = {
    "enabled":    True,
    "bot_token":  TELEGRAM_BOT_TOKEN,
    "chat_id":    TELEGRAM_CHAT_ID,
}

# ── Paths ─────────────────────────────────────────────────────
import os
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESUME_PDF   = os.path.join(BASE_DIR, "resumes", "akshay_master_resume.pdf")
LOG_FILE     = os.path.join(BASE_DIR, "logs",    "applications.json")
SHEETS_LOG   = os.path.join(BASE_DIR, "logs",    "applications.csv")
